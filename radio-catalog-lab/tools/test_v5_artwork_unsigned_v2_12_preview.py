#!/usr/bin/env python3
"""Unsigned TEST v2 with 12 logos: exact one UUID added after fresh SHA check.

This never produces a signed pointer, promotes a visual identity or alters
existing radio/stream/favorite records.
"""
import json
from pathlib import Path
from copy import deepcopy
import unittest

from artwork_release_packager import (
    ArtworkBundleError, validate_body, wire,
)

ROOT=Path(__file__).resolve().parents[2]
ART=ROOT/"grossesondes/radio-test-apk/artwork"
BASE=ART/"releases/b85a4ddc27783e2a242747924f28a5438f1fb8d5adb6500c28126a90e588235d.json"
OLD_PREVIEW=ART/"previews/unsigned-v2-11-logos-20261121.json"
NEW_PREVIEW=ART/"previews/unsigned-v2-12-logos-20261121.json"
REVIEW=ART/"v5_first_source_visual_review_20261121.json"
RITUS_UUID="681c6fee-8d61-437b-84a4-f96b8fd3422c"


class TwelveLogoPreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.previous=validate_body(BASE.read_bytes())
        cls.eleven=validate_body(OLD_PREVIEW.read_bytes(),cls.previous)
        cls.twelve=validate_body(NEW_PREVIEW.read_bytes(),cls.previous)
        cls.review=json.loads(REVIEW.read_text(encoding="utf-8"))

    def test_only_ritus_added_and_original_eleven_unchanged(self):
        old={x["legacy_media_id"]:x for x in self.eleven["assets"]}
        new={x["legacy_media_id"]:x for x in self.twelve["assets"]}
        self.assertEqual(len(old),11)
        self.assertEqual(len(new),12)
        self.assertEqual(set(new)-set(old),{RITUS_UUID})
        for uid,descriptor in old.items():
            self.assertEqual(descriptor,new[uid])
        self.assertEqual(self.twelve["release_sequence"],2)
        self.assertEqual(self.eleven["release_sequence"],2)

    def test_ritus_exact_sha_size_url_provenance_matches_review(self):
        visual={x["legacy_media_id"]:x for x in self.review["records"]}
        target=visual[RITUS_UUID]
        record={x["legacy_media_id"]:x for x in self.twelve["assets"]}[RITUS_UUID]
        logo=record["logo"]
        self.assertEqual(record["station_name"],"Ritus")
        self.assertEqual(logo["url"],target["candidate_url"])
        self.assertEqual(logo["sha256"],target["candidate_sha256"])
        self.assertEqual(logo["asset_id"],"sha256:"+logo["sha256"])
        self.assertEqual(logo["byte_size"],600273)
        self.assertEqual(logo["mime_type"],"image/png")
        self.assertEqual((logo["width"],logo["height"]),(640,640))
        self.assertEqual(record["source"]["official_station_page"],target["source_official_page"])
        self.assertEqual(record["source"]["station_slug"],target["station_slug"])
        self.assertEqual(record["source"]["provider"],"laut.fm")
        self.assertFalse(record["replace_existing_logo"])
        self.assertFalse(target["can_sign_now"])
        self.assertFalse(target["publication_allowed"])

    def test_both_v2_previews_are_alternatives_not_rollback_chain(self):
        with self.assertRaises(ArtworkBundleError):
            validate_body(NEW_PREVIEW.read_bytes(),self.eleven)
        with self.assertRaises(ArtworkBundleError):
            validate_body(OLD_PREVIEW.read_bytes(),self.twelve)

    def test_queries_cannot_change_without_resigning_and_revalidating(self):
        for query in ("?t=_120x120","?t=_640x640&x=1","?x=1"):
            d=deepcopy(self.twelve)
            for asset in d["assets"]:
                if asset["legacy_media_id"]==RITUS_UUID:
                    asset["logo"]["url"]=asset["logo"]["url"].split("?")[0]+query
                    break
            with self.subTest(query=query), self.assertRaises(ArtworkBundleError):
                validate_body(wire(d),self.previous)

    def test_no_active_sidecar_and_radio_generation_four(self):
        self.assertFalse((ART/"current.json").exists())
        self.assertFalse((ART/"pending/test-current-v2.json").exists())
        self.assertEqual(self.twelve["source_radio_catalog_min_sequence"],4)
        self.assertFalse(self.twelve["production_publication_allowed"])
        self.assertEqual(
            json.loads((ART.parent/"current.json").read_text())["release_sequence"],4)


if __name__=="__main__":
    unittest.main()
