"""No-network tests for the private official artist genre evidence workflow."""
from __future__ import annotations

import copy
import datetime as dt
import json
import unittest

import artist_genre_knowledge as knowledge
import artist_genre_preflight as preflight
import registry_funnel

DAY = dt.date(2026, 11, 20)
ARTIST = {"id": "quiet-bands", "name": "QUIET BANDS", "aliases": ["QuietBands"]}
CATALOGUE = {"schemaVersion": 1, "artists": [ARTIST], "events": []}
SOURCE = {"artistId": "quiet-bands", "sourceRole": "artist_official",
          "enabled": True, "url": "https://quiet.example/music"}
SOURCES = {"schema": preflight.SOURCE_SCHEMA, "sources": [SOURCE]}
HTML = ('<script type="application/ld+json">'
        + json.dumps({"@type": "MusicGroup", "name": "QUIET BANDS",
                      "genre": ["Punk", "Hardcore Techno"]})
        + '</script>')


def check(sources=None, catalogue=None, page=HTML, actual=SOURCE["url"],
          robots=lambda url, cache: True):
    return preflight.build(
        sources or SOURCES, catalogue or CATALOGUE, DAY,
        fetch=lambda url, **kwargs: (page, actual), robots=robots, limit=6)


class OfficialArtistGenrePreflightTests(unittest.TestCase):
    def test_verified_profile_record_keeps_provenance_but_not_event_trust(self):
        report = check()
        self.assertEqual(report["artistSourcesEligible"], 1)
        self.assertEqual(report["verifiedArtistCount"], 1)
        self.assertEqual(report["reasonCounts"]["official_artist_genre_verified"], 1)
        item = report["verifiedArtists"][0]
        self.assertEqual(item["genres"], ["Punk"])
        self.assertEqual(item["sourceUrl"], SOURCE["url"])
        self.assertEqual(item["verifiedAt"], DAY.isoformat())
        self.assertFalse(item["eventDateLocationAndLineupProved"])
        self.assertIs(report["publicationAllowed"], False)
        self.assertEqual(report["approvalsProposed"], 0)

    def test_unknown_artist_and_promoter_sources_do_not_get_fetched(self):
        sources = {"schema": preflight.SOURCE_SCHEMA, "sources": [
            {**SOURCE, "artistId": "unlisted"},
            {**SOURCE, "sourceRole": "promoter_official"},
            {**SOURCE, "enabled": False},
        ]}
        report = preflight.build(
            sources, CATALOGUE, DAY, robots=lambda url, cache: True,
            fetch=lambda *a, **k: self.fail("No network allowed"))
        self.assertEqual(report["artistSourcesEligible"], 0)
        self.assertEqual(report["verifiedArtists"], [])

    def test_robots_disallow_is_not_bypassed(self):
        r = preflight.build(
            SOURCES, CATALOGUE, DAY, limit=6,
            robots=lambda url, cache: False,
            fetch=lambda *a, **k: self.fail("Robots must be respected"))
        self.assertEqual(r["verifiedArtistCount"], 0)
        self.assertEqual(r["reasonCounts"], {"robots_disallowed": 1})

    def test_genre_absent_and_redirect_are_quarantined(self):
        for page, actual in (
            ("<h1>QUIET BANDS</h1><p>punk</p>", SOURCE["url"]),
            (HTML, "https://promoter.example/music"),
            (HTML, "https://quiet.example/other"),
            ('<script type="application/ld+json">'
             '{"@type":"MusicGroup","name":"QUIET BANDS","genre":"Jazz"}'
             '</script>', SOURCE["url"]),
        ):
            with self.subTest(page=page[:30], actual=actual):
                r = check(page=page, actual=actual)
                self.assertEqual(r["verifiedArtistCount"], 0)
                self.assertEqual(r["reasonCounts"],
                                 {"profile_not_independently_proven": 1})

    def test_private_funnel_counts_verified_artist_without_granting_approval(self):
        pre = check()
        row = {"candidate": {
            "candidateId": "SECRET-ARTIST", "leadArtist": "QuietBands + NEW ACT",
            "date": "2027-05-05", "reviewBucket": "genre_unknown",
            "source": "artist_official_tour",
            "sourceUrl": "https://private.example/secret",
            "venue": "Mystery Park", "city": "Paris", "name": "QuietBands",
            "publicationAllowed": False, "reviewRequired": True,
            "possibleExistingConcert": False,
        }, "status": "pending_review", "stableObservations": 2,
           "identitySignature": "synthetic"}
        registry = {"schema": registry_funnel.REGISTRY_SCHEMA,
                    "items": {"SECRET": row}}
        approvals = {"schema": registry_funnel.APPROVALS_SCHEMA, "approvals": []}
        saved = copy.deepcopy((registry, CATALOGUE, approvals, pre))
        out = registry_funnel.build(
            registry, approvals, CATALOGUE, DAY, artist_preflight=pre)
        report = out["artistGenreKnowledge"]
        self.assertEqual(report["counts"]["officialArtistGenreVerifiedResearchLead"], 1)
        self.assertEqual(report["officialGenreVerifiedDistinctArtists"], 1)
        self.assertEqual(report["counts"]["knownArtistExactMatch"], 1)
        self.assertIs(report["publicationAllowed"], False)
        self.assertEqual(out["publicEventsTotal"], 0)
        self.assertNotIn("SECRET-ARTIST", str(report))
        self.assertNotIn("https://private.example", str(report))
        self.assertEqual((registry, CATALOGUE, approvals, pre), saved)

    def test_bad_or_expired_evidence_cannot_qualify_a_new_artist(self):
        pre = check()
        fake = copy.deepcopy(pre)
        fake["verifiedArtists"][0]["verifiedAt"] = "2025-01-01"
        reg = {"schema": "grossesondes.concert.intake.v1",
               "items": {"item": {
                   "candidate": {"reviewBucket": "genre_unknown",
                                 "date": "2027-01-01",
                                 "leadArtist": "QUIET BANDS"},
                   "status": "pending_review"}}}
        report = knowledge.private_genre_review(reg, CATALOGUE, DAY, fake)
        self.assertNotIn("officialArtistGenreVerifiedResearchLead", report["counts"])
        fake["publicationAllowed"] = True
        with self.assertRaises(ValueError):
            knowledge.private_genre_review(reg, CATALOGUE, DAY, fake)

    def test_invalid_manifest_and_forged_page_host_are_rejected(self):
        with self.assertRaises(ValueError):
            preflight.build({"sources": [SOURCE]}, CATALOGUE, DAY)
        bad = {"schema": preflight.SOURCE_SCHEMA, "sources": [
            {**SOURCE, "url": "http://quiet.example/music"}]}
        self.assertEqual(check(sources=bad)["artistSourcesEligible"], 0)


if __name__ == "__main__":
    unittest.main()
