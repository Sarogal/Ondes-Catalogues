"""Offline organizer discovery: bands NEVER need to pre-exist in public JSON."""
from __future__ import annotations

import copy
import datetime as dt
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import intake_archive
import organizer_event_discovery as discovery
import organizer_source_contract as authority
from test_organizer_first_party_unknown_bands import (
    fixture, DAY, EVENT_URL, SOURCE, ARTISTS,
)

CATALOGUE = {
    "schemaVersion": 1, "mode": "preview-public-unlisted",
    "artists": [], "venues": [], "events": [],
}


def documents():
    lead, event, cat, osm = fixture()
    html = ('<script type="application/ld+json">'
            + json.dumps(event, ensure_ascii=False)
            + '</script>')
    listing = (
        '<a href="' + EVENT_URL + '">Official upcoming show</a>'
        '<a href="https://evil.example/agenda/forged-metal/">Do not follow</a>'
        '<a href="/agenda/deeper/child/">Do not trust nested event</a>'
        '<a href="/agenda/">Not an individual event</a>'
    )
    return listing, html


class OrganizerNationalDiscoveryTests(unittest.TestCase):
    def test_unknown_artists_and_unknown_location_enter_private_review(self):
        listing, page = documents()
        calls = []
        def fetch(url, *, timeout, cap):
            calls.append(url)
            if url == SOURCE:
                return listing, SOURCE
            if url == EVENT_URL:
                return page, EVENT_URL
            raise AssertionError("No fetch may escape committed organizer")
        reports = discovery.scan(
            CATALOGUE, DAY, slot=0, max_detail=6,
            fetch=fetch, robots=lambda *_: True)
        self.assertEqual(calls, [SOURCE, EVENT_URL])
        self.assertEqual(reports["triageCounts"], {"genre_tag_review": 1})
        self.assertEqual(len(reports["candidates"]), 1)
        c = reports["candidates"][0]
        self.assertEqual(c["source"], "organizer_official_event_detail")
        self.assertEqual(c["name"], " + ".join(ARTISTS))
        self.assertEqual(c["leadArtist"], ARTISTS[0])
        self.assertTrue(c["newVenueToReview"])
        self.assertEqual(c["reviewBucket"], "genre_tag_review")
        self.assertFalse(c["publicationAllowed"])
        self.assertTrue(c["reviewRequired"])
        self.assertNotIn("artistId", c)
        self.assertEqual(CATALOGUE["artists"], [])

        # Archiving the first observation still NEVER signs a concert.
        first, first_counts = intake_archive.merge(
            {}, reports, "2026-11-20T07:20:00+00:00")
        self.assertEqual(first_counts["added"], 1)
        self.assertEqual(first["items"][c["candidateId"]]["stableObservations"], 1)
        second, second_counts = intake_archive.merge(
            first, reports, "2026-11-21T07:20:00+00:00")
        self.assertEqual(second_counts["stableReobservedOnNewDay"], 1)
        self.assertEqual(second["items"][c["candidateId"]]["stableObservations"], 2)

    def test_link_scope_is_exact_and_skips_unreviewed_hosts(self):
        spec = authority.read_sources()[0]
        listing, _ = documents()
        links = discovery.listing_urls(listing, spec)
        self.assertEqual(links, [EVENT_URL])
        for value in (None, "", 123):
            with self.subTest(value=value):
                self.assertEqual(discovery.listing_urls(str(value), spec), [])

    def test_performer_level_official_genre_is_discovered_without_event_genre(self):
        lead, raw, catalogue, osm = fixture()
        raw.pop("genre")
        for band in raw["performer"]:
            band["genre"] = "Black Metal" if band["name"] == ARTISTS[0] else "Jazz"
        result = discovery.candidate(
            raw, authority.read_sources()[0], EVENT_URL, CATALOGUE, DAY)
        self.assertIsNotNone(result)
        self.assertEqual(result["classification"], ["Black Metal", "Jazz"])
        self.assertEqual(result["genreEvidenceScope"],
                         "official_artist_in_event_detail")
        rows, _, buckets = __import__("triage").classify([result], CATALOGUE)
        self.assertEqual(buckets, {"genre_tag_review": 1})
        self.assertEqual(rows[0]["leadArtist"], ARTISTS[0])
        # A genre on an adjacent Event or a generic venue menu is not evidence.
        for band in raw["performer"]:
            band.pop("genre")
        self.assertEqual(discovery.candidate(
            raw, authority.read_sources()[0], EVENT_URL, CATALOGUE, DAY
        )["classification"], [])

    def test_source_redirect_is_held_before_detail_network(self):
        listing, page = documents()
        calls = []
        def fetch(url, *, timeout, cap):
            calls.append(url)
            return listing, "https://unreviewed.example/agenda/"
        reports = discovery.scan(
            CATALOGUE, DAY, slot=1, max_detail=6,
            fetch=fetch, robots=lambda *_: True)
        self.assertEqual(calls, [SOURCE])
        self.assertEqual(reports["candidates"], [])
        self.assertEqual(reports["sourceChecks"][0]["status"],
                         "held_source_unavailable")

    def test_unverified_performer_is_not_created_from_event_title(self):
        listing, page = documents()
        raw = json.loads(page.split('>', 1)[1].split("</script>", 1)[0])
        raw.pop("performer")
        empty = ('<script type="application/ld+json">'
                 + json.dumps(raw) + '</script>')
        def fetch(url, *, timeout, cap):
            return (listing, url) if url == SOURCE else (empty, url)
        reports = discovery.scan(
            CATALOGUE, DAY, max_detail=6, fetch=fetch,
            robots=lambda *_: True)
        self.assertEqual(reports["candidates"], [])

    def test_festival_stays_in_separate_triage_bucket(self):
        listing, page = documents()
        raw = json.loads(page.split('>', 1)[1].split("</script>", 1)[0])
        raw["name"] = "Summer Noise Festival"
        page = ('<script type="application/ld+json">'
                + json.dumps(raw) + '</script>')
        def fetch(url, *, timeout, cap):
            return (listing, url) if url == SOURCE else (page, url)
        reports = discovery.scan(
            CATALOGUE, DAY, max_detail=6, fetch=fetch,
            robots=lambda *_: True)
        self.assertEqual(reports["triageCounts"], {"festival_overlap_review": 1})
        self.assertEqual(reports["candidates"][0]["reviewBucket"],
                         "festival_overlap_review")

    def test_daily_rotation_does_not_repeat_eligible_cohorts(self):
        links = [f"{SOURCE}synthetic-concert-{i:02d}/" for i in range(28)]
        cohorts = [
            discovery.choose_urls(links, DAY, slot, 6)
            for slot in (0, 1, 2)
        ]
        self.assertEqual(sum(len(c) for c in cohorts), 18)
        self.assertEqual(len(set(x for c in cohorts for x in c)), 18)
        for invalid in (-1, 3, "1", True):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                discovery.choose_urls(links, DAY, invalid, 6)


if __name__ == "__main__":
    unittest.main()
