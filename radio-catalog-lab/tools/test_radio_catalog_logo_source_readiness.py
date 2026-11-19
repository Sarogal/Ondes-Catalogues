"""Offline and deterministic checks for real-logo candidate source inventory."""
from __future__ import annotations

import copy
import unittest

from radio_catalog_logo_source_readiness import inspect_source_readiness


def fixture():
    staging = {
        "schema_version": 1, "catalog_id": "grosses-ondes-radio",
        "release_sequence": 1,
        "stations": [
            {
                "go_station_id": "go-station-000001",
                "display_name": "Synthetic Alpha",
                "status": {"state": "active"},
                "legacy_aliases": ["uuid-1"],
                "streams": [{"state": "candidate"}],
                "logo": None,
                "editorial": {"admission_state": "legacy_preserved"},
            },
            {
                "go_station_id": "go-station-000002",
                "display_name": "Synthetic Beta",
                "status": {"state": "active"},
                "legacy_aliases": ["uuid-2"],
                "streams": [{"state": "candidate"}],
                "logo": None,
                "editorial": {"admission_state": "legacy_preserved"},
            },
            {
                "go_station_id": "go-station-000003",
                "display_name": "Synthetic Archived",
                "status": {"state": "quarantined"},
                "legacy_aliases": ["uuid-3"],
                "streams": [],
                "logo": None,
                "editorial": {"admission_state": "legacy_preserved"},
            },
        ],
    }
    reuse = {
        "schema_version": 1,
        "station_logos": [
            {
                "go_station_id": "go-station-000001",
                "legacy_station_ids": ["uuid-1"],
                "logo_source_urls": [
                    "https://cdn.example.org/verified-by-nobody.png",
                    "http://source.example.org/legacy.png",
                ],
                "manifest_revisions": [{"revision": 2}],
            },
            {
                "go_station_id": "go-station-000002",
                "legacy_station_ids": ["uuid-2"],
                "logo_source_urls": [
                    "https://images.example.org/favicon.ico",
                ],
                "manifest_revisions": [],
            },
            {
                "go_station_id": "go-station-000003",
                "legacy_station_ids": ["uuid-3"],
                "logo_source_urls": [
                    "https://cdn.example.org/archive.png",
                ],
                "manifest_revisions": [],
            },
        ],
    }
    coverage = {
        "source_stage_file": "staging/radio-catalog/v1/bootstrap-stations-20261115.json",
        "missing_admissible_uuids": ["uuid-unresolved"],
        "missing_admissible_uuid_count": 1,
        "ready_to_publish": False,
        "coverage_gate_passed": False,
    }
    return staging, reuse, coverage


class SourceInventoryTests(unittest.TestCase):
    def test_deterministic_inventory_is_never_a_release_approval(self):
        a, b, c = fixture()
        result = inspect_source_readiness(a, b, c)
        self.assertEqual(result["status"], "READ_ONLY_LOGO_SOURCES_NOT_APPROVED")
        self.assertFalse(result["ready_to_publish"])
        self.assertFalse(result["publish_action_performed"])
        self.assertEqual(result["auto_downloaded_count"], 0)
        self.assertEqual(result["staged_station_count"], 3)
        self.assertEqual(result["active_station_count"], 2)
        self.assertEqual(result["direct_https_image_candidate_station_count"], 1)
        self.assertEqual(result["verified_stream_count"], 0)
        self.assertEqual(result["unresolved_admissible_uuid_count"], 1)
        self.assertEqual(result["candidate_classes"], {
            "https_image_candidate": 1,
            "https_manual_review": 1,
            "inactive_excluded": 1,
        })
        one = result["stations"][0]
        self.assertEqual(one["candidate_https_image_urls"],
                         ["https://cdn.example.org/verified-by-nobody.png"])
        self.assertTrue(one["requires_independent_artwork_identity_and_byte_sha_review"])
        self.assertFalse(one["automatic_admission"])

    def test_no_url_and_http_only_remain_unapproved(self):
        a, b, c = fixture()
        b["station_logos"][0]["logo_source_urls"] = []
        b["station_logos"][1]["logo_source_urls"] = ["http://example.org/logo.jpg"]
        r = inspect_source_readiness(a, b, c)
        self.assertEqual(r["candidate_classes"]["no_source"], 1)
        self.assertEqual(r["candidate_classes"]["unsafe_or_http_only"], 1)
        self.assertEqual(r["direct_https_image_candidate_station_count"], 0)

    def test_radcap_loopback_credentials_and_numeric_host_never_auto_candidate(self):
        a, b, c = fixture()
        b["station_logos"][0]["logo_source_urls"] = [
            "https://radcap.ru/logo.jpg",
            "https://127.0.0.1/a.png",
            "https://localhost/a.png",
            "https://a:b@cdn.example.org/x.png",
            "https://10.0.0.2/a.png",
            "http://cdn.example.org/x.png",
        ]
        self.assertEqual(
            inspect_source_readiness(a, b, c)["stations"][0]["source_category"],
            "unsafe_or_http_only",
        )

    def test_duplicate_station_and_map_rows_refused(self):
        a, b, c = fixture()
        a["stations"].append(copy.deepcopy(a["stations"][0]))
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            inspect_source_readiness(a, b, c)
        a, b, c = fixture()
        b["station_logos"].append(copy.deepcopy(b["station_logos"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            inspect_source_readiness(a, b, c)

    def test_missing_or_extra_reuse_identity_fails_closed(self):
        a, b, c = fixture()
        b["station_logos"].pop()
        with self.assertRaisesRegex(ValueError, "exactly"):
            inspect_source_readiness(a, b, c)

    def test_wrong_legacy_owner_cannot_acquire_logo_url(self):
        a, b, c = fixture()
        b["station_logos"][0]["legacy_station_ids"] = ["uuid-2"]
        with self.assertRaisesRegex(ValueError, "foreign station alias"):
            inspect_source_readiness(a, b, c)

    def test_bad_coverage_including_unsafe_green_state_is_refused(self):
        a, b, c = fixture()
        c["coverage_gate_passed"] = True
        with self.assertRaisesRegex(ValueError, "Coverage preflight"):
            inspect_source_readiness(a, b, c)
        a, b, c = fixture()
        c["missing_admissible_uuid_count"] = 0
        with self.assertRaisesRegex(ValueError, "Coverage preflight"):
            inspect_source_readiness(a, b, c)

    def test_tampered_report_source_fails_closed(self):
        a, b, c = fixture()
        c["source_stage_file"] = "other-unchecked.json"
        with self.assertRaisesRegex(ValueError, "unexpected staging"):
            inspect_source_readiness(a, b, c)

    def test_staged_sha_metadata_does_not_count_as_verified_bytes(self):
        a, b, c = fixture()
        a["stations"][0]["logo"] = {"sha256": "a" * 64}
        r = inspect_source_readiness(a, b, c)
        self.assertEqual(r["staged_logo_metadata_not_cryptographically_rechecked"], 1)
        self.assertFalse(r["ready_to_publish"])

    def test_bad_sha_and_malformed_stream_fail_closed(self):
        a, b, c = fixture()
        a["stations"][0]["logo"] = {"sha256": "not-a-digest"}
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            inspect_source_readiness(a, b, c)
        a, b, c = fixture()
        a["stations"][0]["streams"] = [None]
        with self.assertRaisesRegex(ValueError, "stream"):
            inspect_source_readiness(a, b, c)


if __name__ == "__main__":
    unittest.main()
