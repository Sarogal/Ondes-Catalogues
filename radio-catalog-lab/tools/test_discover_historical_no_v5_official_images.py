#!/usr/bin/env python3
"""Offline regression tests: open discovery without signing or deletions."""
from copy import deepcopy
import unittest

from discover_historical_no_v5_official_images import (
    discover, NoV5DiscoveryError,
)

IDS = [f"{i:08x}-1111-1111-1111-111111111111" for i in range(1,5)]
IMAGE = "https://new-station.example.org/images/new-punk-radio.png"


def fixture():
    stations = [
        {
            "legacy_media_id": IDS[i], "display_name": "New Metal Radio "+str(i),
            "homepage": (
                "https://laut.fm/newmetal-radio" if i==1 else
                "http://new-station.example.org/" if i in (2,3) else
                "https://already-reviewed.example.org/"
            ),
            "source_logo_url":
                "http://legacy-logo.example.org/old.png" if i==2 else "",
            "logo_state":"unverified_historical" if i==2 else "discovery_needed",
            "editorial_decision":"none",
        } for i in range(4)
    ]
    inventory = {
        "schema_version":1,
        "publication_allowed":False,
        "no_closed_station_list":True,
        "stations":stations,
    }
    queue = {
        "scope":"GO_ARTWORK_V5_EDITORIAL_TRIAGE_ONLY",
        "discovery_is_open":True,"publication_allowed":False,
        "signed_catalog_created":False,"source_manifest_version":5,
        "historical_associations":[{
            "legacy_media_id":IDS[0], "publication_allowed":False,
            "source_url":"https://already-reviewed.example.org/brand.png",
        }],
    }
    return queue,inventory


def page_result(_):
    return {
        "logo_approved":False,"publication_allowed":False,
        "reason":"homepage_metadata_candidates_not_approved",
        "image_candidates":[{"url":IMAGE,"source_meta":"og:image"}],
    }


def official(slug):
    return {
        "station_slug":slug, "official_page":"https://laut.fm/"+slug,
        "official_source":"https://api.laut.fm/station/"+slug,
        "official_image":"https://assets.laut.fm/"+"a"*32,
    }


class NoV5Tests(unittest.TestCase):
    def test_open_providers_and_station_slug_without_whitelist(self):
        q,i=fixture()
        visited=[]
        def page(url):
            visited.append(url)
            return page_result(url)
        d=discover(q,i,shard_index=0,shard_count=1,network=True,
                   page_reader=page,api_reader=official)
        self.assertEqual(d["historical_total"],4)
        self.assertEqual(d["historical_with_v5"],1)
        self.assertEqual(d["historical_without_v5"],3)
        self.assertEqual(d["selected"],3)
        self.assertEqual(d["with_image_candidates"],3)
        self.assertEqual(len(visited),1,
                         "Two stations with same homepage require one request")
        entries={e["legacy_media_id"]:e for e in d["records"]}
        self.assertEqual(entries[IDS[1]]["discovery_status"],
                         "FIRST_PARTY_STATION_API_IMAGE")
        self.assertEqual(entries[IDS[2]]["discovery_status"],
                         "OFFICIAL_HOMEPAGE_METADATA_UNREVIEWED")
        self.assertTrue(entries[IDS[2]]["had_historical_logo"])
        self.assertEqual(entries[IDS[2]]["historical_logo_url_preserved"],
                         "http://legacy-logo.example.org/old.png")
        self.assertFalse(d["signed_catalog_created"])
        self.assertFalse(d["publication_allowed"])
        for record in d["records"]:
            self.assertFalse(record["publication_allowed"])
            self.assertFalse(record["replace_existing_logo"])
            self.assertTrue(all(c["verified_image_bytes"] is False
                                and c["identity_visual_approved"] is False
                                for c in record["image_candidates"]))

    def test_offline_does_not_call_network(self):
        q,i=fixture()
        def forbid(*args):
            raise AssertionError("Would have made a network request")
        d=discover(q,i,shard_index=0,shard_count=1,network=False,
                   page_reader=forbid,api_reader=forbid)
        self.assertEqual(d["selected"],3)
        self.assertEqual(d["candidate_image_refs"],0)
        self.assertTrue(all(x["discovery_status"]=="OFFLINE_NOT_REQUESTED"
                            for x in d["records"]))

    def test_missing_or_invalid_page_yields_no_guessed_logo(self):
        q,i=fixture()
        i["stations"][3]["homepage"]="http://localhost/private"
        d=discover(q,i,shard_index=0,shard_count=1,network=True,
                   page_reader=page_result,api_reader=official)
        row={r["legacy_media_id"]:r for r in d["records"]}[IDS[3]]
        self.assertEqual(row["discovery_status"],
                         "UNSAFE_OR_MISSING_HTTPS_HOMEPAGE")
        self.assertEqual(row["image_candidates"],[])

    def test_unavailable_source_does_not_delete_existing_logo(self):
        q,i=fixture()
        def failed(_):
            raise TimeoutError("test offline")
        d=discover(q,i,shard_index=0,shard_count=1,network=True,
                   page_reader=failed,api_reader=official)
        row={r["legacy_media_id"]:r for r in d["records"]}[IDS[2]]
        self.assertEqual(row["discovery_status"],"HOMEPAGE_DISCOVERY_FAILED")
        self.assertFalse(row["replace_existing_logo"])
        self.assertEqual(row["error_type"],"TimeoutError")

    def test_untrusted_official_api_slug_cannot_be_accepted(self):
        q,i=fixture()
        def misleading(_):
            return {**official("different-channel"),"station_slug":"different-channel"}
        with self.assertRaises(NoV5DiscoveryError):
            discover(q,i,shard_index=0,shard_count=1,network=True,
                     page_reader=page_result,api_reader=misleading)

    def test_missing_uuid_from_v5_is_not_renamed(self):
        q,i=fixture()
        d=discover(q,i,shard_index=0,shard_count=1,network=False)
        found={r["legacy_media_id"]:r["station_name"] for r in d["records"]}
        self.assertEqual(set(found),set(IDS[1:]))
        self.assertEqual(found[IDS[2]],"New Metal Radio 2")

    def test_unknown_or_duplicate_association_fails_closed(self):
        q,i=fixture()
        q["historical_associations"].append(deepcopy(q["historical_associations"][0]))
        with self.assertRaises(NoV5DiscoveryError):
            discover(q,i,shard_index=0,shard_count=1,network=False)
        q,i=fixture()
        q["historical_associations"][0]["legacy_media_id"]="not-an-id"
        with self.assertRaises(NoV5DiscoveryError):
            discover(q,i,shard_index=0,shard_count=1,network=False)

    def test_never_accept_publishable_queue(self):
        q,i=fixture()
        q["publication_allowed"]=True
        with self.assertRaises(NoV5DiscoveryError):
            discover(q,i,shard_index=0,shard_count=1,network=False)

    def test_bad_shards_rejected(self):
        q,i=fixture()
        for j,k in ((0,0),(-1,4),(3,3),(0,17)):
            with self.subTest(shard=(j,k)),self.assertRaises(NoV5DiscoveryError):
                discover(q,i,shard_index=j,shard_count=k,network=False)


if __name__=="__main__":
    unittest.main()
