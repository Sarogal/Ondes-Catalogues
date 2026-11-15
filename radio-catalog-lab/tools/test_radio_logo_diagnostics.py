#!/usr/bin/env python3
"""Tests sans réseau pour les outils d'audit radio. Lancer : python -m unittest discover -s tools -p 'test_radio_logo_*.py'"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from radio_logo_cache_preflight import scan, stable_cache_name, compare as compare_cache
from radio_logo_trace_compare import summarize, compare as compare_trace


class RadioLogoAuditToolsTest(unittest.TestCase):
    def setUp(self):
        self.url = "https://radio.example.org/assets/logo.png"
        self.manifest = {
            "version": 4,
            "entries": [
                {"id": "uuid-1", "url": self.url, "revision": 1, "sizeBytes": 100,
                 "width": 400, "height": 400},
                {"id": "uuid-2", "url": self.url, "revision": 1, "sizeBytes": 100,
                 "width": 400, "height": 400}
            ]
        }
        self.catalog = {
            "stations": [
                {"id": "uuid-1", "streamVariants": [{"stationId": "uuid-2"}]}
            ]
        }

    def test_manifest_distinguishes_entries_and_distinct_urls(self):
        report = scan(self.manifest, self.catalog)
        self.assertEqual(report["applicable_logo_entries"], 2)
        self.assertEqual(report["applicable_unique_image_urls"], 1)
        self.assertEqual(report["manifest_shared_url_groups"], 1)
        self.assertEqual(report["device_inspection"], "unavailable")

    def test_fnv_stable(self):
        self.assertEqual(stable_cache_name(""), "cbf29ce484222325.img")
        self.assertEqual(stable_cache_name("a"), "af63dc4c8601ec8c.img")

    def test_cache_missing_then_installed_with_matching_signatures(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            missing = scan(self.manifest, self.catalog, {}, root)
            self.assertEqual(len(missing["pending"]), 2)
            self.assertEqual(missing["pending_unique_urls"], 1)
            self.assertEqual(missing["reason_counts"]["file_missing_or_empty"], 2)
            self.assertEqual(missing["reason_counts"]["signature_missing"], 2)

            (root / stable_cache_name(self.url)).write_bytes(b"nonempty-logo")
            installed = {"uuid-1": f"1|{self.url}", "uuid-2": f"1|{self.url}"}
            good = scan(self.manifest, self.catalog, installed, root)
            self.assertEqual(len(good["pending"]), 0)
            self.assertEqual(compare_cache(missing, good)["second_boot_zero_pending"], True)

            stale = scan(self.manifest, self.catalog, {"uuid-1": "1|https://old.example/logo.png"}, root)
            self.assertEqual(len(stale["pending"]), 2)
            self.assertEqual(stale["reason_counts"]["signature_mismatch"], 1)
            self.assertEqual(stale["reason_counts"]["signature_missing"], 1)

    def test_trace_distinguishes_stored_from_http_rejection(self):
        first = summarize([
            {"type": "boot_start"},
            {"type": "manifest_selected", "manifest_version": 4},
            {"type": "pending_entry", "station_id": "uuid-1", "file_present": False, "signature_state": "missing"},
            {"type": "plan_summary", "pending_station_entries": 1, "pending_unique_urls": 1},
            {"type": "http_image", "url_key": "a", "outcome": "attempt"},
            {"type": "http_image", "url_key": "a", "outcome": "http_error", "http_status": 404, "received_bytes": 0},
            {"type": "boot_ready"},
        ])
        second = summarize([
            {"type": "boot_start"},
            {"type": "manifest_selected", "manifest_version": 4},
            {"type": "plan_summary", "pending_station_entries": 0, "pending_unique_urls": 0},
            {"type": "boot_ready"},
        ])
        self.assertEqual(first["rejected_or_failed_requests"], 1)
        self.assertEqual(first["http_status_codes"], {"404": 1})
        self.assertTrue(compare_trace(first, second)["acceptance_met"])

    def test_incomplete_trace_rejected(self):
        with self.assertRaises(ValueError):
            summarize([{"type": "boot_start"}])


if __name__ == "__main__":
    unittest.main()
