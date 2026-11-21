#!/usr/bin/env python3
"""Offline tests for exact-UUID open-ended radio logo discovery."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
from audit_open_radio_artwork_inventory import InventoryError
from discover_radio_browser_logo_candidates import (
    collect, fetch_radio_browser_batch, safe_uuid_records,
)

INVENTORY = TOOLS.parents[1] / "grossesondes/radio-test-apk/artwork/legacy_v64_inventory.json"


class RadioBrowserLogoEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inventory = json.loads(INVENTORY.read_text(encoding="utf-8"))

    def test_open_manifest_all_310_uuid_rows_can_be_queried(self):
        report = collect(self.inventory, network=False)
        self.assertEqual(report["requested_uuid_count"], 310)
        self.assertEqual(report["resolved_uuid_count"], 0)
        self.assertFalse(report["publication_allowed"])
        self.assertEqual(len(report["records"]), 310)
        self.assertTrue(all(
            r["candidate_is_verified_logo"] is False
            for r in report["records"]
        ))

    def test_unknown_new_uuid_is_accepted_as_candidate(self):
        data = deepcopy(self.inventory)
        novel = deepcopy(data["stations"][0])
        novel["legacy_media_id"] = "ffef0000-0000-4000-8000-ffff99998888"
        novel["display_name"] = "Future Metal Punk Radio"
        data["stations"].append(novel)
        report = collect(data, network=False)
        self.assertEqual(report["requested_uuid_count"], 311)

    def test_only_exact_uuid_matches_are_accepted(self):
        a = "00000000-0000-4000-8000-000000000001"
        b = "00000000-0000-4000-8000-000000000002"
        result = safe_uuid_records([
            {"stationuuid": a, "name":"Station A", "favicon":"https://example.org/a.png"},
        ], {a,b})
        self.assertEqual(set(result), {a})
        with self.assertRaises(InventoryError):
            safe_uuid_records([
                {"stationuuid": b, "name":"Station B", "favicon":""},
                {"stationuuid": b, "name":"Duplicate", "favicon":""},
            ], {a,b})
        with self.assertRaises(InventoryError):
            safe_uuid_records([
                {"stationuuid":"00000000-0000-4000-8000-000000000099",
                 "name":"Untrusted", "favicon":""},
            ], {a,b})

    def test_http_logo_never_treated_as_https_or_approved(self):
        seed = deepcopy(self.inventory)
        seed["stations"] = seed["stations"][:1]
        original_id = seed["stations"][0]["legacy_media_id"]
        with patch("discover_radio_browser_logo_candidates.fetch_radio_browser_batch") as api:
            api.return_value = {
                original_id: {
                    "name":"Same radio",
                    "favicon":"http://radio.example.org/favicon.ico",
                    "lastcheckok":1,
                }
            }
            report = collect(seed, network=True)
        row = report["records"][0]
        self.assertEqual(row["source_state"], "http_candidate_not_fetched")
        self.assertIsNone(row["https_candidate_url"])
        self.assertFalse(row["candidate_is_verified_logo"])
        self.assertFalse(row["publication_allowed"])

    def test_verified_https_url_still_only_candidate(self):
        seed = deepcopy(self.inventory)
        seed["stations"] = seed["stations"][:1]
        original_id = seed["stations"][0]["legacy_media_id"]
        with patch("discover_radio_browser_logo_candidates.fetch_radio_browser_batch") as api:
            api.return_value = {
                original_id: {
                    "name":"Same radio",
                    "favicon":"https://cdn.example.org/station.png",
                    "lastcheckok":1,
                }
            }
            report = collect(seed, network=True)
        self.assertEqual(report["https_logo_candidates"], 1)
        self.assertTrue(report["records"][0]["identity_match_by_uuid_only"])
        self.assertFalse(report["records"][0]["candidate_is_verified_logo"])

    def test_invalid_batch_size_or_uuid_rejected_before_network(self):
        with self.assertRaises(InventoryError):
            fetch_radio_browser_batch([])
        with self.assertRaises(InventoryError):
            fetch_radio_browser_batch(["not-uuid"])
        with self.assertRaises(InventoryError):
            fetch_radio_browser_batch(["00000000-0000-4000-8000-000000000001"] * 41)


if __name__ == "__main__":
    unittest.main()
