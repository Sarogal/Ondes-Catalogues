"""Two Cargö historical corrections, review-only and fail closed.

Both first-party detail pages prove musical start at 20:30; calendar cards
formerly exposed 20:00/19:30 door times. No other of the initial 127
concerts may be changed, and proof must remain in the private approval feed.
"""
import copy
import datetime as dt
import json
from pathlib import Path
import unittest
from scripts import concerts_cloud_sync as sync

ROOT = Path(__file__).resolve().parents[1]
REF = json.loads((ROOT / "docs/grossesondes/concerts-reference.json").read_text(
    encoding="utf-8"))
DATE = dt.date(2026, 11, 3)
IDS = tuple(sorted(sync.CARGO_REFERENCE_TIME_FIXES))


def legacy():
    return {
        "eventId": sync.LEGACY_LINEUP_ID,
        "reviewDecision": "approved",
        "reviewedBy": "independent-official-verifier",
        "reviewedAt": "2026-11-02",
        "eventPatch": copy.deepcopy(sync.LEGACY_LINEUP_PATCH),
        "officialEvidence": [{
            "url": sync.LEGACY_LINEUP_SOURCE,
            "proofType": "official-venue-detail",
            "checkedAt": "2026-11-02",
            "checkedFields": ["artists", "date", "venue", "startTime"],
        }],
    }


def approval(event_id):
    spec = sync.CARGO_REFERENCE_TIME_FIXES[event_id]
    return {
        "eventId": event_id,
        "reviewDecision": "approved",
        "reviewedBy": "independent-official-verifier",
        "reviewedAt": "2026-11-03",
        "eventPatch": copy.deepcopy(spec["eventPatch"]),
        "officialEvidence": [{
            "url": spec["officialUrl"],
            "proofType": "official-venue-detail",
            "checkedAt": "2026-11-03",
            "checkedFields": ["artists", "date", "venue",
                              "doorTime", "concertStartTime"],
            "doorTimeConfirmed": spec["doorTime"],
            "concertStartTimeConfirmed": "20:30",
        }],
    }


def queue(ids=IDS):
    return {
        "schema": sync.SCHEMA, "approvals": [],
        "referenceCorrections": [legacy()],
        "referenceEventTimeCorrections": [approval(i) for i in ids],
    }


class CargoHistoricalCorrectionTests(unittest.TestCase):
    def test_full_original_reference_is_preserved(self):
        x = sync.corrected_reference_event_state(
            REF, legacy=True, cargo_ids=IDS)
        self.assertEqual(len(x), len(REF["events"]))
        originals = {e["id"]: e for e in REF["events"]}
        for item in x:
            with self.subTest(item=item["id"]):
                old = originals[item["id"]]
                if item["id"] in IDS:
                    spec = sync.CARGO_REFERENCE_TIME_FIXES[item["id"]]
                    self.assertEqual(item["time"], "20:30")
                    self.assertEqual(item["timeMeaning"], "début du concert")
                    self.assertEqual(item["officialUrl"], spec["officialUrl"])
                    self.assertEqual(item["date"], old["date"])
                    self.assertEqual(item["artistIds"], old["artistIds"])
                    self.assertEqual(item["venueId"], old["venueId"])
                    self.assertEqual(item["history"][:-1], old["history"])
                    self.assertEqual(item["history"][-1], spec["history"])
                elif item["id"] != sync.LEGACY_LINEUP_ID:
                    self.assertEqual(item, old)
        self.assertNotEqual(REF["events"], x)
        self.assertEqual(REF["events"][21]["time"], "20:00")

    def test_signed_corrections_merge_and_second_run_idempotent(self):
        q = queue()
        once, summary = sync.merge(REF, REF, q, DATE)
        self.assertEqual(summary["correctedEvents"], 3)  # existing Lost in Kyiv + 2
        self.assertEqual(summary["newEvents"], 0)
        sync.protect_reference(REF, once)
        again, counts = sync.merge(REF, once, q, DATE)
        self.assertEqual(again, once)
        self.assertEqual(counts["correctedEvents"], 0)
        self.assertEqual(len(again["events"]), 127)

    def test_corrections_work_independently_with_existing_legacy_fix(self):
        current = copy.deepcopy(REF)
        current["events"] = sync.legacy_corrected_events(REF)
        changed, counts = sync.merge(REF, current, queue(), DATE)
        self.assertEqual(counts["correctedEvents"], 2)
        self.assertEqual(changed["events"][:127],
                         sync.corrected_reference_event_state(
                             REF, legacy=True, cargo_ids=IDS))
        single, counts = sync.merge(REF, current, queue(IDS[:1]), DATE)
        self.assertEqual(counts["correctedEvents"], 1)
        self.assertEqual(single["events"][21]["time"], "20:30")

    def test_malformed_private_proofs_and_time_patch_fail_closed(self):
        variants = []
        for index in range(len(IDS)):
            for field, value in (
                ("doorTimeConfirmed", "23:00"),
                ("concertStartTimeConfirmed", "20:00"),
                ("url", "https://lecargo.fr/programmation/concert/"),
                ("checkedAt", "2026-11-02"),
                ("proofType", "first-party-calendar"),
                ("checkedFields", ["artists", "date", "venue"])):
                q = queue()
                q["referenceEventTimeCorrections"][index]["officialEvidence"][0][field] = value
                variants.append(q)
            for field, value in (
                ("time", "19:30"), ("date", "2026-11-12"),
                ("artistIds", ["incorrect-band"]), ("officialUrl", "https://wrong.test")):
                q = queue()
                q["referenceEventTimeCorrections"][index]["eventPatch"][field] = value
                variants.append(q)
        missing = queue()
        missing["referenceEventTimeCorrections"][0]["reviewedBy"] = "automatic-guess"
        variants.append(missing)
        dup = queue()
        dup["referenceEventTimeCorrections"][1] = copy.deepcopy(
            dup["referenceEventTimeCorrections"][0])
        variants.append(dup)
        unknown = queue()
        unknown["referenceEventTimeCorrections"][0]["eventId"] = "invented-concert"
        variants.append(unknown)
        for i, q in enumerate(variants):
            with self.subTest(case=i), self.assertRaises((ValueError, KeyError, TypeError)):
                sync.merge(REF, REF, q, DATE)

    def test_a_published_fix_must_keep_its_private_evidence(self):
        corrected, _ = sync.merge(REF, REF, queue(), DATE)
        removed = queue(IDS[:1])
        with self.assertRaises(ValueError):
            sync.merge(REF, corrected, removed, DATE)
        removed_all = queue(())
        with self.assertRaises(ValueError):
            sync.merge(REF, corrected, removed_all, DATE)
        tampered = copy.deepcopy(corrected)
        found = next(e for e in tampered["events"] if e["id"] == IDS[0])
        found["date"] = "2026-11-14"
        with self.assertRaises(ValueError):
            sync.protect_reference(REF, tampered)
        modified = copy.deepcopy(corrected)
        modified["events"][0]["title"] = "unreviewed title"
        with self.assertRaises(ValueError):
            sync.protect_reference(REF, modified)


if __name__ == "__main__":
    unittest.main()
