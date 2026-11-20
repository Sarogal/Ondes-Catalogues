"""Generic official biography evidence tests. No network or real approvals."""
import copy
import datetime as dt
import unittest

import artist_official_bio as bio
import artist_genre_preflight as preflight
import artist_genre_knowledge as knowledge

DAY = dt.date(2026, 11, 20)
SOURCE = {"artistId": "7weeks", "sourceRole": "artist_official",
          "enabled": True, "url": "https://band.example/concerts/"}
CATALOGUE = {"schemaVersion": 1,
             "artists": [{"id": "7weeks", "name": "7WEEKS",
                          "aliases": ["7Weeks"]}],
             "events": []}
TOUR = """<html><head><title>Concerts - 7WEEKS</title></head>
<nav><a href="/bio/">Bio</a><a href="/concerts/">Concerts</a></nav>
<main><h1>Tour</h1>20/11/26 – Toulouse – Le Rex</main></html>"""
BIO = """<html><head><title>Bio - 7WEEKS</title></head><body>
<main><h1>Notre parcours</h1><p>Avec son nouvel album, 7WEEKS
ouvre un nouveau chapitre et revient aux sources de leur Heavy Rock singulier.</p>
</main><footer><p>Death Metal, Hardcore Techno</p></footer></body></html>"""


class OfficialLinkedBioEvidenceTests(unittest.TestCase):
    def test_generic_same_origin_bio_discovery_and_independent_proof(self):
        link = bio.linked_official_biography(
            TOUR, SOURCE["url"], SOURCE["url"])
        self.assertEqual(link, "https://band.example/bio/")
        fact = bio.verify_official_biography(
            SOURCE, CATALOGUE, BIO, link, link, DAY)
        self.assertEqual(fact["genres"], ["Heavy Rock"])
        self.assertEqual(fact["artistId"], "7weeks")
        self.assertEqual(fact["sourceUrl"], link)
        self.assertEqual(fact["sourceTourUrl"], SOURCE["url"])
        self.assertEqual(fact["evidenceKind"],
                         "first-party-artist-visible-linked-bio")
        self.assertFalse(fact["eventDateLocationAndLineupProved"])
        self.assertIs(fact["publicationAllowed"], False)
        self.assertEqual(fact["approvalsProposed"], 0)

    def test_private_preflight_falls_back_to_one_bio_with_robots_check(self):
        calls = []
        def fetch(url, **kwargs):
            calls.append((url, kwargs["cap"]))
            if url == SOURCE["url"]:
                return TOUR, url
            if url == "https://band.example/bio/":
                return BIO, url
            self.fail("Unexpected URL")
        report = preflight.build(
            {"schema": preflight.SOURCE_SCHEMA, "sources": [SOURCE]},
            CATALOGUE, DAY, fetch=fetch,
            robots=lambda url, cache: True)
        self.assertEqual(report["verifiedArtistCount"], 1)
        self.assertEqual(report["reasonCounts"]["linked_biography_verified"], 1)
        self.assertEqual(report["reasonCounts"]["official_artist_genre_verified"], 1)
        self.assertEqual(calls, [
            (SOURCE["url"], 900000),
            ("https://band.example/bio/", 600000)])
        self.assertFalse(report["publicationAllowed"])

    def test_same_origin_and_ambiguous_bio_links_fail_closed(self):
        for href in ("https://evil.example/bio/",
                     "http://band.example/bio/",
                     "//evil.example/bio/", "https://band.example/bio/?v=1",
                     "/concerts/"):
            page = f'<a href="{href}">Bio</a>'
            self.assertIsNone(bio.linked_official_biography(
                page, SOURCE["url"], SOURCE["url"]))
        doubled = ('<a href="/bio/">Bio</a>'
                   '<a href="/about/">About</a>')
        self.assertIsNone(bio.linked_official_biography(
            doubled, SOURCE["url"], SOURCE["url"]))
        self.assertIsNone(bio.linked_official_biography(
            TOUR, SOURCE["url"], "https://evil.example/concerts/"))

    def test_redirected_biography_mismatch_is_rejected(self):
        with self.assertRaises(ValueError):
            bio.verify_official_biography(
                SOURCE, CATALOGUE, BIO, "https://band.example/other/",
                "https://band.example/bio/", DAY)
        with self.assertRaises(ValueError):
            bio.verify_official_biography(
                {**SOURCE, "sourceRole": "promoter_official"},
                CATALOGUE, BIO, "https://band.example/bio/",
                "https://band.example/bio/", DAY)

    def test_absent_identity_or_genre_never_becomes_a_proof(self):
        cases = (
            BIO.replace("Bio - 7WEEKS", "Bio - DIFFERENT ARTIST"),
            BIO.replace("7WEEKS\nouvre", "UNRELATED\nouvre"),
            BIO.replace("Heavy Rock", "Jazz"),
            BIO.replace("Heavy Rock", "Hardcore Techno"),
            BIO.replace("leur Heavy Rock", "ne joue pas du Heavy Rock"),
        )
        for page in cases:
            with self.subTest(page=page[:65]), self.assertRaises(ValueError):
                bio.verify_official_biography(
                    SOURCE, CATALOGUE, page, "https://band.example/bio/",
                    "https://band.example/bio/", DAY)

    def test_meta_only_or_unrelated_navigation_genre_never_counts(self):
        html = """<html><head><title>7WEEKS | Bio</title></head>
<nav><p>Heavy Rock</p></nav><main><p>7WEEKS are a group.</p>
<p>Another group played Death Metal last summer.</p></main></html>"""
        with self.assertRaises(ValueError):
            bio.verify_official_biography(
                SOURCE, CATALOGUE, html, "https://band.example/bio/",
                "https://band.example/bio/", DAY)

    def test_robots_denial_prevents_bio_fetch(self):
        fetched = []
        def fetch(url, **kwargs):
            fetched.append(url)
            return TOUR, url
        report = preflight.build(
            {"schema": preflight.SOURCE_SCHEMA, "sources": [SOURCE]},
            CATALOGUE, DAY, fetch=fetch,
            robots=lambda url, cache: url == SOURCE["url"])
        self.assertEqual(fetched, [SOURCE["url"]])
        self.assertEqual(report["verifiedArtistCount"], 0)
        self.assertEqual(report["reasonCounts"]["biography_robots_disallowed"], 1)

    def test_individual_bio_proof_is_counted_private_only(self):
        link = bio.linked_official_biography(TOUR, SOURCE["url"], SOURCE["url"])
        fact = bio.verify_official_biography(
            SOURCE, CATALOGUE, BIO, link, link, DAY)
        registry = {"schema": "grossesondes.concert.intake.v1",
                    "items": {"id": {
                        "status": "pending_review",
                        "candidate": {
                            "candidateId": "PRIVATE",
                            "reviewBucket": "genre_unknown",
                            "date": "2027-03-01", "leadArtist": "7WEEKS",
                        }}}}
        report = {
            "schema": "grossesondes.concert.artist-genre-source-preflight.v1",
            "verifiedArtists": [fact],
            "publicationAllowed": False, "approvalsProposed": 0,
        }
        before = copy.deepcopy((registry, report, CATALOGUE))
        out = knowledge.private_genre_review(registry, CATALOGUE, DAY, report)
        self.assertEqual(out["counts"]["officialArtistGenreVerifiedResearchLead"], 1)
        self.assertEqual(out["officialGenreVerifiedDistinctArtists"], 1)
        self.assertEqual(out["approvalsProposed"], 0)
        self.assertFalse(out["publicationAllowed"])
        self.assertNotIn("PRIVATE", str(out))
        self.assertEqual(before, (registry, report, CATALOGUE))


if __name__ == "__main__":
    unittest.main()
