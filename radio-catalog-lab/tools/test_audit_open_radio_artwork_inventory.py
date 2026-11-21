#!/usr/bin/env python3
"""Offline safety checks for open Grosses Ondes historical logo inventory."""
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from PIL import Image

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
from audit_open_radio_artwork_inventory import (
    InventoryError, MetadataImages, audit, inspect_bytes, public_https,
    validate_inventory, upgraded_https_homepage,
)

INVENTORY = (
    TOOLS.parents[1] / "grossesondes" / "radio-test-apk" /
    "artwork" / "legacy_v64_inventory.json"
)


class OpenArtworkInventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = json.loads(INVENTORY.read_text(encoding="utf-8"))

    def test_full_legacy_inventory_is_grounded_and_has_no_approval(self):
        rows = validate_inventory(self.doc)
        self.assertEqual(len(rows), 310)
        self.assertEqual(sum(bool(r["source_logo_url"]) for r in rows), 168)
        self.assertEqual(sum(
            r["source_logo_url"].startswith("https://") for r in rows
        ), 130)
        self.assertEqual(sum(
            r["source_logo_url"].startswith("http://") for r in rows
        ), 38)
        self.assertEqual(sum(not r["source_logo_url"] for r in rows), 142)
        self.assertEqual(len({r["legacy_media_id"] for r in rows}), 310)
        self.assertFalse(self.doc["publication_allowed"])

    def test_unknown_new_radio_is_not_blocked_by_finite_allowlist(self):
        novel = deepcopy(self.doc)
        new = deepcopy(novel["stations"][0])
        new["legacy_media_id"] = "future-new-rock-radio-2027"
        new["display_name"] = "New Punk Radio Unseen By Auditors"
        new["source_logo_url"] = ""
        new["logo_state"] = "discovery_needed"
        novel["stations"].append(new)
        self.assertEqual(len(validate_inventory(novel)), 311)

    def test_rejects_duplicate_ids_and_approval_promotion(self):
        doc = deepcopy(self.doc)
        doc["stations"][1]["legacy_media_id"] = doc["stations"][0]["legacy_media_id"]
        with self.assertRaises(InventoryError):
            validate_inventory(doc)
        doc = deepcopy(self.doc)
        doc["stations"][1]["editorial_decision"] = "approved"
        with self.assertRaises(InventoryError):
            validate_inventory(doc)
        doc = deepcopy(self.doc)
        doc["publication_allowed"] = True
        with self.assertRaises(InventoryError):
            validate_inventory(doc)

    def test_shards_cover_all_stations_without_repetition(self):
        found = set()
        for index in range(8):
            result = audit(self.doc, shard_index=index, shard_count=8,
                           network=False)
            self.assertFalse(result["publication_allowed"])
            self.assertFalse(result["signed_catalog_created"])
            for row in result["records"]:
                self.assertNotIn(row["legacy_media_id"], found)
                found.add(row["legacy_media_id"])
                self.assertFalse(row["station_logo_approved"])
        self.assertEqual(len(found), 310)

    def test_never_fetch_original_plain_http_image(self):
        first = next(row for row in self.doc["stations"]
                     if row["source_logo_url"].startswith("http://"))
        doc = deepcopy(self.doc)
        doc["stations"] = [first]
        with patch("audit_open_radio_artwork_inventory.probe_image",
                   return_value={"verified_bytes": True}) as image:
            report = audit(doc, shard_index=0, shard_count=1, network=True)
        row = report["records"][0]
        self.assertTrue(row["historical_http_never_fetched"])
        self.assertTrue(row["probe"]["verified_bytes"])
        self.assertTrue(image.call_args.args[0].startswith("https://"))
        self.assertFalse(row["station_logo_approved"])

    def test_public_https_rejects_private_network_and_untrusted_scheme(self):
        bad = [
            "http://radio.example.org/logo.png", "https://127.0.0.1/a",
            "https://10.3.0.4/logo.jpg", "https://localhost/logo",
            "https://radio.internal/test", "https://radio.example.org:8443/a",
            "https://foo:bar@radio.example.org/logo.png",
            "https://radio.example.org/logo.png#secret", "file:///etc/passwd",
        ]
        for url in bad:
            with self.subTest(url=url):
                self.assertFalse(public_https(url))
        self.assertTrue(public_https("https://new-punk-station.example.org/logo.png"))

    def test_image_decoder_checks_sha_mime_and_quality(self):
        buf = BytesIO()
        Image.new("RGB", (128, 128), (12, 22, 33)).save(buf, format="PNG")
        image = inspect_bytes(buf.getvalue(), content_type="image/png")
        self.assertEqual(image["width"], 128)
        self.assertEqual(image["mime_type"], "image/png")
        self.assertEqual(len(image["sha256"]), 64)
        with self.assertRaises(InventoryError):
            inspect_bytes(buf.getvalue(), content_type="image/jpeg")
        with self.assertRaises(InventoryError):
            inspect_bytes(b"not an image"*50, content_type="image/png")
        tiny = BytesIO()
        Image.new("RGB", (16, 16), (2, 3, 4)).save(tiny, format="PNG")
        with self.assertRaises(InventoryError):
            inspect_bytes(tiny.getvalue(), content_type="image/png")

    def test_plaintext_homepage_is_never_fetched_even_during_upgrade(self):
        self.assertEqual(
            upgraded_https_homepage("http://laut.fm/beatdownx"),
            "https://laut.fm/beatdownx",
        )
        self.assertEqual(
            upgraded_https_homepage("https://www.example.org/stream"),
            "https://www.example.org/stream",
        )
        self.assertIsNone(upgraded_https_homepage("http://127.0.0.1/private"))
        self.assertIsNone(upgraded_https_homepage(
            "http://user:password@station.example.org/secret"))
        self.assertIsNone(upgraded_https_homepage(
            "http://localhost/example"))

    def test_official_site_icons_remain_unreviewed_candidates(self):
        parser = MetadataImages()
        parser.feed("""
            <link rel="apple-touch-icon" href="/apple-touch-icon.png">
            <link rel="icon" type="image/png" href="/radio.ico">
            <link rel="preload" href="/not-a-logo.jpg">
        """)
        self.assertEqual(len(parser.urls), 2)
        self.assertTrue(all(
            kind == "html:link-icon-unreviewed"
            for kind, _ in parser.urls
        ))

    def test_official_page_metadata_is_unapproved(self):
        parser = MetadataImages()
        parser.feed("""
        <meta property="og:image" content="/logos/channel.png">
        <meta name="twitter:image" content="https://cdn.example.org/logo.jpg">
        <script>not station artwork</script>
        """)
        self.assertEqual(len(parser.urls), 2)
        self.assertEqual(parser.urls[0], ("og:image", "/logos/channel.png"))


if __name__ == "__main__":
    unittest.main()
