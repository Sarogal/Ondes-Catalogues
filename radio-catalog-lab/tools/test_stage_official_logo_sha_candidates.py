#!/usr/bin/env python3
"""Offline negative tests for image-only prepublication queue."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

TOOLS=Path(__file__).resolve().parent
sys.path.insert(0,str(TOOLS))
from audit_open_radio_artwork_inventory import InventoryError
from stage_official_logo_sha_candidates import stage

INV=TOOLS.parents[1] / "grossesondes/radio-test-apk/artwork/legacy_v64_inventory.json"


def example(row):
    slug="new_station_never_seen"
    return {
        "legacy_media_id":row["legacy_media_id"],
        "historical_name":row["display_name"],
        "historical_homepage":row["homepage"],
        "station_logo_approved":False,
        "publication_allowed":False,
        "identity_verified_from_official_api":True,
        "verified_image_bytes":True,
        "official_image":"https://assets.laut.fm/"+"a"*32,
        "official_page":"https://laut.fm/"+slug,
        "slug":slug,
        "image_byte_evidence":{
            "candidate_url":"https://assets.laut.fm/"+"a"*32,
            "verified_bytes":True,
            "approved_station_logo":False,
            "sha256":"f"*64,
            "byte_size":30000,"width":512,"height":512,
            "mime_type":"image/png",
        },
    }


class StagedLogoReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inv=json.loads(INV.read_text(encoding="utf-8"))

    def pair(self):
        row=next(x for x in self.inv["stations"] if
                 not x["source_logo_url"])
        record=example(row)
        evidence={
            "scope":"OFFICIAL_LAUT_FM_ARTWORK_DISCOVERY_NOT_PUBLICATION",
            "source_blob_sha":self.inv["source"]["blob_sha"],
            "publication_allowed":False, "signed_catalog_created":False,
            "records":[record],
        }
        return record,evidence

    def test_safe_new_logo_candidate_keeps_uuid_and_does_not_publish(self):
        record,evidence=self.pair()
        queued=stage(self.inv,evidence)
        self.assertEqual(len(queued["logo_candidates"]),1)
        x=queued["logo_candidates"][0]
        self.assertEqual(x["legacy_media_id"],record["legacy_media_id"])
        self.assertFalse(x["allow_replace_historical_logo"])
        self.assertFalse(x["can_activate"])
        self.assertFalse(x["publication_allowed"])
        self.assertFalse(queued["signed_catalog_created"])
        self.assertEqual(x["candidate_logo"]["sha256"],"f"*64)
        self.assertEqual(x["candidate_logo"]["asset_id"],"sha256:"+"f"*64)

    def test_metadata_can_be_untrusted_even_with_good_hash(self):
        record,evidence=self.pair()
        evidence["records"][0]["official_image"]="https://cdn.unrelated.org/logo.png"
        with self.assertRaises(InventoryError):
            stage(self.inv,evidence)
        record,evidence=self.pair()
        evidence["records"][0]["image_byte_evidence"]["candidate_url"]=(
            "https://assets.laut.fm/"+"b"*32
        )
        with self.assertRaises(InventoryError):
            stage(self.inv,evidence)

    def test_wrong_station_or_same_uuid_twice_rejected(self):
        record,evidence=self.pair()
        evidence["records"][0]["historical_name"]="Unrelated radio"
        with self.assertRaises(InventoryError):
            stage(self.inv,evidence)
        record,evidence=self.pair()
        evidence["records"].append(deepcopy(record))
        with self.assertRaises(InventoryError):
            stage(self.inv,evidence)

    def test_explicit_editorial_approval_is_not_accepted_from_candidate(self):
        record,evidence=self.pair()
        evidence["records"][0]["station_logo_approved"]=True
        with self.assertRaises(InventoryError):
            stage(self.inv,evidence)
        record,evidence=self.pair()
        evidence["publication_allowed"]=True
        with self.assertRaises(InventoryError):
            stage(self.inv,evidence)

    def test_failed_image_is_excluded_without_deleting_station(self):
        record,evidence=self.pair()
        evidence["records"][0]["verified_image_bytes"]=False
        evidence["records"][0]["reason"]="image_decoder_failure"
        staged=stage(self.inv,evidence)
        self.assertEqual(len(staged["logo_candidates"]),0)
        self.assertEqual(len(staged["not_qualified"]),1)
        self.assertEqual(staged["historical_station_count"],310)


if __name__ == "__main__":
    unittest.main()
