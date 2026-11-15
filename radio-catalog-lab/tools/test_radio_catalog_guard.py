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


if __name__ == "__main__":
    unittest.main()
