"""Location-neutral discovery regressions: a named stage can be anywhere.

These checks do NOT grant trust to a new venue, artist or organizer. They
only prevent city-level match heuristics and the phrase 'Open Air' from
suppressing a distinct future concert before independent verification.
"""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import discover
import triage
import official_recheck
import radical_slift_tour_adapter

CATALOGUE = {
    "venues": [
        {"id": "historic-hall", "name": "Historic Hall", "city": "Paris"},
    ],
    "artists": [
        {"id": "metal-orchestra", "name": "Metal Orchestra"},
    ],
    "events": [{
        "id": "already-published", "date": "2027-04-27",
        "venueId": "historic-hall", "artistIds": ["metal-orchestra"],
        "title": "Metal Orchestra",
        "officialUrl": "https://official.example/historic-hall-concert",
    }],
}

ONE_OFF = {
    "candidateId": "synthetic:other-place",
    "source": "artist_official_tour_listing",
    "sourceUrl": "https://official.example/one-off-open-air",
    "date": "2027-04-27",
    "city": "Paris",
    "venue": "Esplanade du Parc",
    "name": "Metal Orchestra — Open Air",
    "leadArtist": "Metal Orchestra",
    "classification": ["Heavy Metal"],
}


class AnywhereConcertsSafetyTests(unittest.TestCase):
    def test_same_artist_city_and_day_at_different_named_place_is_not_held_as_duplicate(self):
        before = copy.deepcopy(CATALOGUE)
        row = discover.mark_match(dict(ONE_OFF), discover.make_known_keys(CATALOGUE))
        self.assertTrue(row["sameCityArtistCollisionAdvisory"])
        self.assertFalse(row["possibleExistingConcert"])
        classified = triage.triage(row, catalogue=CATALOGUE)
        self.assertEqual(classified["reviewBucket"], "genre_tag_review")
        self.assertEqual(classified["catalogueMatches"], [])
        self.assertFalse(classified["publicationAllowed"])
        self.assertTrue(classified["reviewRequired"])
        self.assertEqual(CATALOGUE, before)

    def test_same_named_venue_and_artist_remains_possible_duplicate(self):
        row = discover.mark_match(
            {**ONE_OFF, "venue": "Historic Hall", "name": "Metal Orchestra"},
            discover.make_known_keys(CATALOGUE))
        self.assertTrue(row["possibleExistingConcert"])
        classified = triage.triage(row, catalogue=CATALOGUE)
        self.assertEqual(classified["reviewBucket"], "possible_duplicate")
        self.assertEqual(classified["catalogueMatches"], ["already-published"])
        self.assertFalse(classified["publicationAllowed"])

    def test_same_exact_published_url_stays_blocked_even_when_place_differs(self):
        row = discover.mark_match(
            {**ONE_OFF, "sourceUrl": CATALOGUE["events"][0]["officialUrl"]},
            discover.make_known_keys(CATALOGUE))
        self.assertTrue(row["possibleExistingConcert"])
        self.assertFalse(row["sameCityArtistCollisionAdvisory"])
        self.assertFalse(triage.triage(row, catalogue=CATALOGUE)["publicationAllowed"])

    def test_missing_venue_does_not_assert_distinct_location(self):
        row = discover.mark_match(
            {k: v for k, v in ONE_OFF.items() if k != "venue"},
            discover.make_known_keys(CATALOGUE))
        self.assertTrue(row["possibleExistingConcert"])
        self.assertFalse(row["sameCityArtistCollisionAdvisory"])
        self.assertEqual(
            triage.triage(row, catalogue=CATALOGUE)["reviewBucket"],
            "possible_duplicate")

    def test_open_air_alone_is_not_a_festival_but_explicit_festival_is(self):
        reviewed = triage.triage(ONE_OFF, catalogue={"events": [], "venues": [], "artists": []})
        self.assertEqual(reviewed["reviewBucket"], "genre_tag_review")
        self.assertFalse(reviewed["publicationAllowed"])
        festival = triage.triage(
            {**ONE_OFF, "name": "Metal Orchestra Festival Open Air",
             "festivalContext": True},
            catalogue={"events": [], "venues": [], "artists": []})
        self.assertEqual(festival["reviewBucket"], "festival_overlap_review")
        self.assertFalse(festival["publicationAllowed"])

    def test_other_open_air_name_filters_only_explicit_festivals(self):
        self.assertEqual(
            official_recheck.artist_names("Metal Orchestra Open Air"),
            ["Metal Orchestra Open Air"])
        self.assertIsNone(
            official_recheck.BANNED_STATUS.search("Metal Orchestra Open Air"))
        self.assertFalse(
            radical_slift_tour_adapter.EXCLUDE_PLACE.search("Place Open Air"))
        self.assertTrue(
            radical_slift_tour_adapter.EXCLUDE_PLACE.search("Metal Festival"))
        with self.assertRaises(ValueError):
            official_recheck.artist_names("Metal Orchestra Festival")

    def test_location_is_not_authority_and_unknown_genre_stays_held(self):
        row = triage.triage(
            {**ONE_OFF, "venue": "Place publique éphémère",
             "classification": []},
            catalogue={"events": [], "venues": [], "artists": []})
        self.assertEqual(row["reviewBucket"], "genre_unknown")
        self.assertFalse(row["publicationAllowed"])
        self.assertTrue(row["reviewRequired"])


if __name__ == "__main__":
    unittest.main()
