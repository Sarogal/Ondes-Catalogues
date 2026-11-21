#!/usr/bin/env python3
"""Network-free safety regression for batch SHA candidate probes."""
import copy
import unittest

from probe_reconciled_public_logo_bytes import (
    candidate_urls, probe, ProbeQueueError,
)
from reconcile_legacy_logo_manifests import reconcile

ID1 = "11111111-1111-4111-8111-111111111111"
ID2 = "22222222-2222-4222-8222-222222222222"
ID3 = "33333333-3333-4333-8333-333333333333"
IMG = "https://previously-unknown-radio.example.net/artwork/identical.png"


def inventory():
    return {
        "schema_version": 1,
        "publication_allowed": False,
        "no_closed_station_list": True,
        "source": {"blob_sha": "a"*40},
        "stations": [
            {"legacy_media_id": ident, "display_name": ident,
             "primary_genre": "Punk", "homepage": "https://indie.example.org",
             "source_logo_url": "", "logo_state": "discovery_needed",
             "editorial_decision": "none", "source_position": i}
            for i, ident in enumerate((ID1, ID2))
        ],
    }


def association(ident, url):
    return {"id": ident, "url": url, "revision": 1, "sizeBytes": 25000,
            "width": 600, "height": 600}


def queue():
    return reconcile(inventory(), {
        "schema": 1, "version": 5, "entries": [
            association(ID1, IMG),
            association(ID2, IMG),  # two radio UUIDs, one byte request
            association(ID3, "https://never-seen.example.org/new-logo.png"),
        ]
    })


class ProbeTests(unittest.TestCase):
    def test_duplicate_url_is_fetched_once_without_merging_stations(self):
        calls = []
        def fake_image_probe(url):
            calls.append(url)
            return {"verified_bytes": True, "sha256": "d"*64,
                    "byte_size": 200, "width": 600, "height": 600,
                    "mime_type": "image/png", "approved_station_logo": False}
        p = probe(queue(), shard_index=0, shard_count=1,
                  network=True, image_probe=fake_image_probe)
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(p["records"]), 2)
        same = next(r for r in p["records"] if r["url"] == IMG)
        self.assertEqual(same["legacy_media_ids"], [ID1, ID2])
        self.assertTrue(p["network_enabled"])
        self.assertFalse(p["publication_allowed"])
        self.assertFalse(p["signed_catalog_created"])
        self.assertEqual(p["verified_image_bytes"], 2)
        self.assertTrue(all(r["needs_station_identity_review"] for r in p["records"]))
        self.assertTrue(all(r["publication_allowed"] is False for r in p["records"]))

    def test_offline_default_does_not_download_any_image(self):
        def fail_if_called(url):
            raise AssertionError("Network touched during offline scan")
        p = probe(queue(), shard_index=0, shard_count=1,
                  image_probe=fail_if_called)
        self.assertFalse(p["network_enabled"])
        self.assertEqual(p["verified_image_bytes"], 0)
        self.assertEqual(p["url_attempts"], 0)

    def test_new_domain_not_rejected_or_treated_as_approved(self):
        urls = candidate_urls(queue())
        self.assertIn("https://never-seen.example.org/new-logo.png", urls)
        self.assertEqual(urls["https://never-seen.example.org/new-logo.png"],
                         [ID3])

    def test_source_forgery_is_rejected_before_fetch(self):
        bad = copy.deepcopy(queue())
        bad["historical_stations"][0]["candidates"][0]["publication_allowed"] = True
        with self.assertRaises(ProbeQueueError):
            probe(bad, shard_index=0, shard_count=1, network=False)
        bad = copy.deepcopy(queue())
        bad["historical_stations"][0]["candidates"][0]["safe_public_https_candidate"] = False
        with self.assertRaises(ProbeQueueError):
            probe(bad, shard_index=0, shard_count=1, network=False)

    def test_stable_shard_partition_preserves_all_urls(self):
        q = queue()
        full = set(candidate_urls(q))
        seen = set()
        for shard in range(8):
            result = probe(q, shard_index=shard, shard_count=8)
            shard_urls = {row["url"] for row in result["records"]}
            self.assertTrue(seen.isdisjoint(shard_urls))
            seen.update(shard_urls)
        self.assertEqual(full, seen)


if __name__ == "__main__":
    unittest.main()
