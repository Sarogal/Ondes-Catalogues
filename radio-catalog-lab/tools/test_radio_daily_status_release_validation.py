import copy
import json
import unittest
from radio_daily_status_release_validation import validate_status_release, publish_status_release
from radio_daily_lab_signing import EphemeralLabSigner
from radio_daily_publication_simulator import MemoryStore, verify_visible
from radio_daily_unified_generator import build
from radio_daily_decision_preview import decide
from radio_daily_repair_preview import build as repair
from radio_daily_repair_confirmation import build as confirm
from radio_daily_repair_plan import plan
from radio_daily_status_preview import build as status_build
from radio_daily_v9_generator import digest, encode
from test_radio_daily_baseline_selection import signed
from test_radio_daily_status_preview import setup, run
from test_radio_daily_repair_plan import DAY, SID


class IndependentStatusGateTests(unittest.TestCase):
    def fixture(self, quarantined=False, redirect=False, count=1, synthetic=False):
        self.signer = EphemeralLabSigner()
        raw, _ = setup(quarantined=quarantined, redirect=redirect, count=count)
        doc = json.loads(raw)
        for row in doc["stations"]:
            row["logo"] = None
            row["editorial"].update(admission_state="approved", reviewed_at=DAY+"T00:00:00Z")
        if synthetic:
            doc["stations"][0]["status"]["reason_code"] = "synthetic_diagnostic_not_for_playback"
        self.pointer, self.raw = signed(doc, self.signer._key, self.signer.key_id)
        sha = digest(self.raw)
        self.anchor = dict(expected_sha=sha, expected_sequence=8,
                           public_key=self.signer.public_key, key_id=self.signer.key_id)
        m = st = None
        for day in ("2026-11-24", "2026-11-25", DAY):
            m, st = run(self.raw, sha, day, m, st, positive=quarantined)
        d = dict(schemaVersion=1, scanDate=DAY, publicationAllowed=False, candidates=[])
        e = dict(schemaVersion=1, scanDate=DAY, publicationAllowed=False, approvedCount=0,
                 catalogBaselineSha256=sha, records=[])
        r = repair(self.raw, m, d, expected=sha)
        c = confirm(self.raw, r, expected=sha)
        rp = plan(self.raw, m, r, c, expected=sha)
        st = status_build(self.raw, m, rp, expected=sha, prior=st)
        self.evidence = dict(maintenance=m, repair=r, confirmation=c, status=st)
        self.candidate, _ = build(self.raw, d, e, decide(d,e,sha), m,r,c,rp,st, expected=sha)

    def verify(self, candidate=None, **kw):
        args = dict(anchor=self.anchor, day=DAY, **self.evidence)
        args.update(kw)
        return validate_status_release(self.pointer, self.raw,
            self.candidate if candidate is None else candidate, **args)

    def manual_transition(self, to):
        doc = json.loads(self.raw)
        doc.update(release_sequence=9, generated_at=DAY+"T00:00:00Z")
        doc["stations"][0]["status"].update(state=to,
            reason_code="experimental_recovery_review" if to=="active"
                        else "experimental_unavailability_review",
            changed_at=DAY+"T00:00:00Z")
        return encode(doc)

    def test_quarantine_exact_generated_delta_accepted(self):
        self.fixture()
        self.assertEqual(self.verify(), digest(self.candidate))
        self.assertEqual(json.loads(self.candidate)["stations"][0]["status"]["state"], "quarantined")

    def test_recovery_exact_generated_delta_accepted(self):
        self.fixture(quarantined=True)
        self.assertEqual(self.verify(), digest(self.candidate))
        self.assertEqual(json.loads(self.candidate)["stations"][0]["status"]["state"], "active")

    def test_forged_proposal_refused(self):
        self.fixture()
        st = copy.deepcopy(self.evidence["status"])
        st["proposals"][0]["to"] = "active"
        with self.assertRaisesRegex(ValueError, "status evidence mismatch"):
            self.verify(status=st)

    def test_stale_evidence_refused(self):
        self.fixture()
        st = dict(self.evidence["status"], scanDate="2026-11-25")
        with self.assertRaisesRegex(ValueError, "status evidence date mismatch"):
            self.verify(status=st)

    def test_unrelated_stream_change_refused(self):
        self.fixture()
        doc = json.loads(self.candidate)
        doc["stations"][0]["streams"][0]["url"] = "https://radio.example.org/injected"
        with self.assertRaisesRegex(ValueError, "unauthorized catalogue delta"):
            self.verify(encode(doc))

    def test_mass_transition_refused(self):
        self.fixture(count=4)
        self.assertIsNone(self.candidate)
        with self.assertRaisesRegex(ValueError, "no qualified status transition"):
            self.verify(self.manual_transition("quarantined"))

    def test_synthetic_recovery_refused(self):
        self.fixture(quarantined=True, synthetic=True)
        self.assertIsNone(self.candidate)
        with self.assertRaisesRegex(ValueError, "no qualified status transition"):
            self.verify(self.manual_transition("active"))

    def test_protected_redirect_refused(self):
        self.fixture(redirect=True)
        self.assertIsNone(self.candidate)
        with self.assertRaises(ValueError):
            self.verify(self.manual_transition("quarantined"))

    def test_publication_requires_exact_delta(self):
        self.fixture(quarantined=True)
        store = MemoryStore(self.pointer,self.raw)
        doc = json.loads(self.candidate)
        doc["stations"][0]["display_name"] = "Injected"
        body = encode(doc)
        args = dict(expected_sha=self.anchor["expected_sha"], expected_sequence=8,
                    day=DAY, **self.evidence)
        with self.assertRaisesRegex(ValueError,"unauthorized catalogue delta"):
            publish_status_release(store,self.signer,self.pointer,self.raw,body,
                expected_candidate_sha=digest(body), **args)
        self.assertEqual(store.current(),self.pointer)
        result = publish_status_release(store,self.signer,self.pointer,self.raw,self.candidate,
                expected_candidate_sha=digest(self.candidate), **args)
        self.assertEqual(result["sequence"],9)
        verify_visible(store,store.current(),sha=digest(self.candidate),sequence=9,signer=self.signer)


if __name__=="__main__":
    unittest.main()
