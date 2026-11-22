#!/usr/bin/env python3
"""Offline gate for SHA-rechecked Ritus-style sized images."""
from copy import deepcopy
import unittest

from probe_v5_reviewed_resized_artwork import (
    verify_resized_review, ResizeProbeError,
)

SID="681c6fee-8d61-437b-84a4-f96b8fd3422c"
URL="https://assets.laut.fm/"+"a"*32+"?t=_640x640"
CANONICAL="https://assets.laut.fm/"+"a"*32
SHA="b"*64


def fixtures():
    visual={
        "scope":"GO_V5_EXPLICIT_VISUAL_DECISIONS_TEST_ONLY_UNSIGNED",
        "publication_allowed":False,"signed_catalog_created":False,
        "records":[{
            "legacy_media_id":SID,"station_name":"Ritus",
            "candidate_sha256":SHA,"candidate_url":URL,
            "desired_canonical_url":CANONICAL,
            "expected_width":640,"expected_height":640,
            "source_official_page":"https://laut.fm/ritus",
            "editorial_decision":"VISUAL_TEST_ACCEPTED_CANONICAL_BYTES_PENDING",
            "publication_allowed":False,"can_sign_now":False,
        }],
    }
    queue={
        "scope":"GO_ARTWORK_V5_EDITORIAL_TRIAGE_ONLY",
        "publication_allowed":False,
        "priority_no_initial_logo":[{
            "legacy_media_id":SID,"probe_verified":True,
            "publication_allowed":False,
            "sha256":SHA,"byte_size":600273,
            "width":640,"height":640,"mime_type":"image/png",
            "source_url":URL,
        }],
    }
    source={
        "records":[{
            "legacy_media_id":SID,
            "candidate_sha256":SHA,"candidate_url":URL,
            "publication_allowed":False,
            "source_status":"OFFICIAL_API_EXACT_ASSET_PATH",
            "source_evidence":[{
                "kind":"laut_fm_exact_station_slug_api",
                "source_path_matches_candidate":True,
                "official_station_page":"https://laut.fm/ritus",
                "official_image_url":CANONICAL,
            }]
        }],
    }
    return visual,queue,[source]


def fresh(sha=SHA):
    return {
        "approved_station_logo":False,"verified_bytes":True,
        "sha256":sha,"byte_size":600273,"width":640,"height":640,
        "mime_type":"image/png",
    }


class TestResizedProvenance(unittest.TestCase):
    def test_fresh_sha_match_no_publication(self):
        a,b,c=fixtures()
        result=verify_resized_review(a,b,c,candidate_uuid=SID,
                                     network=True,probe=lambda _:fresh())
        self.assertTrue(result["fresh_sha_size_mime_dimensions_match"])
        self.assertFalse(result["publication_allowed"])
        self.assertFalse(result["signed_catalog_created"])

    def test_hash_changed_is_not_signed(self):
        a,b,c=fixtures()
        result=verify_resized_review(a,b,c,candidate_uuid=SID,
                                     network=True,probe=lambda _:fresh("c"*64))
        self.assertFalse(result["fresh_sha_size_mime_dimensions_match"])

    def test_offline_makes_no_request(self):
        a,b,c=fixtures()
        def forbidden(_): raise AssertionError("Network forbidden")
        result=verify_resized_review(a,b,c,candidate_uuid=SID,network=False,probe=forbidden)
        self.assertFalse(result["fresh_sha_size_mime_dimensions_match"])

    def test_wrong_uuid_rejected(self):
        a,b,c=fixtures()
        with self.assertRaises(ResizeProbeError):
            verify_resized_review(a,b,c,candidate_uuid="other",network=False)

    def test_malformed_or_extra_size_modifier_is_rejected(self):
        a,b,c=fixtures()
        for modifier in ("?t=_640x600","?t=_640x640&other=1","?debug=1"):
            x,y,z=deepcopy((a,b,c))
            x["records"][0]["candidate_url"]=CANONICAL+modifier
            y["priority_no_initial_logo"][0]["source_url"]=CANONICAL+modifier
            z[0]["records"][0]["candidate_url"]=CANONICAL+modifier
            with self.subTest(modifier=modifier),self.assertRaises(ResizeProbeError):
                verify_resized_review(x,y,z,candidate_uuid=SID,network=False)

    def test_visual_flag_cannot_authorize_signing(self):
        a,b,c=fixtures()
        a["records"][0]["can_sign_now"]=True
        with self.assertRaises(ResizeProbeError):
            verify_resized_review(a,b,c,candidate_uuid=SID,network=False)

    def test_disagreeing_api_identity_rejected(self):
        a,b,c=fixtures()
        c[0]["records"][0]["source_evidence"][0]["official_station_page"]="https://laut.fm/other"
        with self.assertRaises(ResizeProbeError):
            verify_resized_review(a,b,c,candidate_uuid=SID,network=False)

    def test_byte_probe_cannot_claim_logo_identity(self):
        a,b,c=fixtures()
        with self.assertRaises(ResizeProbeError):
            verify_resized_review(a,b,c,candidate_uuid=SID,network=True,
                                  probe=lambda _:{**fresh(),"approved_station_logo":True})


if __name__=="__main__":
    unittest.main()
