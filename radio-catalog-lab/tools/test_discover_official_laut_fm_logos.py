#!/usr/bin/env python3
"""Offline assertions for exact-source laut.fm discovery; no approvals."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
from audit_open_radio_artwork_inventory import InventoryError
from discover_official_laut_fm_logos import (
    collect, extract_slug, validated_station_metadata,
)

INV = (TOOLS.parents[1] / "grossesondes/radio-test-apk/"
       "artwork/legacy_v64_inventory.json")


def official(slug):
    return {
        "name":slug, "display_name":"Example Punk Radio",
        "page_url":"https://laut.fm/"+slug,
        "stream_url":"https://"+slug+".stream.laut.fm/"+slug,
        "images":{"station":"https://assets.laut.fm/"+"a"*32},
    }


class OpenLautFmArtworkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inventory=json.loads(INV.read_text(encoding="utf-8"))

    def test_homepage_slug_extraction_refuses_ambiguous_paths(self):
        self.assertEqual(extract_slug("http://laut.fm/beatdownx"),"beatdownx")
        self.assertEqual(extract_slug("https://www.laut.fm/up_the_irons"),"up_the_irons")
        self.assertEqual(extract_slug("https://stream.laut.fm/ritus"),"ritus")
        self.assertIsNone(extract_slug("https://laut.fm/"))
        self.assertIsNone(extract_slug("https://laut.fm/example/song"))
        self.assertIsNone(extract_slug("https://www.other.org/test"))
        self.assertIsNone(extract_slug("https://laut.fm/ritus?station=other"))
        self.assertIsNone(extract_slug("https://user:pass@laut.fm/ritus"))

    def test_rejects_mismatched_slug_and_external_artwork(self):
        row=official("beatdownx")
        self.assertEqual(validated_station_metadata(row,"beatdownx")[
            "official_image"],"https://assets.laut.fm/"+"a"*32)
        row["name"]="another_station"
        with self.assertRaises(InventoryError):
            validated_station_metadata(row,"beatdownx")
        row=official("beatdownx")
        row["images"]["station"]="https://image-aggregator.example.org/logo.png"
        with self.assertRaises(InventoryError):
            validated_station_metadata(row,"beatdownx")
        row=official("beatdownx")
        row["stream_url"]="https://fake-radio.example.org/other-stream"
        with self.assertRaises(InventoryError):
            validated_station_metadata(row,"beatdownx")

    def test_actual_inventory_is_open_and_nonpublishing(self):
        result=collect(self.inventory, network=False)
        self.assertGreaterEqual(result["candidate_stations"],15)
        self.assertFalse(result["publication_allowed"])
        self.assertFalse(result["signed_catalog_created"])
        self.assertTrue(all(
            not r["station_logo_approved"] and not r["verified_image_bytes"]
            for r in result["records"]
        ))

    def test_new_unseen_station_slug_is_not_blocked_by_list(self):
        info=official("future_punk_rebel_2028")
        result=validated_station_metadata(info,"future_punk_rebel_2028")
        self.assertTrue(result["identity_by_exact_station_slug"])

    def test_even_successful_image_sha_remains_candidate(self):
        station=next(r for r in self.inventory["stations"]
                     if extract_slug(r["homepage"]) is not None)
        data=dict(self.inventory)
        data["stations"]=[station]
        slug=extract_slug(station["homepage"])
        with patch("discover_official_laut_fm_logos.fetch_official",
                   return_value=validated_station_metadata(official(slug),slug)
                   ) as apifetch:
            with patch("discover_official_laut_fm_logos.probe_image",
                       return_value={
                         "verified_bytes":True,
                         "sha256":"f"*64, "byte_size":20000,
                         "width":512,"height":512,"mime_type":"image/jpeg",
                       }) as img:
                result=collect(data, network=True)
        self.assertEqual(result["api_identity_matches"],1)
        self.assertEqual(result["decoded_official_images"],1)
        self.assertEqual(apifetch.call_count,1)
        self.assertEqual(img.call_count,1)
        self.assertFalse(result["records"][0]["station_logo_approved"])
        self.assertFalse(result["publication_allowed"])


if __name__ == "__main__":
    unittest.main()
