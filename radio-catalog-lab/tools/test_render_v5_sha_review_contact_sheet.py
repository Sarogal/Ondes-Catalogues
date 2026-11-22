#!/usr/bin/env python3
"""No-network tests for SHA contact sheet isolation and shared-URL caching."""
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from render_v5_sha_review_contact_sheet import pick_candidates, render, ContactReviewError

URL = "https://new-station.example.net/channel/logo.png"


def sample():
    def item(uuid, name):
        return {
            "legacy_media_id": uuid, "station_name": name,
            "source_url": URL, "source_host": "new-station.example.net",
            "editorial_review_status": "IDENTITY_VISUAL_REVIEW_REQUIRED",
            "probe_verified": True, "sha256": "a"*64, "byte_size": 1500,
            "width": 600, "height": 600, "mime_type": "image/png",
            "publication_allowed": False, "replace_existing_logo": False,
        }
    return {
        "scope": "GO_ARTWORK_V5_EDITORIAL_TRIAGE_ONLY",
        "publication_allowed": False, "signed_catalog_created": False,
        "discovery_is_open": True,
        "priority_no_initial_logo": [
            item("11111111-1111-1111-1111-111111111111", "A radio"),
            item("22222222-2222-2222-2222-222222222222", "B radio")
        ]
    }


class ReviewSheetTests(unittest.TestCase):
    def test_two_uuid_same_url_downloaded_once_and_never_merged(self):
        q = sample()
        calls = []
        def fake(row):
            calls.append(row["source_url"])
            return Image.new("RGBA", (100, 100), "black"), "SHA_MATCH"
        with tempfile.TemporaryDirectory() as td:
            image, report = Path(td)/"review.png", Path(td)/"report.json"
            data = render(q, image, report, shard_index=0,
                          shard_count=1, fetcher=fake)
            self.assertTrue(image.exists())
            self.assertEqual(len(calls), 1)
            self.assertEqual(data["candidate_rows"], 2)
            self.assertEqual(data["unique_urls_fetched"], 1)
            self.assertEqual(data["sha_matching_previews"], 2)
            self.assertEqual(len({x["legacy_media_id"] for x in data["records"]}), 2)
            self.assertFalse(json.loads(report.read_text())["publication_allowed"])

    def test_prior_pilot_approval_is_not_re_reviewed(self):
        q = sample()
        q["priority_no_initial_logo"][0]["editorial_review_status"] = (
            "PREVIOUS_TEST_VISUAL_SHA_MATCH")
        rows = pick_candidates(q, shard_index=0, shard_count=1)
        self.assertEqual(len(rows), 1)

    def test_unsigned_queue_required(self):
        q = sample()
        q["publication_allowed"] = True
        with self.assertRaises(ContactReviewError):
            pick_candidates(q, shard_index=0, shard_count=1)

    def test_duplicate_uuids_rejected(self):
        q = sample()
        q["priority_no_initial_logo"][1]["legacy_media_id"] = (
            q["priority_no_initial_logo"][0]["legacy_media_id"])
        with self.assertRaises(ContactReviewError):
            pick_candidates(q, shard_index=0, shard_count=1)

    def test_no_unknown_shard(self):
        with self.assertRaises(ContactReviewError):
            pick_candidates(sample(), shard_index=6, shard_count=6)

    def test_explicitly_no_source_permissions(self):
        q = sample()
        q["priority_no_initial_logo"][0]["replace_existing_logo"] = True
        with self.assertRaises(ContactReviewError):
            pick_candidates(q, shard_index=0, shard_count=1)


if __name__ == "__main__":
    unittest.main()
