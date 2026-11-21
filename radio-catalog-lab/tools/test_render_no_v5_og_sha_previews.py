#!/usr/bin/env python3
"""Offline visual-review tests: exact SHA, dedupe, no implicit approval."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PIL import Image

from render_no_v5_og_sha_previews import (
    select, render, OGVisualError,
)


def dataset():
    a="a"*64
    def candidate(id_,url,sha=a,valid=True,big=True):
        return {
            "legacy_media_id":id_,
            "station_name":"Radio "+id_[0],
            "candidate_url":url,
            "publication_allowed":False,
            "replace_existing_logo":False,
            "identity_visual_approved":False,
            "sha_and_decoder_verified":valid,
            "large_enough_to_review":big,
            "byte_evidence":{
                "verified_bytes":valid,"sha256":sha,
                "byte_size":10000,"width":600 if big else 144,
                "height":600,"mime_type":"image/png",
                "approved_station_logo":False,"publication_allowed":False,
            },
        }
    base="https://new-unknown-radio.example.org/social.png"
    return {
        "scope":"GO_NO_V5_HOMEPAGE_IMAGE_SHA_REVIEW_ONLY",
        "publication_allowed":False,"signed_catalog_created":False,
        "identity_visual_approved":False,
        "historical_scanned":3,"historical_missing_v5":3,
        "records":[
            candidate("11111111-1111-1111-1111-111111111111",base),
            candidate("11111111-1111-1111-1111-111111111111",
                      base+"?tracking=2"),
            candidate("22222222-2222-2222-2222-222222222222",
                      "https://another-unknown.example.net/hero.png",
                      big=False),
            candidate("33333333-3333-3333-3333-333333333333",
                      "https://third.example.org/network-cover.png",
                      valid=False),
        ],
    }


class OGVisualTests(unittest.TestCase):
    def test_same_uuid_and_sha_deduped_without_station_whitelist(self):
        rows=select(dataset())
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["station_name"],"Radio 1")
        self.assertEqual(rows[0]["legacy_media_id"],
                         "11111111-1111-1111-1111-111111111111")

    def test_render_creates_readable_preview_without_publishing(self):
        def dummy(_):
            return Image.new("RGBA",(600,600),"#556677"),"SHA_MATCH"
        with TemporaryDirectory() as tmp:
            p=Path(tmp)/"sheet.png"
            r=Path(tmp)/"review.json"
            out=render(dataset(),p,r,fetcher=dummy)
            self.assertTrue(p.exists())
            with Image.open(p) as img:
                self.assertGreater(img.width,300)
                self.assertGreater(img.height,300)
            self.assertTrue(r.exists())
            self.assertEqual(out["sha_matching_previews"],1)
            self.assertFalse(out["editorial_identity_approved"])
            self.assertFalse(out["publication_allowed"])
            self.assertFalse(out["signed_catalog_created"])

    def test_source_sha_change_prevents_approved_preview(self):
        def changed(_):
            return None,"CHANGED_AFTER_PREVIOUS_SHA:sha256"
        with TemporaryDirectory() as tmp:
            out=render(dataset(),Path(tmp)/"sheet.png",
                       Path(tmp)/"review.json",fetcher=changed)
            self.assertEqual(out["sha_matching_previews"],0)
            self.assertEqual(out["records"][0]["status"],
                             "CHANGED_AFTER_PREVIOUS_SHA:sha256")

    def test_malicious_publishing_flag_rejected(self):
        d=dataset()
        d["publication_allowed"]=True
        with self.assertRaises(OGVisualError):
            select(d)
        d=dataset()
        d["records"][0]["identity_visual_approved"]=True
        with self.assertRaises(OGVisualError):
            select(d)

    def test_shards_must_cover_exact_missing_uuid_count(self):
        d=dataset()
        d["historical_scanned"]=2
        with self.assertRaises(OGVisualError):
            select(d)


if __name__=="__main__":
    unittest.main()
