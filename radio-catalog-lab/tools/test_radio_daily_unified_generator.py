import copy
import json
import unittest

from radio_daily_unified_generator import build
from radio_daily_decision_preview import decide
from radio_daily_repair_plan import plan
from radio_daily_v9_generator import digest, encode
from radio_daily_maintenance_preview import build as maintenance
from radio_daily_repair_preview import build as repair
from radio_daily_repair_confirmation import build as confirm
from test_radio_daily_repair_plan import fixture as repair_fixture, SID, NEW, DAY
from test_radio_daily_v9_generator import fixture as addition_fixture


def repair_inputs(strong=True):
    raw, sha, m, r, c = repair_fixture(strong=strong)
    d = {"schemaVersion": 1, "scanDate": DAY, "publicationAllowed": False, "candidates": []}
    e = {"schemaVersion": 1, "scanDate": DAY, "publicationAllowed": False,
         "approvedCount": 0, "catalogBaselineSha256": sha, "records": []}
    return raw, d, e, decide(d,e,sha), m, r, c, plan(raw,m,r,c,expected=sha)


def addition_inputs():
    raw,d,e = addition_fixture()
    doc = json.loads(raw)
    # Maintenance requires at least one stream per live catalogue row.
    doc["stations"] = doc["stations"][:1]
    raw = encode(doc)
    sha = digest(raw)
    e["catalogBaselineSha256"] = sha
    day = d["scanDate"]
    m = maintenance(raw,day,expected=sha)
    r = repair(raw,m,d,expected=sha)
    c = confirm(raw,r,expected=sha)
    return raw,d,e,decide(d,e,sha),m,r,c,plan(raw,m,r,c,expected=sha)


def run(args, **kwargs):
    return build(*args, expected=digest(args[0]), **kwargs)


class UnifiedTests(unittest.TestCase):
    def test_addition_preserves_baseline(self):
        args = addition_inputs()
        payload, report = run(args)
        old,new = json.loads(args[0]),json.loads(payload)
        self.assertEqual(new["stations"][:-1],old["stations"])
        self.assertEqual(new["tombstones"],old["tombstones"])
        self.assertEqual(report["candidateSequence"],9)
        self.assertEqual(report["candidateSha256"],digest(payload))
        self.assertEqual(run(args),(payload,report))

    def test_repair_without_url_is_deferred(self):
        payload, report = run(repair_inputs())
        self.assertIsNone(payload)
        self.assertIsNone(report["candidateSequence"])
        self.assertEqual(report["repairDeferred"][0]["reason"],"replacement_material_incomplete")

    def test_repair_preserves_station_and_increments_once(self):
        args = repair_inputs()
        payload, report = run(args,urls={(SID,digest(NEW.encode())):NEW})
        old,new = json.loads(args[0]),json.loads(payload)
        self.assertEqual(new["release_sequence"],9)
        self.assertEqual(len(report["repaired"]),1)
        self.assertFalse(report["publicationAllowed"])
        new["stations"][0]["streams"].pop()
        self.assertEqual(new["stations"],old["stations"])

    def test_no_change_no_candidate(self):
        payload,report = run(repair_inputs(strong=False))
        self.assertIsNone(payload)
        self.assertFalse(report["changed"])

    def test_refuse_forged_report(self):
        args = list(repair_inputs())
        args[-1] = dict(args[-1],approvedCount=1)
        with self.assertRaisesRegex(ValueError,"repair plan mismatch"):
            run(args)

    def test_refuse_mixed_days(self):
        args = list(repair_inputs())
        args[-1] = dict(args[-1],scanDate="2026-11-25")
        with self.assertRaisesRegex(ValueError,"date mismatch"):
            run(args)

    def test_refuse_unknown_or_changed_material(self):
        args = repair_inputs()
        with self.assertRaises(ValueError):
            run(args,urls={(SID,"a"*64):NEW})
        with self.assertRaises(ValueError):
            run(args,urls={(SID,digest(NEW.encode())):NEW+"2"})


if __name__ == "__main__":
    unittest.main()
