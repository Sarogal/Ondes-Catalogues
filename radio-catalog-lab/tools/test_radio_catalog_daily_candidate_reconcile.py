"""Synthetic tests only: discovery NEVER edits or filters the central catalog."""
import copy
import unittest

from radio_catalog_daily_candidate_reconcile import index_catalog, review_candidates

ID_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
ID_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
ID_C = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
ID_D = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"


def catalog():
    return {
        "schema_version": 1,
        "stations": [
            {
                "go_station_id": "go-radio-bob-a",
                "display_name": "RADIO BOB! DEATH METAL",
                "country_code": "DE",
                "legacy_aliases": [ID_A],
                "radio_browser_uuids": [{"uuid": ID_A, "state": "current"}],
                "streams": [{"url": "https://bob.example/metal"}],
            },
            {
                "go_station_id": "go-metal-b",
                "display_name": "Metal Underground",
                "country_code": "FR",
                "legacy_aliases": [ID_B],
                "radio_browser_uuids": [{"uuid": ID_B, "state": "current"}],
                "streams": [{"url": "https://underground.example/stream"}],
            },
        ],
        "tombstones": [],
    }


def candidate(uid, name="Metal Wave", country="FR", stream="https://new.example/radio",
              status="candidate_requires_qualification", duplicate=False):
    return {
        "stationuuid": uid, "name": name, "countrycode": country,
        "streamUrl": stream, "status": status,
        "duplicateIdentityRisk": duplicate,
    }


def discovery(rows):
    return {
        "schemaVersion": 1, "scanDate": "2026-11-20",
        "publicationAllowed": False, "candidates": rows,
    }


class DailyReconciliationTests(unittest.TestCase):
    def test_new_uuid_not_in_allowlist_remains_candidate(self):
        saved = catalog()
        frozen = copy.deepcopy(saved)
        report = review_candidates(saved, discovery([candidate(ID_C)]))
        self.assertEqual(report["counts"]["unmapped_candidate"], 1)
        self.assertFalse(report["automaticAdmissionAllowed"])
        self.assertFalse(report["catalogChanged"])
        self.assertEqual(saved, frozen)

    def test_radio_bob_existing_uuid_is_never_deleted(self):
        report = review_candidates(catalog(), discovery([
            candidate(ID_A, "RADIO BOB! DEATH METAL", "DE", "https://bob.example/metal"),
        ]))
        self.assertEqual(report["counts"]["already_mapped"], 1)
        self.assertEqual(report["candidates"][0]["existingGoStationId"], "go-radio-bob-a")

    def test_same_country_name_with_new_uuid_requires_review_not_merge(self):
        report = review_candidates(catalog(), discovery([
            candidate(ID_C, "Metal Underground", "FR"),
        ]))
        self.assertEqual(report["counts"]["possible_variant_or_duplicate"], 1)
        self.assertEqual(report["candidates"][0]["possibleGoStationIds"], ["go-metal-b"])

    def test_exact_stream_url_with_different_name_is_not_auto_merged(self):
        report = review_candidates(catalog(), discovery([
            candidate(ID_C, "Other Band Radio", "FR",
                      "https://underground.example/stream"),
        ]))
        self.assertEqual(report["counts"]["possible_variant_or_duplicate"], 1)
        self.assertFalse(report["automaticAdmissionAllowed"])

    def test_blacklisted_candidate_by_legacy_baseline_not_new(self):
        report = review_candidates(catalog(), discovery([candidate(ID_D)]), {ID_D})
        self.assertEqual(report["counts"]["known_legacy_not_yet_mapped"], 1)

    def test_same_name_other_country_not_assumed_duplicate(self):
        report = review_candidates(catalog(), discovery([
            candidate(ID_C, "Metal Underground", "US"),
        ]))
        self.assertEqual(report["counts"]["unmapped_candidate"], 1)

    def test_record_collision_blocks_reconciliation(self):
        duplicated = catalog()
        duplicated["stations"][1]["legacy_aliases"].append(ID_A)
        with self.assertRaises(ValueError):
            index_catalog(duplicated)

    def test_tombstone_uuid_remains_preserved_and_recognized(self):
        c = catalog()
        c["tombstones"] = [{
            "go_station_id": "go-old", "legacy_aliases": [ID_D],
        }]
        report = review_candidates(c, discovery([candidate(ID_D)]))
        self.assertEqual(report["counts"]["already_mapped"], 1)
        self.assertEqual(report["candidates"][0]["existingGoStationId"], "go-old")

    def test_reject_untrusted_report_claiming_permission_to_publish(self):
        d = discovery([candidate(ID_C)])
        d["publicationAllowed"] = True
        with self.assertRaises(ValueError):
            review_candidates(catalog(), d)

    def test_unhealthy_stream_needs_qualification_and_remains_candidate(self):
        report = review_candidates(catalog(), discovery([
            candidate(ID_C, status="needs_stream_check"),
        ]))
        self.assertEqual(report["counts"]["unmapped_candidate"], 1)
        self.assertTrue(report["candidates"][0]["technicalVerificationNeeded"])
        self.assertEqual(report["candidates"][0]["candidateStatus"], "needs_stream_check")

    def test_duplicate_uuids_in_report_fail(self):
        with self.assertRaises(ValueError):
            review_candidates(catalog(), discovery([
                candidate(ID_C), candidate(ID_C),
            ]))


if __name__ == "__main__":
    unittest.main()
