#!/usr/bin/env python3
"""No-network guards for TEST-only reviewed artwork sidecar."""
from copy import deepcopy
from pathlib import Path
import json
import sys
import unittest

TOOLS=Path(__file__).resolve().parent
sys.path.insert(0,str(TOOLS))
from compose_reviewed_artwork_test_manifest import compose, ArtworkReviewError

REVIEW=TOOLS.parents[1]/"grossesondes/radio-test-apk/artwork/first_visual_review_20261121.json"


def fixtures():
    src={
        "station_slug":"brand_new_station_2027",
        "legacy_media_id":"123e4567-e89b-42d3-a456-426614174000",
        "historical_name":"Brand New Rock",
        "old_source_logo_url":"",
        "identity_provider":"official_laut_fm_api",
        "editorial_status":"candidate_requires_visual_identity_review",
        "allow_replace_historical_logo":False,
        "can_activate":False,"publication_allowed":False,
        "official_station_page":"https://laut.fm/brand_new_station_2027",
        "candidate_logo":{
            "asset_id":"sha256:"+"a"*64,
            "sha256":"a"*64,
            "url":"https://assets.laut.fm/"+"b"*32,
            "byte_size":30000,"width":600,"height":600,
            "mime_type":"image/png","revision":1,
        },
    }
    q={"scope":"LOGO_SHA_PREPUBLICATION_REVIEW_ONLY",
       "publication_allowed":False, "signed_catalog_created":False,
       "logo_candidates":[src]}
    review={"scope":"GROSSES_ONDES_TEST_VISUAL_REVIEW_ONLY",
       "publication_allowed":False,"open_discovery_not_allowlist":True,
       "approved_for_test":1,"held":0,
       "records":[{
         "station_slug":src["station_slug"],
         "decision":"test_visual_approved",
         "visual_evidence":"Explicit wordmark Brand New Rock",
         "scope":"test_only","publication_allowed":False,
         "replace_existing_logo":False,
       }]}
    return q,review


class SidecarReviewTests(unittest.TestCase):
    def test_new_unknown_station_accepted_without_allowlist(self):
        q,review=fixtures()
        manifest=compose(q,review,generated_at="2026-11-21T11:30:00Z")
        self.assertEqual(len(manifest["assets"]),1)
        self.assertEqual(manifest["assets"][0]["legacy_media_id"],
                         q["logo_candidates"][0]["legacy_media_id"])
        self.assertEqual(manifest["source_radio_catalog_min_sequence"],4)
        self.assertFalse(manifest["production_publication_allowed"])
        self.assertFalse(manifest["assets"][0]["replace_existing_logo"])

    def test_review_missing_or_auto_approval_is_refused(self):
        q,rev=fixtures()
        rev["records"]=[]
        with self.assertRaises(ArtworkReviewError):
            compose(q,rev,generated_at="2026-11-21T11:30:00Z")
        q,rev=fixtures()
        rev["records"][0]["publication_allowed"]=True
        with self.assertRaises(ArtworkReviewError):
            compose(q,rev,generated_at="2026-11-21T11:30:00Z")

    def test_image_without_clear_review_or_resolution_refused(self):
        q,rev=fixtures()
        q["logo_candidates"][0]["candidate_logo"]["width"]=120
        with self.assertRaises(ArtworkReviewError):
            compose(q,rev,generated_at="2026-11-21T11:30:00Z")
        q,rev=fixtures()
        rev["records"][0]["decision"]="hold"
        rev["approved_for_test"]=0
        rev["held"]=1
        self.assertEqual(compose(q,rev,generated_at="2026-11-21T11:30:00Z")
                         ["assets"],[])

    def test_changed_url_or_old_logo_replacement_denied(self):
        q,rev=fixtures()
        q["logo_candidates"][0]["candidate_logo"]["url"]="http://other.host/radio"
        with self.assertRaises(ArtworkReviewError):
            compose(q,rev,generated_at="2026-11-21T11:30:00Z")
        q,rev=fixtures()
        q["logo_candidates"][0]["old_source_logo_url"]="https://old.logo/radio.png"
        with self.assertRaises(ArtworkReviewError):
            compose(q,rev,generated_at="2026-11-21T11:30:00Z")

    def test_rejects_duplicate_historical_uuid(self):
        q,rev=fixtures()
        second=deepcopy(q["logo_candidates"][0])
        second["station_slug"]="other_new_station"
        second["official_station_page"]="https://laut.fm/other_new_station"
        q["logo_candidates"].append(second)
        rev["records"].append({
            "station_slug":"other_new_station",
            "decision":"test_visual_approved",
            "visual_evidence":"Explicit Other New Station name",
            "scope":"test_only","publication_allowed":False,
            "replace_existing_logo":False,
        })
        rev["approved_for_test"]=2
        with self.assertRaises(ArtworkReviewError):
            compose(q,rev,generated_at="2026-11-21T11:30:00Z")

    def test_committed_review_document_is_test_only(self):
        doc=json.loads(REVIEW.read_text(encoding="utf-8"))
        self.assertEqual(doc["approved_for_test"],9)
        self.assertEqual(doc["held"],10)
        self.assertEqual(len(doc["records"]),19)
        self.assertFalse(doc["publication_allowed"])


if __name__=="__main__":
    unittest.main()
