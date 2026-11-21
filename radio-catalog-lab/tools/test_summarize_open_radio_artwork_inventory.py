#!/usr/bin/env python3
"""Offline tests: do not publish based on logo hash evidence alone."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
from audit_open_radio_artwork_inventory import audit
from summarize_open_radio_artwork_inventory import consolidate, EvidenceError

INVENTORY = (
    TOOLS.parents[1] / "grossesondes" / "radio-test-apk" /
    "artwork" / "legacy_v64_inventory.json"
)


class FullLogoEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = json.loads(INVENTORY.read_text(encoding="utf-8"))

    def reports(self):
        return [
            audit(self.document, shard_index=i, shard_count=8, network=False)
            for i in range(8)
        ]

    def test_310_fully_reconciled_without_network(self):
        result = consolidate(self.document, self.reports())
        self.assertEqual(result["historical_station_count"], 310)
        self.assertEqual(result["shards"], 8)
        self.assertFalse(result["publication_allowed"])
        self.assertFalse(result["signed_catalog_created"])
        self.assertEqual(len(result["records"]), 310)
        self.assertTrue(all(
            not r["station_logo_approved"] and r["sha256"] is None
            for r in result["records"]
        ))
        self.assertEqual(result["summary"]["legacy_https"], 130)
        self.assertEqual(result["summary"]["legacy_http"], 38)
        self.assertEqual(result["summary"]["needs_discovery"], 142)

    def test_incomplete_or_duplicate_shard_refused(self):
        reports = self.reports()
        with self.assertRaises(EvidenceError):
            consolidate(self.document, reports[:-1])
        with self.assertRaises(EvidenceError):
            consolidate(self.document, reports+[reports[0]])

    def test_rejects_unknown_or_shifted_or_preapproved_media_ids(self):
        reports = self.reports()
        reports[0]["records"][0]["legacy_media_id"] = "unknown-unreviewed-station"
        with self.assertRaises(EvidenceError):
            consolidate(self.document, reports)
        reports = self.reports()
        reports[0]["records"][0]["station_logo_approved"] = True
        with self.assertRaises(EvidenceError):
            consolidate(self.document, reports)

    def test_valid_sha_evidence_never_automatically_becomes_logo_approval(self):
        reports = self.reports()
        row = next(r for report in reports for r in report["records"]
                   if r["source_kind"] == "legacy_https")
        row["probe"] = {
            "verified_bytes": True, "sha256": "a" * 64,
            "byte_size": 4000, "width": 256, "height": 256,
            "mime_type": "image/jpeg",
            "candidate_url": row["source_logo_url"],
            "reason": "decoded_sha_only_editorial_identity_unreviewed",
        }
        full = consolidate(self.document, reports)
        evidence = next(r for r in full["records"]
                        if r["legacy_media_id"] == row["legacy_media_id"])
        self.assertTrue(evidence["bytes_verified_by_sha_and_decoder"])
        self.assertFalse(evidence["station_logo_approved"])
        self.assertEqual(
            evidence["editorial_state"],
            "evidence_ready_for_manual_identity_review",
        )

    def test_same_sha_across_multiple_station_ids_is_only_review_flag(self):
        reports = self.reports()
        sources = [r for report in reports for r in report["records"]
                   if r["source_kind"] == "legacy_https"][:2]
        for row in sources:
            row["probe"] = {
                "verified_bytes": True, "sha256": "d"*64,
                "byte_size": 10000, "width": 512, "height": 512,
                "mime_type": "image/png",
                "candidate_url": row["source_logo_url"],
            }
        full = consolidate(self.document, reports)
        self.assertEqual(len(full["duplicate_sha_groups"]), 1)
        self.assertEqual(len(full["duplicate_sha_groups"][0]["legacy_media_ids"]), 2)
        for row in full["records"]:
            if row["legacy_media_id"] in {
                x["legacy_media_id"] for x in sources
            }:
                self.assertIn("identical_bytes_for_multiple_stations_review_identity",
                              row["review_flags"])
                self.assertFalse(row["station_logo_approved"])


if __name__ == "__main__":
    unittest.main()
