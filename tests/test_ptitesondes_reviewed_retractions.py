"""Safety checks for the reviewed, non-Publisher editorial withdrawal route."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from ptitesondes_reviewed_retractions import reviewed_retraction, digest

CAT = ROOT / "docs/ptitesondes/sorties.json"
MANIFEST = ROOT / "config/ptitesondes-reviewed-retractions-20261122.json"


def fixture():
    document = json.loads(CAT.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    # Regression fixtures must be reproducible even after this one-off
    # correction has succeeded on main. Restore the nine immutable,
    # source-reviewed snapshots IN MEMORY only for the negative tests.
    seen = {e["id"] for e in document["events"]}
    for approval in manifest["approvals"]:
        original = approval["expected_event"]
        if original["id"] not in seen:
            document["events"].append(deepcopy(original))
            seen.add(original["id"])
    return document, manifest


class EditorialRetractionTests(unittest.TestCase):
    def test_exact_nine_reviewed_records_are_removed_and_every_other_row_kept(self):
        catalogue, plan = fixture()
        before = deepcopy(catalogue)
        after, audit, changed = reviewed_retraction(catalogue, plan)
        self.assertTrue(changed)
        self.assertEqual(len(audit["withdrawn"]), 9)
        self.assertEqual(audit["after_count"], audit["before_count"] - 9)
        self.assertEqual(audit["catalogue_before_sha256"], digest(before))
        target_ids = {a["expected_event"]["id"] for a in plan["approvals"]}
        self.assertEqual({a["id"] for a in audit["withdrawn"]}, target_ids)
        self.assertEqual(after["events"], [
            e for e in before["events"] if e["id"] not in target_ids])
        self.assertEqual(catalogue, before)  # Pure function, no input mutation
        self.assertTrue(any(e["title"] ==
                            "Créez et enregistrez votre musique en studio"
                            for e in after["events"]))

    def test_repeated_correction_is_idempotent(self):
        original, plan = fixture()
        after, audit, changed = reviewed_retraction(original, plan)
        again, second_audit, again_changed = reviewed_retraction(after, plan)
        self.assertTrue(changed)
        self.assertFalse(again_changed)
        self.assertIsNone(second_audit)
        self.assertEqual(again, after)

    def test_an_unrelated_new_public_event_is_preserved(self):
        original, plan = fixture()
        new_event = dict(original["events"][0], id="new-future-unrelated-2027-01-01")
        original["events"].append(new_event)
        after, audit, changed = reviewed_retraction(original, plan)
        self.assertTrue(changed)
        self.assertIn(new_event, after["events"])
        self.assertEqual(len(after["events"]), len(original["events"])-9)

    def test_changed_target_event_halts_every_removal(self):
        original, plan = fixture()
        original["events"][-1]["city"] = "Different city"
        # Last event is not in the manifest: verify instead a targeted row.
        target_id = plan["approvals"][0]["expected_event"]["id"]
        for item in original["events"]:
            if item["id"] == target_id:
                item["venue"] = "Unexpected venue"
        with self.assertRaisesRegex(ValueError, "reviewed_record_changed"):
            reviewed_retraction(original, plan)

    def test_partially_applied_transaction_cannot_erase_more_rows(self):
        original, plan = fixture()
        eid = plan["approvals"][0]["expected_event"]["id"]
        original["events"] = [e for e in original["events"] if e["id"] != eid]
        with self.assertRaisesRegex(ValueError, "partially_applied"):
            reviewed_retraction(original, plan)

    def test_unreviewed_id_and_duplicate_plan_are_rejected(self):
        original, plan = fixture()
        extra = deepcopy(plan)
        extra["approvals"].append(deepcopy(extra["approvals"][0]))
        with self.assertRaisesRegex(ValueError, "invalid_approval_identity"):
            reviewed_retraction(original, extra)
        extra = deepcopy(plan)
        extra["approvals"][0]["expected_event"]["id"] = "some-historic-event"
        with self.assertRaisesRegex(ValueError, "invalid_approval_identity"):
            reviewed_retraction(original, extra)

    def test_reason_cannot_be_changed_without_consistent_main_activity(self):
        original, plan = fixture()
        plan["approvals"][0]["reason_code"] = "non_performance_gathering_primary"
        with self.assertRaisesRegex(ValueError, "invalid_approval_identity"):
            reviewed_retraction(original, plan)

    def test_actual_published_catalogue_is_safe_to_recheck_after_withdrawal(self):
        actual = json.loads(CAT.read_text(encoding="utf-8"))
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        present = {
            x["expected_event"]["id"] for x in manifest["approvals"]
            if any(e["id"] == x["expected_event"]["id"] for e in actual["events"])
        }
        if not present:
            corrected, audit, changed = reviewed_retraction(actual, manifest)
            self.assertFalse(changed)
            self.assertIsNone(audit)
            self.assertEqual(corrected, actual)

    def test_dry_run_never_changes_catalogue_bytes(self):
        original_bytes = CAT.read_bytes()
        original, plan = fixture()
        reviewed_retraction(original, plan)
        self.assertEqual(CAT.read_bytes(), original_bytes)


if __name__ == "__main__":
    unittest.main()
