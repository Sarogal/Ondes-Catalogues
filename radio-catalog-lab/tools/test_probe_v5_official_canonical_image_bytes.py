#!/usr/bin/env python3
"""Offline regression checks: canonical SHA is a separate requirement."""
import copy
import unittest

from probe_v5_official_canonical_image_bytes import (
    collect, CanonicalEvidenceError,
)

SID = "11111111-1111-1111-1111-111111111111"
SID2 = "22222222-2222-2222-2222-222222222222"
ASSET = "https://assets.laut.fm/" + "a"*32
EXPECTED = "b"*64


def fixture():
    return {
        "scope": "GO_V5_OFFICIAL_SOURCE_CORROBORATION_REVIEW_ONLY",
        "shard_count": 1, "shard_index": 0,
        "publication_allowed": False, "identity_visual_approved": False,
        "signed_catalog_created": False, "candidate_count": 1,
        "records": [{
            "legacy_media_id": SID, "station_name": "Unknown metal channel",
            "candidate_url": ASSET + "?t=_640x640",
            "candidate_sha256": EXPECTED,
            "source_status": "OFFICIAL_API_EXACT_ASSET_PATH",
            "source_evidence": [{
                "kind": "laut_fm_exact_station_slug_api",
                "official_station_page": "https://laut.fm/any-new-metal-radio",
                "official_image_url": ASSET,
                "source_path_matches_candidate": True,
            }],
            "publication_allowed": False,
            "identity_visual_approved": False,
        }],
    }


def img(sha=EXPECTED, width=600, height=600):
    return {"sha256": sha, "verified_bytes": True, "approved_station_logo": False,
            "publication_allowed": False, "byte_size": 12345, "width": width,
            "height": height, "mime_type": "image/png"}


class CanonicalTests(unittest.TestCase):
    def test_matching_canonical_sha_is_not_editorial_approval(self):
        q = fixture()
        report = collect([q], network=True, downloader=lambda url: img())
        self.assertEqual(report["same_sha_and_quality"], 1)
        self.assertEqual(report["canonical_image_count"], 1)
        self.assertFalse(report["publication_allowed"])
        self.assertFalse(report["records"][0]["identity_visual_approved"])
        self.assertFalse(report["records"][0]["replace_existing_logo"])

    def test_different_sha_requires_review_not_auto_switch(self):
        report = collect([fixture()], network=True,
                         downloader=lambda _: img(sha="c"*64))
        self.assertEqual(report["same_sha"], 0)
        self.assertFalse(report["records"][0]["canonical_sha_and_quality_ready_for_visual_review"])

    def test_small_canonical_asset_not_signed(self):
        report = collect([fixture()], network=True,
                         downloader=lambda _: img(width=120, height=120))
        self.assertEqual(report["same_sha"], 1)
        self.assertEqual(report["same_sha_and_quality"], 0)

    def test_no_network_does_not_probe(self):
        def blocked(_):
            raise AssertionError("No download expected")
        report = collect([fixture()], network=False, downloader=blocked)
        self.assertEqual(report["same_sha"], 0)
        self.assertEqual(report["canonical_image_count"], 1)

    def test_missing_shard_fails_closed(self):
        q=fixture()
        q["shard_count"]=2
        with self.assertRaises(CanonicalEvidenceError):
            collect([q], network=False)

    def test_unsigned_source_only(self):
        q=fixture()
        q["publication_allowed"]=True
        with self.assertRaises(CanonicalEvidenceError):
            collect([q], network=False)

    def test_wrong_asset_domain_rejected(self):
        q=fixture()
        q["records"][0]["source_evidence"][0]["official_image_url"]="https://notlaut.example/logo.png"
        with self.assertRaises(CanonicalEvidenceError):
            collect([q], network=False)

    def test_cannot_approve_from_byte_probe(self):
        with self.assertRaises(CanonicalEvidenceError):
            collect([fixture()], network=True,
                    downloader=lambda _: {**img(), "approved_station_logo": True})

    def test_two_uuid_same_canonical_url_keeps_two_identities_one_fetch(self):
        q=fixture()
        q["records"].append(copy.deepcopy(q["records"][0]))
        q["records"][1]["legacy_media_id"]=SID2
        q["candidate_count"]=2
        calls=[]
        def probe(url):
            calls.append(url)
            return img()
        d=collect([q], network=True, downloader=probe)
        self.assertEqual(len(calls),1)
        self.assertEqual(len(d["records"]),2)
        self.assertEqual(d["same_sha"],2)

    def test_canonical_modified_live_file_not_considered_original(self):
        report=collect([fixture()],network=True,downloader=lambda _:
                       {"verified_bytes":False,"reason":"HTTPError",
                        "publication_allowed":False,
                        "approved_station_logo":False})
        self.assertEqual(report["same_sha"],0)
        self.assertEqual(report["candidate_radios"],1)


if __name__ == "__main__":
    unittest.main()
