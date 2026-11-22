#!/usr/bin/env python3
"""Offline regression tests: v5 technical evidence must never publish logos."""
import copy
import unittest

from assemble_v5_artwork_editorial_queue import build_queue, ReviewQueueError

URL = "https://new-provider.example.net/artwork/bob_metalcore_600x600.png"
SHA = "a" * 64
ID1 = "11111111-1111-1111-1111-111111111111"
ID2 = "22222222-2222-2222-2222-222222222222"


def fixtures():
    def station(sid, name, missing):
        return {
            "legacy_media_id": sid, "station_name": name,
            "review_flags": ["bootstrap_logo_missing"] if missing else [],
            "publication_allowed": False, "visual_identity_approved": False,
            "candidates": [{
                "evidence_source": "live_public_manifest",
                "url": URL, "publication_allowed": False,
                "requires_byte_sha_and_visual_review": True,
                "metadata": {"reported_width": 600, "reported_height": 600},
            }],
        }
    reconciliation = {
        "scope": "GROSSES_ONDES_LEGACY_ARTWORK_RECONCILIATION_UNREVIEWED",
        "public_manifest_version": 5, "publication_allowed": False,
        "signed_catalog_created": False, "discovery_is_open": True,
        "historical_stations": [
            station(ID1, "DrGnu - Metalcore 1", True),
            station(ID2, "RADIO BOB! Metalcore", False)],
        "unmatched_public_manifest_ids": [],
    }
    shard = {
        "scope": "GROSSES_ONDES_PUBLIC_MANIFEST_LOGO_SHA_EVIDENCE_ONLY",
        "public_manifest_version": 5, "publication_allowed": False,
        "signed_catalog_created": False, "shard_index": 0, "shard_count": 1,
        "total_unique_manifest_urls": 1,
        "unique_candidate_urls_in_shard": 1,
        "records": [{
            "url": URL, "legacy_media_ids": [ID1, ID2],
            "publication_allowed": False,
            "needs_station_identity_review": True,
            "source_manifest_version": 5,
            "probe": {
                "verified_bytes": True, "sha256": SHA,
                "byte_size": 74342, "width": 600, "height": 600,
                "mime_type": "image/png", "approved_station_logo": False,
            },
        }],
    }
    pilot = {
        "scope": "TEST_ONLY", "production_publication_allowed": False,
        "catalog_id": "grosses-ondes-artwork",
        "assets": [{"legacy_media_id": ID1, "logo": {"sha256": SHA},
                    "replace_existing_logo": False}],
    }
    return reconciliation, shard, pilot


class QueueTests(unittest.TestCase):
    def test_reuses_exact_approved_test_sha_without_publishing(self):
        rec, shard, pilot = fixtures()
        report = build_queue(rec, [shard], pilot)
        self.assertEqual(report["summary"]["unique_urls_checked"], 1)
        self.assertEqual(report["summary"]["historical_uuid_with_verified_bytes"], 2)
        self.assertEqual(report["summary"]["historical_no_bootstrap_with_verified_bytes"], 1)
        self.assertEqual(report["summary"]["priority_previously_reviewed_test_sha_match"], 1)
        self.assertEqual(len(report["priority_no_initial_logo"]), 1)
        row = report["priority_no_initial_logo"][0]
        self.assertEqual(row["editorial_review_status"], "PREVIOUS_TEST_VISUAL_SHA_MATCH")
        self.assertIn("DRGNU_SOURCE_HAS_RADIO_BOB_BRANDING_REVIEW", row["review_flags"])
        self.assertIn("SHARED_IMAGE_UUIDS_NEVER_MERGE", row["review_flags"])
        self.assertFalse(row["publication_allowed"])
        self.assertFalse(report["signed_catalog_created"])

    def test_no_pilot_never_creates_visual_approval(self):
        rec, shard, _ = fixtures()
        report = build_queue(rec, [shard])
        self.assertEqual(
            report["priority_no_initial_logo"][0]["editorial_review_status"],
            "IDENTITY_VISUAL_REVIEW_REQUIRED")

    def test_shard_must_cover_all_urls(self):
        rec, shard, _ = fixtures()
        bad = copy.deepcopy(shard)
        bad["shard_count"] = 2
        with self.assertRaises(ReviewQueueError):
            build_queue(rec, [bad])

    def test_probe_uuid_mismatch_is_rejected(self):
        rec, shard, _ = fixtures()
        shard["records"][0]["legacy_media_ids"] = [ID1]
        with self.assertRaises(ReviewQueueError):
            build_queue(rec, [shard])

    def test_probe_cannot_approve_station(self):
        rec, shard, _ = fixtures()
        shard["records"][0]["probe"]["approved_station_logo"] = True
        with self.assertRaises(ReviewQueueError):
            build_queue(rec, [shard])

    def test_pilot_sha_mismatch_is_held(self):
        rec, shard, pilot = fixtures()
        pilot["assets"][0]["logo"]["sha256"] = "b" * 64
        report = build_queue(rec, [shard], pilot)
        self.assertEqual(
            report["priority_no_initial_logo"][0]["editorial_review_status"],
            "PILOT_SHA_MISMATCH_HOLD")

    def test_low_resolution_flag_does_not_delete_station(self):
        rec, shard, _ = fixtures()
        shard["records"][0]["probe"]["width"] = 120
        report = build_queue(rec, [shard])
        self.assertIn("ACTUAL_IMAGE_UNDER_192PX",
                      report["priority_no_initial_logo"][0]["review_flags"])
        self.assertEqual(len(report["historical_associations"]), 2)

    def test_refuses_active_or_production_sidecar(self):
        rec, shard, pilot = fixtures()
        pilot["production_publication_allowed"] = True
        with self.assertRaises(ReviewQueueError):
            build_queue(rec, [shard], pilot)


if __name__ == "__main__":
    unittest.main()
