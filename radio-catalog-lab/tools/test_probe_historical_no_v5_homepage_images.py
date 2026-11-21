#!/usr/bin/env python3
"""Offline tests of SHA evidence for OG images without visual admission."""
import copy
import unittest

from probe_historical_no_v5_homepage_images import (
    NoV5MetaProbeError, probe_reports,
)

IMAGE="https://brand-new-radio.example.org/og-logo.jpg"


def fixtures():
    def row(uuid, images):
        return {
            "legacy_media_id":uuid,
            "station_name":"Brand new unknown radio "+uuid[0],
            "historical_homepage":"https://brand-new-radio.example.org/",
            "historical_logo_url_preserved":"http://old-radio.example.org/a.png"
                                      if uuid[0]=="1" else "",
            "publication_allowed":False,
            "replace_existing_logo":False,
            "identity_visual_approved":False,
            "image_candidates":images,
        }
    og={"url":IMAGE,"source_meta":"og:image",
        "identity_visual_approved":False,
        "publication_allowed":False,
        "verified_image_bytes":False}
    icon={**og,"url":"https://brand-new-radio.example.org/favicon.ico",
          "source_meta":"html:link-icon-unreviewed"}
    shards=[
        {"scope":"GO_HISTORICAL_NO_V5_OFFICIAL_LOGO_DISCOVERY_REVIEW_ONLY",
         "historical_total":4,"historical_with_v5":1,
         "historical_without_v5":3,"shard_index":0,"shard_count":2,
         "publication_allowed":False,"signed_catalog_created":False,
         "identity_visual_approved":False,"selected":2,
         "records":[row("11111111-1111-1111-1111-111111111111",[og,icon]),
                    row("22222222-2222-2222-2222-222222222222",[icon])]},
        {"scope":"GO_HISTORICAL_NO_V5_OFFICIAL_LOGO_DISCOVERY_REVIEW_ONLY",
         "historical_total":4,"historical_with_v5":1,
         "historical_without_v5":3,"shard_index":1,"shard_count":2,
         "publication_allowed":False,"signed_catalog_created":False,
         "identity_visual_approved":False,"selected":1,
         "records":[row("33333333-3333-3333-3333-333333333333",[og])]},
    ]
    return shards


def checked(sha="a"*64,width=512):
    return {"verified_bytes":True,"sha256":sha,
            "width":width,"height":512,"byte_size":10240,
            "mime_type":"image/jpeg","approved_station_logo":False,
            "publication_allowed":False}


class MetadataProbeTests(unittest.TestCase):
    def test_generic_favicon_never_approved_or_probed(self):
        calls=[]
        def dl(url):
            calls.append(url)
            return checked()
        d=probe_reports(fixtures(),network=True,downloader=dl)
        self.assertEqual(d["historical_missing_v5"],3)
        self.assertEqual(d["historical_scanned"],3)
        self.assertEqual(d["selected_image_references"],2)
        self.assertEqual(d["site_icons_not_downloaded"],2)
        self.assertEqual(d["distinct_image_urls_probed"],1)
        self.assertEqual(calls,[IMAGE])
        self.assertEqual(d["technical_image_valid_count"],2)
        self.assertEqual(d["image_quality_min_192_count"],2)
        self.assertFalse(d["publication_allowed"])
        self.assertFalse(d["signed_catalog_created"])
        self.assertNotEqual(d["records"][0]["legacy_media_id"],
                            d["records"][1]["legacy_media_id"])

    def test_offline_does_not_fetch(self):
        def forbidden(_):
            raise AssertionError("Offline mode may not download")
        d=probe_reports(fixtures(),network=False,downloader=forbidden)
        self.assertEqual(d["technical_image_valid_count"],0)
        self.assertEqual(d["distinct_image_urls_probed"],1)

    def test_small_technical_logo_still_requires_manual_review(self):
        d=probe_reports(fixtures(),network=True,
                        downloader=lambda _:checked(width=120))
        self.assertEqual(d["technical_image_valid_count"],2)
        self.assertEqual(d["image_quality_min_192_count"],0)
        self.assertTrue(all(r["identity_visual_approved"] is False
                            for r in d["records"]))

    def test_network_image_failure_does_not_remove_historical_url(self):
        d=probe_reports(fixtures(),network=True,downloader=lambda _:{
            "verified_bytes":False, "reason":"URLError",
            "approved_station_logo":False,"publication_allowed":False})
        self.assertEqual(d["technical_image_valid_count"],0)
        self.assertEqual(d["records"][0]["previous_logo_url_preserved"],
                         "http://old-radio.example.org/a.png")

    def test_malformed_or_duplicated_shard_is_refused(self):
        d=fixtures()
        d[1]["shard_index"]=0
        with self.assertRaises(NoV5MetaProbeError):
            probe_reports(d,network=False)

    def test_unknown_publication_state_is_refused(self):
        d=fixtures()
        d[0]["records"][0]["image_candidates"][0]["publication_allowed"]=True
        with self.assertRaises(NoV5MetaProbeError):
            probe_reports(d,network=False)

    def test_http_social_image_is_refused(self):
        d=fixtures()
        d[0]["records"][0]["image_candidates"][0]["url"]="http://private.example.org/a.jpg"
        with self.assertRaises(NoV5MetaProbeError):
            probe_reports(d,network=False)

    def test_no_probes_when_only_favicons_exist(self):
        d=fixtures()
        for shard in d:
            for row in shard["records"]:
                row["image_candidates"]=[
                    c for c in row["image_candidates"] if c["source_meta"]!="og:image"
                ]
        result=probe_reports(d,network=True,
                             downloader=lambda _: (_ for _ in ()).throw(
                                 AssertionError("Do not fetch icons")))
        self.assertEqual(result["distinct_image_urls_probed"],0)

    def test_duplicate_uuid_between_shards_fails_closed(self):
        d=fixtures()
        d[1]["records"][0]["legacy_media_id"]=d[0]["records"][0]["legacy_media_id"]
        with self.assertRaises(NoV5MetaProbeError):
            probe_reports(d,network=False)


if __name__=="__main__":
    unittest.main()
