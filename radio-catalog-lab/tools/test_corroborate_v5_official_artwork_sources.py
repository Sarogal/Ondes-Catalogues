#!/usr/bin/env python3
"""No-network tests of open-world official-source evidence and UUID isolation."""
import copy
import unittest

from corroborate_v5_official_artwork_sources import (
    CorroborationError, corroborate, same_asset_path,
)

ID1 = "11111111-1111-1111-1111-111111111111"
ID2 = "22222222-2222-2222-2222-222222222222"
ID3 = "33333333-3333-3333-3333-333333333333"
SRC = "https://new-metal-channel.example.org/logo-station.png?t=640"
PATH = "https://new-metal-channel.example.org/logo-station.png?cache=1"


def fixtures():
    stations = [
        {
            "legacy_media_id": ID1, "display_name": "New Metal Channel",
            "homepage": "http://new-metal-channel.example.org/",
            "source_logo_url": "", "editorial_decision": "none",
            "logo_state": "discovery_needed",
        },
        {
            "legacy_media_id": ID2, "display_name": "unknown lautfm source",
            "homepage": "https://laut.fm/new-genre-station",
            "source_logo_url": "", "editorial_decision": "none",
            "logo_state": "discovery_needed",
        },
        {
            "legacy_media_id": ID3, "display_name": "RADIO BOB! Example",
            "homepage": "https://another-operator.example.net/station",
            "source_logo_url": "", "editorial_decision": "none",
            "logo_state": "discovery_needed",
        },
    ]
    urls = [SRC, "https://assets.laut.fm/1234567890abcdef1234567890abcdef?t=640",
            "https://agginfo.quantumcast.cloud/media/bob_image.png"]
    rows = [{
        "legacy_media_id": s["legacy_media_id"],
        "station_name": s["display_name"],
        "source_url": url, "probe_verified": True,
        "sha256": "a" * 64, "width": 600, "height": 600,
        "publication_allowed": False, "replace_existing_logo": False,
        "editorial_review_status": "IDENTITY_VISUAL_REVIEW_REQUIRED",
    } for s, url in zip(stations, urls)]
    inv = {
        "schema_version": 1, "publication_allowed": False,
        "no_closed_station_list": True,
        "source": {"blob_sha": "0123456789012345678901234567890123456789"},
        "stations": stations,
    }
    queue = {
        "scope": "GO_ARTWORK_V5_EDITORIAL_TRIAGE_ONLY",
        "publication_allowed": False, "signed_catalog_created": False,
        "discovery_is_open": True,
        "source_manifest_version": 5,
        "priority_no_initial_logo": rows,
    }
    return queue, inv


class SourceTests(unittest.TestCase):
    def test_https_exact_image_path_ignores_query_but_not_hostname(self):
        self.assertTrue(same_asset_path(SRC, PATH))
        self.assertFalse(same_asset_path(SRC,
                         "https://other.example.org/logo-station.png"))
        self.assertFalse(same_asset_path("http://new-metal-channel.example.org/logo-station.png", PATH))
        self.assertFalse(same_asset_path("https://localhost/private", PATH))

    def test_site_meta_match_not_auto_approved(self):
        queue, inv = fixtures()
        hits = []
        def page_reader(url):
            hits.append(url)
            return {
                "reason": "homepage_metadata_candidates_not_approved",
                "image_candidates": [
                    {"url": PATH, "source_meta": "og:image"},
                ],
            }
        def api_reader(slug):
            return {
                "official_image": "https://assets.laut.fm/1234567890abcdef1234567890abcdef",
                "official_page": "https://laut.fm/" + slug,
            }
        result = corroborate(queue, inv, shard_index=0, shard_count=1,
                             network=True, page_reader=page_reader,
                             api_reader=api_reader)
        by_id = {x["legacy_media_id"]: x for x in result["records"]}
        self.assertEqual(by_id[ID1]["source_status"], "HOMEPAGE_METADATA_ASSET_PATH_MATCH")
        self.assertEqual(by_id[ID2]["source_status"], "OFFICIAL_API_EXACT_ASSET_PATH")
        self.assertEqual(by_id[ID3]["source_status"], "NO_FIRST_PARTY_IMAGE_CORROBORATION")
        self.assertEqual(len(hits), 2)
        self.assertEqual(result["official_api_exact_asset_path"], 1)
        self.assertEqual(result["homepage_metadata_asset_path_matches"], 1)
        self.assertFalse(result["publication_allowed"])
        self.assertFalse(result["identity_visual_approved"])
        self.assertTrue(all(not r["identity_visual_approved"] for r in result["records"]))

    def test_other_provider_with_new_genre_needs_no_whitelist(self):
        queue, inv = fixtures()
        queue["priority_no_initial_logo"] = queue["priority_no_initial_logo"][:1]
        inv["stations"] = inv["stations"][:1]
        result = corroborate(queue, inv, shard_index=0, shard_count=1,
                             network=True,
                             page_reader=lambda _: {"reason": "homepage_no_image_metadata",
                                                    "image_candidates": []})
        self.assertEqual(result["candidate_count"], 1)
        self.assertEqual(result["records"][0]["source_status"],
                         "SAME_HOST_ONLY_NO_METADATA_MATCH")

    def test_no_network_never_calls_external_reader(self):
        queue, inv = fixtures()
        def forbidden(*_):
            raise AssertionError("Should never request external data")
        result = corroborate(queue, inv, shard_index=0, shard_count=1,
                             network=False, page_reader=forbidden,
                             api_reader=forbidden)
        self.assertEqual(result["candidate_count"], 3)
        self.assertTrue(all(x["source_status"] == "UNTESTED_NO_NETWORK"
                            for x in result["records"]))

    def test_unknown_uuid_fails_closed(self):
        queue, inv = fixtures()
        del inv["stations"][0]
        with self.assertRaises(CorroborationError):
            corroborate(queue, inv, shard_index=0, shard_count=1, network=False)

    def test_existing_historical_logo_never_reinterpreted_as_missing(self):
        queue, inv = fixtures()
        inv["stations"][0]["source_logo_url"] = "https://example.com/other.png"
        inv["stations"][0]["logo_state"] = "unverified_historical"
        with self.assertRaises(CorroborationError):
            corroborate(queue, inv, shard_index=0, shard_count=1, network=False)

    def test_publishable_queue_is_rejected(self):
        queue, inv = fixtures()
        queue["publication_allowed"] = True
        with self.assertRaises(CorroborationError):
            corroborate(queue, inv, shard_index=0, shard_count=1, network=False)

    def test_metadata_does_not_assert_identity(self):
        queue, inv = fixtures()
        def deceptive(_):
            return {"reason": "homepage_metadata_candidates_not_approved",
                    "image_candidates": [{"url": PATH, "source_meta": "og:image"}]}
        report = corroborate(queue, inv, shard_index=0, shard_count=1,
                             network=True, page_reader=deceptive,
                             api_reader=lambda _: {"official_page": "https://laut.fm/test",
                                                    "official_image": "https://assets.laut.fm/0000"})
        self.assertTrue(all(x["publication_allowed"] is False for x in report["records"]))

    def test_source_error_held_not_thrown_into_publisher(self):
        queue, inv = fixtures()
        def broken(_):
            raise TimeoutError("Fake network failure")
        report = corroborate(queue, inv, shard_index=0, shard_count=1,
                             network=True, page_reader=broken,
                             api_reader=broken)
        self.assertTrue(all(x["source_status"] in {
            "OFFICIAL_API_UNAVAILABLE", "HOMEPAGE_PROBE_FAILED"
        } for x in report["records"]))
        self.assertFalse(report["signed_catalog_created"])

    def test_pilot_review_is_skipped(self):
        queue, inv = fixtures()
        queue["priority_no_initial_logo"][0]["editorial_review_status"] = (
            "PREVIOUS_TEST_VISUAL_SHA_MATCH")
        report = corroborate(queue, inv, shard_index=0, shard_count=1,
                             network=False)
        self.assertEqual(report["candidate_count"], 2)

if __name__ == "__main__":
    unittest.main()
