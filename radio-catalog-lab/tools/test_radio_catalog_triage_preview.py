"""Synthetic tests only: never copy private stations or real favorites here."""
import copy
import unittest

from radio_catalog_triage_preview import build_triage


UUID_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
UUID_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def fixture():
    coverage = {
        "ready_to_publish": False, "coverage_gate_passed": False,
        "missing_historical_alias_count": 0, "alias_collisions": [],
        "missing_admissible_uuid_count": 2,
        "missing_admissible_uuids": [UUID_A, UUID_B],
    }
    evidence = {
        "total_uuid_reviewed": 2,
        "classification_counts": {
            "same_stream_and_name_review": 1, "not_found_directory_recheck": 1,
        },
        "rows": [
            {
                "uuid": UUID_A, "classification": "same_stream_and_name_review",
                "approval": "HUMAN_REVIEW_REQUIRED", "auto_admit": False,
                "auto_merge": False, "delete_previous_alias": False,
                "directory_found": True, "directory_name": "Synthetic Station",
                "exact_stream_matches": [{"go_station_id": "go-station-999001"}],
                "exact_name_matches": [{"go_station_id": "go-station-999001"}],
            },
            {
                "uuid": UUID_B, "classification": "not_found_directory_recheck",
                "approval": "HUMAN_REVIEW_REQUIRED", "auto_admit": False,
                "auto_merge": False, "delete_previous_alias": False,
                "directory_found": False, "directory_name": None,
                "exact_stream_matches": [], "exact_name_matches": [],
            },
        ],
    }
    return coverage, evidence


class TriageTest(unittest.TestCase):
    def test_safe_preview_never_approves(self):
        coverage, evidence = fixture()
        before = copy.deepcopy(evidence)
        result = build_triage(coverage, evidence)
        self.assertEqual(result["total_missing_uuids"], 2)
        self.assertFalse(result["ready_to_publish"])
        self.assertFalse(result["catalog_change_authorized"])
        self.assertTrue(all(not r["catalog_change_authorized"] for r in result["rows"]))
        self.assertEqual(evidence, before)

    def test_missing_review_uuid_is_rejected(self):
        c, e = fixture()
        e["rows"][1]["uuid"] = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
        with self.assertRaises(ValueError):
            build_triage(c, e)

    def test_duplicate_uuid_is_rejected(self):
        c, e = fixture()
        e["rows"][1]["uuid"] = UUID_A
        with self.assertRaises(ValueError):
            build_triage(c, e)

    def test_automerge_is_rejected(self):
        c, e = fixture()
        e["rows"][0]["auto_merge"] = True
        with self.assertRaises(ValueError):
            build_triage(c, e)

    def test_forged_approval_is_rejected(self):
        c, e = fixture()
        e["rows"][0]["approval"] = "APPROVED"
        with self.assertRaises(ValueError):
            build_triage(c, e)

    def test_lost_legacy_alias_is_rejected(self):
        c, e = fixture()
        c["missing_historical_alias_count"] = 1
        with self.assertRaises(ValueError):
            build_triage(c, e)

    def test_missing_exact_name_evidence_is_rejected(self):
        c, e = fixture()
        e["rows"][0]["exact_name_matches"] = []
        with self.assertRaises(ValueError):
            build_triage(c, e)

    def test_false_directory_presence_is_rejected(self):
        c, e = fixture()
        e["rows"][1]["directory_found"] = True
        with self.assertRaises(ValueError):
            build_triage(c, e)

    def test_unrecognized_classification_is_rejected(self):
        c, e = fixture()
        e["rows"][0]["classification"] = "safe_auto_merge"
        with self.assertRaises(ValueError):
            build_triage(c, e)

    def test_counts_mismatch_is_rejected(self):
        c, e = fixture()
        e["classification_counts"]["same_stream_and_name_review"] = 2
        with self.assertRaises(ValueError):
            build_triage(c, e)


if __name__ == "__main__":
    unittest.main()
