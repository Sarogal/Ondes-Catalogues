#!/usr/bin/env python3
"""Historical SHA artwork reuse without signing, replacing, or deleting."""
from __future__ import annotations
import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "radio-catalog-lab/tools"))
from attach_full_staging_artwork_20261122 import attach  # noqa: E402


class HistoricalArtworkReuseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads((ROOT / "radio-catalog-lab/full-staging/candidate-20261122.json"
                                  ).read_text(encoding="utf-8"))
        cls.preview = json.loads((ROOT / "grossesondes/radio-test-apk/artwork/previews/"
                                  "unsigned-v2-12-logos-20261121.json"
                                  ).read_text(encoding="utf-8"))

    def test_12_existing_sha_evidences_match_exact_station_uuid(self):
        original = copy.deepcopy(self.catalog)
        new, report = attach(self.catalog, self.preview)
        self.assertEqual(self.catalog, original)
        self.assertEqual(report["linked_logo_count"], 12)
        self.assertEqual(report["total_sha_descriptors_after_preview"], 13)
        self.assertTrue(report["radio_count_unchanged"])
        self.assertFalse(report["ready_to_sign"])
        self.assertFalse(report["can_replace_test_current_json"])
        self.assertEqual(len(new["stations"]), 320)
        aliases = {x: st for st in new["stations"] for x in st["legacy_aliases"]}
        for a in self.preview["assets"]:
            station = aliases[a["legacy_media_id"]]
            self.assertEqual(station["logo"]["sha256"], a["logo"]["sha256"])
            self.assertEqual(station["logo"]["byte_size"], a["logo"]["byte_size"])

    def test_refuse_unknown_historical_identity_or_name_mismatch(self):
        forged = copy.deepcopy(self.preview)
        forged["assets"][0]["station_name"] = "Another radio"
        with self.assertRaises(ValueError):
            attach(self.catalog, forged)
        forged["assets"][0]["legacy_media_id"] = "00000000-0000-0000-0000-000000000000"
        with self.assertRaises(ValueError):
            attach(self.catalog, forged)

    def test_refuse_fabricated_sha_or_url_and_unreviewed_logo(self):
        for field, value in (("sha256", "0"*64), ("url", "http://example.org/logo.png")):
            forged = copy.deepcopy(self.preview)
            forged["assets"][0]["logo"][field] = value
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    attach(self.catalog, forged)
        forged = copy.deepcopy(self.preview)
        forged["assets"][0]["source"]["visual_identity_evidence"] = ""
        with self.assertRaises(ValueError):
            attach(self.catalog, forged)

    def test_existing_signed_test_v4_logo_cannot_be_overwritten(self):
        forged = copy.deepcopy(self.preview)
        target = next(s for s in self.catalog["stations"] if s["logo"] is not None)
        forged["assets"][0]["legacy_media_id"] = target["legacy_aliases"][0]
        forged["assets"][0]["station_name"] = target["display_name"]
        with self.assertRaises(ValueError):
            attach(self.catalog, forged)


if __name__ == "__main__":
    unittest.main(verbosity=2)
