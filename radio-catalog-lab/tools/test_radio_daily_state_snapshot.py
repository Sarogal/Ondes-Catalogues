import copy
import json
import tempfile
import unittest
from pathlib import Path
from radio_daily_state_snapshot import transition, POINTER, BODY
from radio_daily_release_context import STATE_FILES, REQUALIFY
from radio_daily_v9_generator import encode, digest
from test_radio_daily_baseline_selection import setup as selection_setup, signed
from test_radio_daily_state_migration import repair_setup
from test_radio_daily_repair_plan import DAY


class StateSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        _, _, self.key, _, _, _, _, self.anchor = selection_setup()
        old, self.new, state = repair_setup()
        self.pointer, self.raw = signed(old, self.key)
        self.next_pointer, self.next_body = signed(self.new, self.key)
        self.anchor["expected_sha"] = digest(self.raw)
        self.previous = self.root / "v8"
        self.previous.mkdir()
        (self.previous / POINTER).write_bytes(self.pointer)
        (self.previous / BODY).write_bytes(self.raw)
        for key, name in STATE_FILES.items():
            (self.previous / name).write_bytes(encode(state[key]))
        for name in REQUALIFY:
            (self.previous / name).write_bytes(encode(dict(schemaVersion=1,
                publicationAllowed=False,catalogBaselineSha256=digest(self.raw),records=[])))
        (self.previous / "ledger.json").write_bytes(encode(dict(schemaVersion=1,
            publicationAllowed=False,records=[])))

    def advance(self, pointer=None, body=None, output=None, **kw):
        return transition(self.previous, output or self.root/"v9",
            self.next_pointer if pointer is None else pointer,
            lambda path,length: self.next_body if body is None else body,
            day=DAY, anchor=self.anchor, **kw)

    def test_complete_transition_preserves_predecessor_and_invalidates_decisions(self):
        before={p.name:p.read_bytes() for p in self.previous.iterdir()}
        ctx=self.advance()
        target=self.root/"v9"
        self.assertTrue(ctx["advanced"])
        self.assertEqual((target/BODY).read_bytes(),self.next_body)
        self.assertEqual((target/POINTER).read_bytes(),self.next_pointer)
        for name in STATE_FILES.values():
            report=json.loads((target/name).read_bytes())
            self.assertEqual(report["catalogBaselineSha256"],digest(self.next_body))
        self.assertTrue((target/"ledger.json").exists())
        self.assertTrue(all(not (target/name).exists() for name in REQUALIFY))
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.previous.iterdir()})

    def test_same_version_keeps_compatible_reports(self):
        ctx=self.advance(pointer=self.pointer,body=self.raw)
        self.assertFalse(ctx["advanced"])
        self.assertTrue(all((self.root/"v9"/name).exists() for name in REQUALIFY))

    def test_repeated_successor_migration(self):
        self.advance()
        third=copy.deepcopy(self.new)
        third["release_sequence"]=10
        p10,b10=signed(third,self.key)
        ctx=transition(self.root/"v9",self.root/"v10",p10,lambda path,length:b10,
            day=DAY,anchor=dict(self.anchor,expected_sha=digest(self.next_body),expected_sequence=9))
        self.assertEqual(ctx["selectedSequence"],10)
        self.assertEqual((self.root/"v10"/BODY).read_bytes(),b10)
        self.assertTrue(all(json.loads((self.root/"v10"/name).read_bytes())
            ["catalogBaselineSha256"]==digest(b10) for name in STATE_FILES.values()))

    def test_tampered_body_leaves_no_snapshot(self):
        with self.assertRaises(ValueError):
            self.advance(body=self.next_body+b" ")
        self.assertFalse((self.root/"v9").exists())

    def test_missing_evidence_leaves_no_snapshot(self):
        (self.previous/STATE_FILES["repair"]).unlink()
        with self.assertRaises(ValueError):
            self.advance()
        self.assertFalse((self.root/"v9").exists())

    def test_invalid_observation_leaves_no_snapshot(self):
        (self.previous/"ledger.json").write_bytes(encode(dict(schemaVersion=1,publicationAllowed=True)))
        with self.assertRaisesRegex(ValueError,"untrusted observation"):
            self.advance()
        self.assertFalse((self.root/"v9").exists())

    def test_existing_destination_is_untouched(self):
        target=self.root/"v9"
        target.mkdir()
        (target/"keep").write_text("unchanged")
        with self.assertRaisesRegex(ValueError,"fresh successor"):
            self.advance()
        self.assertEqual((target/"keep").read_text(),"unchanged")

    def test_wrong_trusted_predecessor_rejected(self):
        self.anchor["expected_sha"]="0"*64
        with self.assertRaises(ValueError):
            self.advance()
        self.assertFalse((self.root/"v9").exists())

    def test_bound_observation_not_reused_after_advance(self):
        (self.previous/"metadata-preview.json").write_bytes(encode(dict(schemaVersion=1,
            publicationAllowed=False,catalogBaselineSha256=digest(self.raw))))
        self.advance()
        self.assertFalse((self.root/"v9"/"metadata-preview.json").exists())

    def test_rollback_after_advancement_rejected(self):
        self.advance()
        with self.assertRaisesRegex(ValueError,"rollback"):
            transition(self.root/"v9",self.root/"rollback",self.pointer,lambda path,length:self.raw,
                day=DAY,anchor=dict(self.anchor,expected_sha=digest(self.next_body),expected_sequence=9))
        self.assertFalse((self.root/"rollback").exists())


if __name__=="__main__":
    unittest.main()
