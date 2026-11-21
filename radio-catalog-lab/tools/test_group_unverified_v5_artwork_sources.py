#!/usr/bin/env python3
"""No-host-list offline tests for nonpublishing v5 image failure groups."""
from copy import deepcopy
import unittest
from group_unverified_v5_artwork_sources import (
    group_unverified_sources, UnverifiedSourceError,
)

IDs=[
    "11111111-1111-1111-1111-111111111111",
    "22222222-2222-2222-2222-222222222222",
    "33333333-3333-3333-3333-333333333333",
    "44444444-4444-4444-4444-444444444444",
]
URL="https://unknown-images-for-new-radio.example.net/assets/channel.png"


def fixtures():
    stations=[]
    for n,sid in enumerate(IDs):
        has_logo=n==0
        stations.append({
            "legacy_media_id":sid,
            "display_name":"Unknown metal/punk station "+str(n),
            "source_logo_url":"http://original-radio.example.net/original.png"
                              if has_logo else "",
            "homepage":"https://newradio-"+str(n)+".example.net/",
            "logo_state":"unverified_historical" if has_logo else "discovery_needed",
            "editorial_decision":"none",
        })
    inventory={
        "schema_version":1,"publication_allowed":False,
        "no_closed_station_list":True,
        "stations":stations,
    }
    rows=[]
    for n,s in enumerate(stations[:3]):
        rows.append({
            "legacy_media_id":s["legacy_media_id"],
            "station_name":s["display_name"],
            "source_url":URL if n<2 else "https://other.example.org/pic.png",
            "publication_allowed":False,
            "replace_existing_logo":False,
            "probe_verified":n==2,
            "probe_failure":"URLError" if n<2 else None,
        })
    queue={
        "scope":"GO_ARTWORK_V5_EDITORIAL_TRIAGE_ONLY",
        "publication_allowed":False,
        "signed_catalog_created":False,
        "discovery_is_open":True,
        "source_manifest_version":5,
        "summary":{"historical_manifest_associations":3},
        "historical_associations":rows,
    }
    return queue,inventory


class TestGrouping(unittest.TestCase):
    def test_unknown_host_is_accepted_without_whitelist(self):
        q,i=fixtures()
        r=group_unverified_sources(q,i)
        self.assertEqual(r["summary"]["historical_radio_count"],4)
        self.assertEqual(r["summary"]["with_public_manifest_association"],3)
        self.assertEqual(r["summary"]["without_public_manifest_association"],1)
        self.assertEqual(r["summary"]["failed_historical_associations"],2)
        self.assertEqual(r["summary"]["failed_distinct_urls"],1)
        self.assertEqual(r["summary"]["failed_source_hosts"],1)
        row=r["failed_source_groups"][0]
        self.assertEqual(row["historical_radio_count"],2)
        self.assertEqual(row["distinct_failed_image_urls"],1)
        self.assertEqual(row["no_historical_logo_url"],1)
        self.assertEqual(row["historical_logo_url_retained"],1)
        self.assertEqual(row["failure_reason_counts"],{"URLError":1})
        self.assertEqual(set(x["legacy_media_id"] for x in row["records"]),
                         set(IDs[:2]))
        self.assertTrue(all(not x["remove_existing_logo"]
                            and not x["remove_station"]
                            for x in row["records"]))
        self.assertFalse(r["publication_allowed"])
        self.assertFalse(r["signed_catalog_created"])

    def test_different_provider_and_reason_is_analyzed_without_hardcoded_hosts(self):
        q,i=fixtures()
        q["historical_associations"][2]["probe_verified"]=False
        q["historical_associations"][2]["probe_failure"]="HTTPError"
        r=group_unverified_sources(q,i)
        self.assertEqual(r["summary"]["failed_source_hosts"],2)
        self.assertEqual(r["summary"]["failed_distinct_urls"],2)

    def test_missing_manifest_radio_is_not_deleted_or_guessed(self):
        q,i=fixtures()
        r=group_unverified_sources(q,i)
        unlisted=r["historical_without_manifest_by_homepage_host"]
        self.assertEqual(sum(x["count"] for x in unlisted),1)
        self.assertEqual(unlisted[0]["records"][0]["legacy_media_id"],IDs[3])
        self.assertFalse(unlisted[0]["records"][0]["publication_allowed"])

    def test_no_manual_review_or_disallowed_publisher(self):
        q,i=fixtures()
        q["publication_allowed"]=True
        with self.assertRaises(UnverifiedSourceError):
            group_unverified_sources(q,i)

    def test_source_with_changed_historical_name_rejected(self):
        q,i=fixtures()
        q["historical_associations"][0]["station_name"]="A different radio"
        with self.assertRaises(UnverifiedSourceError):
            group_unverified_sources(q,i)

    def test_duplicate_uuid_in_review_rejected(self):
        q,i=fixtures()
        q["historical_associations"][1]["legacy_media_id"]=IDs[0]
        with self.assertRaises(UnverifiedSourceError):
            group_unverified_sources(q,i)

    def test_count_mismatch_refused(self):
        q,i=fixtures()
        q["summary"]["historical_manifest_associations"]=123
        with self.assertRaises(UnverifiedSourceError):
            group_unverified_sources(q,i)

    def test_untrusted_http_logo_candidate_refused(self):
        q,i=fixtures()
        q["historical_associations"][0]["source_url"]="http://example.net/a.jpg"
        with self.assertRaises(UnverifiedSourceError):
            group_unverified_sources(q,i)


if __name__=="__main__":
    unittest.main()
