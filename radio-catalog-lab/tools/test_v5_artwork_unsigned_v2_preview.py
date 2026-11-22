#!/usr/bin/env python3
"""Offline checks for unsigned TEST v2 preview — never a signed release."""
import copy
import hashlib
import json
from pathlib import Path
import unittest

from artwork_release_packager import (
    validate_body, wire, ArtworkBundleError,
)

ROOT=Path(__file__).resolve().parents[2]
ART=ROOT/"grossesondes"/"radio-test-apk"/"artwork"
OLD_SHA="b85a4ddc27783e2a242747924f28a5438f1fb8d5adb6500c28126a90e588235d"
OLD=ART/"releases"/(OLD_SHA+".json")
PREVIEW=ART/"previews"/"unsigned-v2-11-logos-20261121.json"
REVIEW=ART/"v5_first_source_visual_review_20261121.json"
RADIO=ROOT/"grossesondes"/"radio-test-apk"/"current.json"


class PreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.oldraw=OLD.read_bytes()
        cls.newraw=PREVIEW.read_bytes()
        cls.old=validate_body(cls.oldraw)
        cls.new=validate_body(cls.newraw,cls.old)
        cls.review=json.loads(REVIEW.read_text(encoding="utf-8"))

    def test_first_nine_immutable_and_two_added_exactly(self):
        self.assertEqual(hashlib.sha256(self.oldraw).hexdigest(),OLD_SHA)
        self.assertEqual(self.old["release_sequence"],1)
        self.assertEqual(self.new["release_sequence"],2)
        byold={r["legacy_media_id"]:r for r in self.old["assets"]}
        bynew={r["legacy_media_id"]:r for r in self.new["assets"]}
        self.assertEqual(len(byold),9)
        self.assertEqual(len(bynew),11)
        self.assertTrue(all(bynew[id_]==row for id_,row in byold.items()))
        new_ids=set(bynew)-set(byold)
        expected={
            r["legacy_media_id"] for r in self.review["records"]
            if r["editorial_decision"]=="VISUAL_TEST_ACCEPTED_SOURCE_REVIEWED"
        }
        self.assertEqual(new_ids,expected)
        self.assertEqual(len(new_ids),2)

    def test_evidence_sha_and_identity_are_pinned_to_manual_review(self):
        self.assertEqual(self.review["scope"],
                         "GO_V5_EXPLICIT_VISUAL_DECISIONS_TEST_ONLY_UNSIGNED")
        self.assertFalse(self.review["publication_allowed"])
        self.assertFalse(self.review["signed_catalog_created"])
        self.assertTrue(self.review["open_discovery_not_allowlist"])
        bynew={r["legacy_media_id"]:r for r in self.new["assets"]}
        for record in self.review["records"]:
            self.assertFalse(record["publication_allowed"])
            self.assertFalse(record["replace_existing_logo"])
            self.assertFalse(record["can_sign_now"])
            if record["editorial_decision"]!="VISUAL_TEST_ACCEPTED_SOURCE_REVIEWED":
                self.assertNotIn(record["legacy_media_id"],bynew)
                continue
            staged=bynew[record["legacy_media_id"]]
            self.assertEqual(staged["station_name"],record["station_name"])
            self.assertEqual(staged["logo"]["sha256"],
                             record["candidate_sha256"])
            self.assertEqual(staged["logo"]["url"],
                             record["candidate_url"])
            self.assertEqual(staged["logo"]["width"],
                             record["expected_width"])
            self.assertEqual(staged["logo"]["height"],
                             record["expected_height"])
            self.assertEqual(staged["source"]["official_station_page"],
                             record["source_official_page"])
            self.assertEqual(staged["source"]["provider"],record["provider"])
            self.assertEqual(staged["source"]["station_slug"],
                             record["station_slug"])
            self.assertFalse(staged["replace_existing_logo"])

    def test_existing_test_radio_pointer_and_artwork_inactive(self):
        self.assertEqual(self.new["scope"],"TEST_ONLY")
        self.assertFalse(self.new["production_publication_allowed"])
        self.assertEqual(self.new["source_radio_catalog_min_sequence"],4)
        self.assertEqual(json.loads(RADIO.read_text())["release_sequence"],4)
        self.assertFalse((ART/"current.json").exists())
        self.assertFalse((ART/"pending"/"test-current-v2.json").exists())
        self.assertEqual(
            {p.name for p in (ART/"previews").glob("*.json")},
            {"unsigned-v2-11-logos-20261121.json",
             "unsigned-v2-12-logos-20261121.json"})
        self.assertEqual(self.new["selection_mode"],
                         "manual_visual_review_of_open_discovery_candidates")

    def test_broken_sha_or_untrusted_protocol_rejected(self):
        obj=copy.deepcopy(self.new)
        obj["assets"][-1]["logo"]["sha256"]="g"*64
        with self.assertRaises(ArtworkBundleError):
            validate_body(wire(obj),self.old)

    def test_unsigned_preview_cannot_bypass_release_antiroallback(self):
        obj=copy.deepcopy(self.new)
        obj["release_sequence"]=1
        with self.assertRaises(ArtworkBundleError):
            validate_body(wire(obj),self.old)


if __name__=="__main__":
    unittest.main()
