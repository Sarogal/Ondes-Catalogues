"""Tests déterministes sans accès réseau pour le contrat du catalogue central."""
from __future__ import annotations

import copy
import unittest

from radio_catalog_guard import validate_catalog, safe_url


def station(goid="go-station-000001", alias="legacy-uuid-001", approved=False, verified=False):
    return {
        "go_station_id": goid,
        "display_name": "Radio fictive",
        "country_code": "FR",
        "genres": ["Heavy"],
        "homepage": "https://radio.example.org",
        "radio_browser_uuids": [{"uuid": alias, "state": "current"}],
        "legacy_aliases": [alias],
        "status": {"state": "active", "reason_code": None, "changed_at": "2026-11-15T09:00:00Z"},
        "streams": [
            {"stream_id": "stream-001", "url": "https://radio.example.org/live.mp3",
             "priority": 0, "protocol": "https", "codec": "mp3", "bitrate_kbps": 128,
             "state": "verified" if verified else "candidate"}
        ],
        "logo": None,
        "editorial": {
            "admission_state": "approved" if approved else "legacy_preserved",
            "reviewed_at": "2026-11-15T09:00:00Z",
            "evidence_refs": [],
        },
    }


def catalog(*stations, sequence=1):
    return {
        "schema_version": 1, "catalog_id": "grosses-ondes-radio",
        "release_sequence": sequence, "generated_at": "2026-11-15T09:00:00Z",
        "stations": list(stations), "tombstones": []
    }


class GuardContractTest(unittest.TestCase):
    def test_staging_preserves_unverified_legacy(self):
        self.assertEqual(validate_catalog(catalog(station()), mode="staging"), [])

    def test_publication_requires_editorial_and_verified_stream(self):
        errors = validate_catalog(catalog(station()), mode="publish")
        self.assertTrue(any("not approved" in e for e in errors))
        self.assertTrue(any("no verified stream" in e for e in errors))
        self.assertEqual(validate_catalog(catalog(station(approved=True, verified=True)), mode="publish"), [])

    def test_approved_stations_require_actual_review_date(self):
        s = station(approved=True, verified=True)
        s["editorial"]["reviewed_at"] = None
        self.assertTrue(any("missing editorial review timestamp" in e
                            for e in validate_catalog(catalog(s), mode="publish")))

    def test_collision_between_two_station_aliases_is_blocked(self):
        first = station()
        second = station(goid="go-station-000002")
        self.assertTrue(any("collision" in e for e in validate_catalog(catalog(first, second))))

    def test_variant_alias_is_stable_across_versions(self):
        old = station()
        old["legacy_aliases"].append("variant-uuid-777")
        previous = catalog(old)
        new = station(approved=True, verified=True)
        proposed = catalog(new, sequence=2)
        self.assertTrue(any("historical alias lost" in e for e in validate_catalog(proposed, mode="publish", previous=previous)))

    def test_station_retirement_must_keep_go_id(self):
        previous = catalog(station())
        proposed = catalog(station("go-station-000002", "legacy-uuid-002"), sequence=2)
        self.assertTrue(any("previously known go_station_id lost" in e for e in validate_catalog(proposed, previous=previous)))

    def test_quarantined_preserves_alias_and_can_lack_audio(self):
        s = station()
        s["status"]["state"] = "quarantined"
        s["streams"] = []
        self.assertEqual(validate_catalog(catalog(s), mode="staging"), [])

    def test_reject_url_credential_local_ip_and_file(self):
        for value in ("http://127.0.0.1/radio", "https://192.168.1.1/live",
                      "http://localhost/stream", "file:///etc/passwd",
                      "https://user:pass@radio.example.org/stream",
                      "https://[::1]/audio", "http://metal.local/stream"):
            with self.subTest(value=value):
                self.assertFalse(safe_url(value))
        self.assertTrue(safe_url("http://radio.example.org/stream"))
        self.assertTrue(safe_url("https://radio.example.org/stream"))

    def test_invalid_stream_protocol_and_duplicate_priority(self):
        s = station()
        additional = copy.deepcopy(s["streams"][0])
        additional["stream_id"] = "stream-002"
        additional["protocol"] = "http"
        s["streams"].append(additional)
        issues = validate_catalog(catalog(s))
        self.assertTrue(any("duplicate priority" in i for i in issues))
        self.assertTrue(any("protocol mismatch" in i for i in issues))

    def test_logo_hash_must_match_object_id(self):
        s = station()
        digest = "a" * 64
        s["logo"] = {
            "asset_id": "sha256:" + "b" * 64,
            "revision": 1, "url": "https://radio.example.org/logo.png",
            "sha256": digest, "byte_size": 5000, "width": 512,
            "height": 512, "mime_type": "image/png"
        }
        self.assertTrue(any("logo asset ID/digest inconsistency" in e
                            for e in validate_catalog(catalog(s))))

    def test_must_increment_release_sequence_in_publish_mode(self):
        prev = catalog(station(approved=True, verified=True), sequence=3)
        same = copy.deepcopy(prev)
        self.assertTrue(any("did not increase" in e
                            for e in validate_catalog(same, mode="publish", previous=prev)))


    def test_quarantine_requires_human_review_and_reason_in_publish(self):
        s = station(approved=False, verified=True)
        s["status"]["state"] = "quarantined"
        issues = validate_catalog(catalog(s), mode="publish")
        self.assertTrue(any("not editorially approved" in e for e in issues))
        self.assertTrue(any("missing status reason" in e for e in issues))
        s["editorial"]["admission_state"] = "approved"
        s["status"]["reason_code"] = "verified_manual_quarantine"
        self.assertEqual(validate_catalog(catalog(s), mode="publish"), [])

    def test_retired_station_requires_review_date(self):
        s = station(approved=True, verified=False)
        s["status"]["state"] = "retired"
        s["status"]["reason_code"] = "editorial_retirement"
        s["editorial"]["reviewed_at"] = None
        self.assertTrue(any("missing editorial review timestamp" in e
                            for e in validate_catalog(catalog(s), mode="publish")))

    def test_invalid_editorial_object_fails_closed_without_crash(self):
        s = station(approved=False, verified=True)
        s["editorial"] = None
        issues = validate_catalog(catalog(s), mode="publish")
        self.assertTrue(any("invalid editorial approval state" in e for e in issues))
        self.assertTrue(any("not approved" in e for e in issues))

    def test_bulk_shrink_blocked_even_when_each_retirement_approved(self):
        prior_stations = [
            station(f"go-station-{i:06d}", f"synthetic-alias-{i}", approved=True, verified=True)
            for i in range(1, 251)
        ]
        before = catalog(*prior_stations, sequence=3)
        next_stations = copy.deepcopy(prior_stations)
        for s in next_stations[:40]:
            s["status"]["state"] = "retired"
            s["status"]["reason_code"] = "editorial_retirement"
        after = catalog(*next_stations, sequence=4)
        issues = validate_catalog(after, mode="publish", previous=before)
        self.assertTrue(any("bulk station shrink" in e for e in issues))

    def test_small_reviewed_retirement_does_not_trigger_bulk_guard(self):
        prior_stations = [
            station(f"go-station-{i:06d}", f"synthetic-alias-{i}", approved=True, verified=True)
            for i in range(1, 211)
        ]
        before = catalog(*prior_stations, sequence=1)
        updated = copy.deepcopy(prior_stations)
        for s in updated[:10]:
            s["status"]["state"] = "retired"
            s["status"]["reason_code"] = "editorial_retirement"
        after = catalog(*updated, sequence=2)
        self.assertEqual(validate_catalog(after, mode="publish", previous=before), [])


    def test_later_publication_requires_previous_catalog(self):
        s = station(approved=True, verified=True)
        proposed = catalog(s, sequence=2)
        self.assertTrue(any("requires the previous catalog" in e
                            for e in validate_catalog(proposed, mode="publish")))
        self.assertEqual(validate_catalog(proposed, mode="publish",
                                          previous=catalog(copy.deepcopy(s), sequence=1)), [])



if __name__ == "__main__":
    unittest.main()
