"""Offline contract tests for reusable artist-level music knowledge.

Only synthetic events, catalogues and official HTML. No network or approval.
"""
import copy
import datetime as dt
import json
import unittest

import artist_genre_knowledge as knowledge

DAY = dt.date(2026, 11, 20)
OFFICIAL = {
    "artistId": "one",
    "url": "https://artist.example/official",
    "sourceRole": "artist_official",
    "enabled": True,
}
CAT = {
    "schemaVersion": 1,
    "artists": [
        {"id": "one", "name": "THE FIRST", "aliases": ["The 1st"]},
        {"id": "two", "name": "NEXT ACT", "aliases": []},
        {"id": "three", "name": "FRESH GROUP", "aliases": []},
    ],
    "events": [
        {"genres": ["Death Metal"], "artistIds": ["one", "two"]},
        {"genres": ["Hardcore Techno"], "artistIds": ["three"]},
    ],
}


def page(name="THE FIRST", genre="Black Metal", kind="MusicGroup", **changes):
    node = {"@type": kind, "name": name, "genre": genre, **changes}
    return '<script type="application/ld+json">' + json.dumps(
        node, ensure_ascii=False) + '</script>'


def private_row(i, lead, **changes):
    return {"status": "pending_review", "candidate": {
        "candidateId": i, "reviewBucket": "genre_unknown",
        "leadArtist": lead, "date": "2027-01-25",
        "publicationAllowed": False, "reviewRequired": True,
        **changes,
    }}


class ArtistGenreKnowledgeTests(unittest.TestCase):
    def test_first_party_profile_reusable_proof_is_artist_scoped(self):
        c = copy.deepcopy(CAT)
        c["artists"][0]["name"] = "The First"
        result = knowledge.independently_verify_artist_profile(
            OFFICIAL, c, page(genre=["Black Metal", "Punk"]), OFFICIAL["url"], DAY)
        self.assertEqual(result["artistId"], "one")
        self.assertEqual(result["genres"], ["Black Metal", "Punk"])
        self.assertEqual(result["verifiedAt"], "2026-11-20")
        self.assertEqual(result["scope"], "individual_artist_not_event")
        self.assertIs(result["publicationAllowed"], False)
        self.assertIs(result["eventDateLocationAndLineupProved"], False)

    def test_alias_exactly_mapped_is_accepted(self):
        result = knowledge.independently_verify_artist_profile(
            OFFICIAL, CAT, page("The 1st", "Hard Rock"), OFFICIAL["url"], DAY)
        self.assertEqual(result["genres"], ["Hard Rock"])

    def test_schema_org_graph_musician_person(self):
        html = ('<script type="application/ld+json">'
                + json.dumps({"@graph": [{"@type": "WebSite", "name": "THE FIRST"},
                  {"@type": "Person", "name": "THE FIRST", "jobTitle": "Musician",
                   "genre": "Metalcore"}]}) + '</script>')
        result = knowledge.independently_verify_artist_profile(
            OFFICIAL, CAT, html, OFFICIAL["url"], DAY)
        self.assertEqual(result["genres"], ["Metalcore"])

    def test_first_party_only_and_no_redirect(self):
        for changes in (
            {"sourceRole": "promoter_official"},
            {"enabled": False},
            {"artistId": "unknown"},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                knowledge.independently_verify_artist_profile(
                    {**OFFICIAL, **changes}, CAT, page(), OFFICIAL["url"], DAY)
        for actual in ("http://artist.example/official",
                       "https://fake.example/official",
                       "https://artist.example/different",
                       "https://artist.example/official?tracking=1"):
            with self.subTest(actual=actual), self.assertRaises(ValueError):
                knowledge.independently_verify_artist_profile(
                    OFFICIAL, CAT, page(), actual, DAY)

    def test_no_implicit_event_or_biography_genre(self):
        for html in (
            '<p>Death Metal</p><h1>THE FIRST</h1>',
            page("OTHER GROUP"),
            page("THE FIRST", "Rock"),
            page("THE FIRST", "Jazz"),
            page("THE FIRST", "Hardcore Techno"),
            page("THE FIRST", "Electronic Hardcore"),
            page("THE FIRST", "Punk", "Event"),
            page("THE FIRST", "Punk", "Person"),
        ):
            with self.subTest(html=html), self.assertRaises(ValueError):
                knowledge.independently_verify_artist_profile(
                    OFFICIAL, CAT, html, OFFICIAL["url"], DAY)

    def test_two_indistinguishable_artist_nodes_must_fail_closed(self):
        html = page() + page()
        with self.assertRaises(ValueError):
            knowledge.independently_verify_artist_profile(
                OFFICIAL, CAT, html, OFFICIAL["url"], DAY)

    def test_alias_collision_must_fail_closed(self):
        changed = copy.deepcopy(CAT)
        changed["artists"][1]["aliases"].append("The 1st")
        with self.assertRaises(ValueError):
            knowledge.independently_verify_artist_profile(
                OFFICIAL, changed, page("The 1st"), OFFICIAL["url"], DAY)

    def test_read_only_review_counts_do_not_leak_private_names(self):
        registry = {"schema": "grossesondes.concert.intake.v1", "items": {
            "A": private_row("SECRET-123", "THE FIRST + SOME NEW GROUP"),
            "B": private_row("SECRET-456", "NEXT ACT"),
            "C": private_row("SECRET-789", "FRESH GROUP"),
            "D": private_row("SECRET-EXPIRED", "THE FIRST", date="2026-01-01"),
            "E": private_row("OTHER", "THE FIRST", reviewBucket="genre_tag_review"),
        }}
        saved = copy.deepcopy((registry, CAT))
        report = knowledge.private_genre_review(registry, CAT, DAY)
        self.assertEqual(report["counts"]["unknownGenreAllDates"], 4)
        self.assertEqual(report["counts"]["futureUnknownGenre"], 3)
        self.assertEqual(report["counts"]["knownArtistExactMatch"], 3)
        self.assertEqual(report["counts"]["eventGenreHintOnly"], 2)
        self.assertEqual(report["counts"]["knownArtistWithoutEventGenreHint"], 1)
        self.assertEqual(report["knownDistinctArtists"], 3)
        self.assertFalse(report["publicationAllowed"])
        self.assertEqual(report["approvalsProposed"], 0)
        self.assertIn("event-genre-hints-only", report["evidenceLevel"])
        self.assertNotIn("SECRET", str(report))
        self.assertNotIn("THE FIRST", str(report))
        self.assertEqual((registry, CAT), saved)

    def test_no_fuzzy_artist_or_untrusted_id_shortcut(self):
        registry = {"schema": "grossesondes.concert.intake.v1", "items": {
            "one": private_row("private-1", "THE FIR", artistId="one"),
            "two": private_row("private-2", "THE FIRSTNESS"),
        }}
        result = knowledge.private_genre_review(registry, CAT, DAY)
        self.assertEqual(result["counts"]["noExactKnownArtistMatch"], 2)
        self.assertNotIn("knownArtistExactMatch", result["counts"])

    def test_ambiguous_aliases_are_not_assigned(self):
        catalogue = copy.deepcopy(CAT)
        catalogue["artists"][2]["aliases"] = ["The 1st"]
        registry = {"schema": "grossesondes.concert.intake.v1", "items": {
            "one": private_row("private-1", "The 1st"),
        }}
        result = knowledge.private_genre_review(registry, catalogue, DAY)
        self.assertEqual(result["counts"]["ambiguousAliasHeld"], 1)
        self.assertEqual(result["counts"]["noExactKnownArtistMatch"], 1)
        self.assertNotIn("eventGenreHintOnly", result["counts"])

    def test_incomplete_schema_fail_closed(self):
        with self.assertRaises(ValueError):
            knowledge.private_genre_review({"items": {}}, CAT, DAY)
        with self.assertRaises(ValueError):
            knowledge.private_genre_review({"schema": "grossesondes.concert.intake.v1",
                                            "items": {"x": {"candidate": "corrupt"}}},
                                           CAT, DAY)


if __name__ == "__main__":
    unittest.main()
