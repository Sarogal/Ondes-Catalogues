#!/usr/bin/env python3
"""No network: verify lossless UUID reconciliation and zero auto-publishing."""
import copy
import unittest

from reconcile_legacy_logo_manifests import (
    reconcile, validate_manifest, ReconciliationError,
)

IDA = "11111111-1111-4111-8111-111111111111"
IDB = "22222222-2222-4222-8222-222222222222"
IDC = "33333333-3333-4333-8333-333333333333"
IDD = "44444444-4444-4444-8444-444444444444"


def source_row(uuid, name, logo):
    return {
        "legacy_media_id": uuid, "display_name": name,
        "primary_genre": "Punk", "homepage": "https://radio.example.org/",
        "source_logo_url": logo,
        "logo_state": "unverified_historical" if logo else "discovery_needed",
        "editorial_decision": "none", "source_position": 0,
    }


def inventory():
    return {
        "schema_version": 1,
        "scope": "GROSSES_ONDES_TEST_ARTWORK_INTAKE_NOT_PUBLICATION",
        "publication_allowed": False, "no_closed_station_list": True,
        "source": {"blob_sha": "a" * 40},
        "stations": [
            source_row(IDA, "A", "https://radio-a.example.org/old.jpg"),
            source_row(IDB, "B", ""),
            source_row(IDC, "C", ""),
        ],
    }


def entry(id_, url, width=600, height=600):
    return {
        "id": id_, "url": url, "sizeBytes": 12345,
        "width": width, "height": height, "revision": 1,
    }


def manifest(entries, version):
    return {"schema": 1, "version": version, "entries": entries}


class ReconciliationTests(unittest.TestCase):
    def test_old_logo_preserved_and_missing_logo_found_in_new_manifest(self):
        old = manifest([entry(IDA, "https://radio-a.example.org/old.jpg")], 4)
        new = manifest([
            entry(IDA, "https://radio-a.example.org/old.jpg"),
            entry(IDB, "https://new-source.example.org/new-logo.webp"),
            entry(IDD, "https://unseen-provider.example.org/punk.png"),
        ], 5)
        before = copy.deepcopy(inventory())
        data = reconcile(before, new, old)
        self.assertEqual(before, inventory(), "No mutation of V64 inventory")
        summary = data["summary"]
        self.assertEqual(summary["historical_station_count"], 3)
        self.assertEqual(summary["public_manifest_associations"], 3)
        self.assertEqual(summary["history_with_public_manifest"], 2)
        self.assertEqual(summary["history_missing_bootstrap_but_in_public_manifest"], 1)
        self.assertEqual(summary["history_without_public_manifest"], 1)
        self.assertEqual(summary["public_manifest_not_in_historical_snapshot"], 1)
        self.assertEqual(summary["new_public_manifest_ids_since_previous"], 2)
        self.assertEqual(data["new_public_manifest_ids"], [IDB, IDD])
        self.assertEqual(len(data["unmatched_public_manifest_ids"]), 1)
        self.assertEqual(data["unmatched_public_manifest_ids"][0]["station_identity"],
                         "requires_signed_catalog_uuid_alias_join")
        a = next(s for s in data["historical_stations"]
                 if s["legacy_media_id"] == IDA)
        self.assertEqual(len(a["candidates"]), 2)
        self.assertEqual(a["candidates"][0]["evidence_source"], "legacy_v64_bootstrap")
        b = next(s for s in data["historical_stations"]
                 if s["legacy_media_id"] == IDB)
        self.assertEqual(len(b["candidates"]), 1)
        self.assertTrue(b["candidates"][0]["safe_public_https_candidate"])
        self.assertTrue(b["candidates"][0]["requires_byte_sha_and_visual_review"])
        self.assertFalse(data["publication_allowed"])
        self.assertFalse(data["signed_catalog_created"])
        self.assertTrue(all(not s["publication_allowed"]
                            for s in data["historical_stations"]))
        self.assertTrue(all(not s["publication_allowed"]
                            for s in data["unmatched_public_manifest_ids"]))

    def test_small_images_and_http_stay_as_evidence_not_preapproved(self):
        src = inventory()
        src["stations"][0]["source_logo_url"] = "http://radio-a.example.org/logo.jpg"
        new = manifest([entry(IDA, "https://unknown-public.example.org/logo.jpg", 145, 145)], 5)
        result = reconcile(src, new)
        a = result["historical_stations"][0]
        self.assertIn("public_manifest_image_needs_resolution_review",
                      a["review_flags"])
        self.assertIn("non_public_https_url_no_download", a["review_flags"])
        self.assertFalse(a["candidates"][0]["safe_public_https_candidate"])
        self.assertTrue(a["candidates"][1]["safe_public_https_candidate"])
        self.assertEqual(a["candidates"][1]["metadata"]["reported_width"], 145)
        self.assertFalse(a["visual_identity_approved"])

    def test_unknown_station_and_provider_remain_candidates_not_allowlisted(self):
        new = manifest([entry(IDD, "https://brand-new-source.example.net/special.svg")], 5)
        result = reconcile(inventory(), new)
        self.assertEqual(len(result["unmatched_public_manifest_ids"]), 1)
        self.assertTrue(result["discovery_is_open"])
        self.assertFalse(result["unmatched_public_manifest_ids"][0]
                         ["visual_identity_approved"])

    def test_duplicate_ids_and_malformed_metadata_rejected(self):
        duplicate = manifest([
            entry(IDA, "https://one.example.com/logo.png"),
            entry(IDA, "https://two.example.com/logo.png")
        ], 5)
        with self.assertRaises(ReconciliationError):
            reconcile(inventory(), duplicate)
        broken = manifest([entry(IDA, "https://one.example.com/logo.png")], 5)
        broken["entries"][0]["sizeBytes"] = "12345"
        with self.assertRaises(ReconciliationError):
            validate_manifest(broken)

    def test_removed_or_updated_manifest_entries_reported_without_deletion(self):
        old = manifest([entry(IDA, "https://one.example.org/logo.png"),
                        entry(IDB, "https://other.example.org/logo.png")], 4)
        new = manifest([entry(IDA, "https://one.example.org/logo_hd.png")], 5)
        result = reconcile(inventory(), new, old)
        self.assertEqual(result["removed_public_manifest_ids"], [IDB])
        self.assertEqual(result["changed_public_manifest_ids"], [IDA])
        self.assertEqual(len(result["historical_stations"]), 3)
        self.assertEqual(result["summary"]["history_without_public_manifest"], 2)


if __name__ == "__main__":
    unittest.main()
