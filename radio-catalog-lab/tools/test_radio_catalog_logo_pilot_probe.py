"""Synthetic, offline tests for the opt-in, zero-publication HTTPS logo pilot."""
from __future__ import annotations

import hashlib
import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from radio_catalog_logo_pilot_probe import (
    MAX_LOGO_BYTES,
    checked_https_url,
    fetch_strict_https,
    plan_pilot,
    run_pilot,
)

URL_A = "https://radio.example.org/assets/a.png"
URL_B = "https://radio.example.org/assets/b.png"


def sample():
    stage = {
        "stations": [
            {
                "go_station_id": "go-station-000001",
                "status": {"state": "active"},
                "legacy_aliases": ["historic-a"],
            },
            {
                "go_station_id": "go-station-000002",
                "status": {"state": "active"},
                "legacy_aliases": ["historic-b"],
            },
        ],
    }
    reuse = {
        "station_logos": [
            {
                "go_station_id": "go-station-000001",
                "legacy_station_ids": ["historic-a"],
                "logo_source_urls": [URL_A],
            },
            {
                "go_station_id": "go-station-000002",
                "legacy_station_ids": ["historic-b"],
                "logo_source_urls": [URL_B],
            },
        ],
    }
    pilot = {
        "schema_version": 1,
        "entries": [
            {"source_url": URL_A, "allowed_host": "radio.example.org",
             "go_station_ids": ["go-station-000001"]},
            {"source_url": URL_B, "allowed_host": "radio.example.org",
             "go_station_ids": ["go-station-000002"]},
        ],
    }
    return pilot, stage, reuse


class PilotGuardTests(unittest.TestCase):
    def test_no_io_during_plan_and_deterministic_selection(self):
        pilot, stage, reuse = sample()
        self.assertEqual(len(plan_pilot(pilot, stage, reuse)), 2)
        self.assertEqual(plan_pilot(pilot, stage, reuse)[0]["source_url"], URL_A)
        self.assertTrue(all(
            e["source_status"] == "historical_url_only_not_editorially_approved"
            for e in plan_pilot(pilot, stage, reuse)
        ))

    def test_http_ip_local_auth_fragment_and_cross_domain_all_blocked(self):
        for url, host in [
            ("http://radio.example.org/a.png", "radio.example.org"),
            ("https://127.0.0.1/a.png", "127.0.0.1"),
            ("https://localhost/a.png", "localhost"),
            ("https://radio.local/a.png", "radio.local"),
            ("https://u:p@radio.example.org/a.png", "radio.example.org"),
            ("https://radio.example.org:8080/a.png", "radio.example.org"),
            ("https://radio.example.org/a.png#secret", "radio.example.org"),
            ("https://radcap.ru/a.png", "radcap.ru"),
            ("https://radio.example.org/a.png", "other.example.org"),
            ("https://radio.example.org/a.png\n", "radio.example.org"),
        ]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                checked_https_url(url, host)

    def test_cross_station_source_must_exist_in_its_own_historical_map(self):
        pilot, stage, reuse = sample()
        pilot["entries"][0]["source_url"] = URL_B
        with self.assertRaises(ValueError):
            plan_pilot(pilot, stage, reuse)

    def test_unknown_or_duplicated_go_id_fail_closed(self):
        pilot, stage, reuse = sample()
        pilot["entries"][0]["go_station_ids"] = ["go-station-999999"]
        with self.assertRaises(ValueError):
            plan_pilot(pilot, stage, reuse)
        pilot, stage, reuse = sample()
        pilot["entries"][0]["go_station_ids"].append("go-station-000001")
        with self.assertRaises(ValueError):
            plan_pilot(pilot, stage, reuse)

    def test_station_cannot_have_two_pilot_source_urls(self):
        pilot, stage, reuse = sample()
        reuse["station_logos"][0]["logo_source_urls"].append(URL_B)
        pilot["entries"][1]["go_station_ids"] = ["go-station-000001"]
        with self.assertRaisesRegex(ValueError, "more than one"):
            plan_pilot(pilot, stage, reuse)

    def test_quarantined_station_is_not_automatically_eligible(self):
        pilot, stage, reuse = sample()
        stage["stations"][0]["status"]["state"] = "quarantined"
        with self.assertRaises(ValueError):
            plan_pilot(pilot, stage, reuse)

    def test_foreign_alias_and_incomplete_legacy_map_refused(self):
        pilot, stage, reuse = sample()
        reuse["station_logos"][0]["legacy_station_ids"] = ["historic-b"]
        with self.assertRaises(ValueError):
            plan_pilot(pilot, stage, reuse)
        pilot, stage, reuse = sample()
        reuse["station_logos"].pop()
        with self.assertRaisesRegex(ValueError, "IDs differ"):
            plan_pilot(pilot, stage, reuse)

    def test_max_eight_explicit_sources(self):
        pilot, stage, reuse = sample()
        pilot["entries"] = pilot["entries"] * 5
        with self.assertRaises(ValueError):
            plan_pilot(pilot, stage, reuse)

    def test_fake_downloads_write_one_verified_object_when_bytes_identical(self):
        pilot, stage, reuse = sample()
        planned = plan_pilot(pilot, stage, reuse)
        evidence = b"not-a-real-image-synthetic-test-only"
        expected_sha = hashlib.sha256(evidence).hexdigest()
        hits = []
        def fetch(url, host):
            hits.append((url, host))
            return evidence, "image/png"
        def decode(data):
            self.assertEqual(data, evidence)
            return "image/png", 512, 512
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "pilot-new"
            report = run_pilot(planned, destination, fetch=fetch, decode=decode)
            self.assertEqual(len(hits), 2)
            self.assertEqual(report["unique_fetched_urls"], 2)
            self.assertEqual(report["unique_sha256_objects"], 1)
            self.assertEqual(report["approved_logo_count"], 0)
            self.assertFalse(report["catalog_written"])
            self.assertFalse(report["play_or_informaniak_modified"])
            self.assertEqual(
                (destination / "evidence" / (expected_sha + ".img")).read_bytes(),
                evidence,
            )
            self.assertEqual(
                json.loads((destination / "pilot-evidence.json").read_text())["status"],
                "PILOT_HTTPS_BYTES_VERIFIED_BUT_NOT_APPROVED",
            )
            with self.assertRaisesRegex(ValueError, "exists"):
                run_pilot(planned, destination, fetch=fetch, decode=decode)

    def test_mime_mismatch_refused_before_writing_evidence_report(self):
        pilot, stage, reuse = sample()
        planned = plan_pilot(pilot, stage, reuse)
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "candidate"
            with self.assertRaisesRegex(ValueError, "MIME"):
                run_pilot(planned, destination,
                          fetch=lambda u, h: (b"test-image", "image/jpeg"),
                          decode=lambda d: ("image/png", 64, 64))
            self.assertFalse((destination / "pilot-evidence.json").exists())

    def test_oversized_payload_refused_even_with_decoder_injected(self):
        pilot, stage, reuse = sample()
        planned = plan_pilot(pilot, stage, reuse)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "byte count"):
                run_pilot(planned, Path(tmp) / "new",
                          fetch=lambda u, h: (b"x" * (MAX_LOGO_BYTES + 1), "image/png"),
                          decode=lambda d: ("image/png", 64, 64))

    def test_dns_rebinding_to_private_ip_is_rejected_before_tls(self):
        with patch("radio_catalog_logo_pilot_probe.socket.getaddrinfo",
                   return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "",
                                  ("10.0.0.1", 443))]):
            with self.assertRaisesRegex(ValueError, "Private/reserved"):
                fetch_strict_https(URL_A, "radio.example.org")

    def test_empty_source_selection_not_allowed(self):
        pilot, stage, reuse = sample()
        pilot["entries"] = []
        with self.assertRaises(ValueError):
            plan_pilot(pilot, stage, reuse)


if __name__ == "__main__":
    unittest.main()
