"""Pure, offline alias review: existing public halls, not trusted new sites.

The 40 future unknown-site reports were audited on 20 Nov 2026. Multiple
artist listings merely omitted a French article from an existing public venue.
No event, geographical claim, unpublished venue or source host is approved by
these checks.
"""
from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import artist_tour_venue_hints as alias

EMPTY = {"schema": alias.SCHEMA, "hints": []}
PUBLIC = {
    "artists": [],
    "venues": [
        {"id": "l-aeronef-lille", "name": "L’Aéronef", "city": "Lille"},
        {"id": "le-trianon-paris", "name": "Le Trianon", "city": "Paris"},
        {"id": "le-tetris-le-havre", "name": "Le Tetris", "city": "Le Havre"},
        {"id": "la-laiterie-strasbourg", "name": "La Laiterie", "city": "Strasbourg"},
        {"id": "le-rocher-de-palmer-cenon", "name": "Le Rocher de Palmer",
         "city": "Cenon"},
        {"id": "salle-cap-caval-penmarch", "name": "Salle Cap Caval",
         "city": "Penmarc'h"},
    ],
}

def lead(i, name, city):
    return {
        "candidateId": f"synthetic:{i}",
        "source": "artist_official_tour_listing",
        "venue": name, "city": city,
        "artistId": "never-important-for-article-matching",
        "date": "2027-05-10",
        "leadArtist": "Fictitious Rock Act",
        "reviewRequired": True, "publicationAllowed": False,
        "newVenueToReview": True, "venueIdIfKnown": None,
    }


class GenericExistingVenueReviewTests(unittest.TestCase):
    def test_known_name_variants_in_same_city_are_identity_only(self):
        examples = (
            ("Aéronef", "LILLE", "l-aeronef-lille"),
            ("Trianon", "PARIS", "le-trianon-paris"),
            ("Tétris", "LE HAVRE", "le-tetris-le-havre"),
            ("Laiterie", "STRASBOURG", "la-laiterie-strasbourg"),
            ("ROCHER DE PALMER", "Cenon", "le-rocher-de-palmer-cenon"),
            ("CAP CAVAL", "Penmarc'h", "salle-cap-caval-penmarch"),
            ("Aeronef", "Lille", "l-aeronef-lille"),
        )
        rows = [lead(i, name, city) for i, (name, city, _) in enumerate(examples)]
        baseline = copy.deepcopy(rows)
        mapped, hits = alias.annotate(rows, PUBLIC, EMPTY)
        self.assertEqual(len(hits), len(examples))
        self.assertEqual(rows, baseline)
        for got, (name, city, expected) in zip(mapped, examples):
            with self.subTest(name=name, city=city):
                self.assertEqual(got["venueIdIfKnown"], expected)
                self.assertFalse(got["newVenueToReview"])
                self.assertEqual(got["venue"], name)
                self.assertEqual(got["city"], city)
                self.assertEqual(got["venueReconciliation"]["status"],
                                 "catalogue_identity_review_only")
                self.assertNotIn("officialEvidenceUrl",
                                 got["venueReconciliation"])
                self.assertTrue(got["venueAddressToVerify"])
                self.assertTrue(got["coordinatesToVerify"])
                self.assertFalse(got["publicationAllowed"])
                self.assertTrue(got["reviewRequired"])
                self.assertNotIn("latitude", got)
                self.assertNotIn("longitude", got)

    def test_unknown_street_public_square_and_unseen_venue_remain_open(self):
        rows = [
            lead(0, "Place de la Tour Eiffel", "Paris"),
            lead(1, "Aéronef", "Bordeaux"),
            lead(2, "Le Douze", "Cergy"),
            lead(3, "Trianon Annexe", "Paris"),
            lead(4, "Bikini", "Toulouse"),
        ]
        out, hits = alias.annotate(rows, PUBLIC, EMPTY)
        self.assertEqual(hits, [])
        self.assertTrue(all(x["newVenueToReview"] is True for x in out))
        self.assertTrue(all(x["venueIdIfKnown"] is None for x in out))
        self.assertTrue(all(x["publicationAllowed"] is False for x in out))

    def test_homonyms_in_same_municipality_are_held(self):
        dup = copy.deepcopy(PUBLIC)
        dup["venues"].append(
            {"id": "second-aeronef", "name": "Aéronef", "city": "Lille"})
        out, hits = alias.annotate([lead(1, "Aeronef", "Lille")], dup, EMPTY)
        self.assertEqual(hits, [])
        self.assertTrue(out[0]["newVenueToReview"])
        self.assertIsNone(out[0]["venueIdIfKnown"])

    def test_article_neutralizer_is_narrow_and_deterministic(self):
        self.assertEqual(alias._article_neutral("L’Aéronef"),
                         alias._article_neutral("Aéronef"))
        self.assertEqual(alias._article_neutral("Salle Cap Caval"),
                         alias._article_neutral("Cap Caval"))
        self.assertNotEqual(alias._article_neutral("Le Trianon"),
                            alias._article_neutral("Trianon Annexe"))
        self.assertFalse(alias._article_neutral("Le A"))

    def test_real_catalogue_has_expected_stable_existing_ids(self):
        # Read repository-owned sample, no network or private registry.
        cat = json.loads((ROOT / "docs/grossesondes/concerts.json").read_text(
            encoding="utf-8"))
        cases = (
            ("Aéronef", "Lille", "l-aeronef-lille"),
            ("Trianon", "Paris", "le-trianon-paris"),
            ("Tétris", "Le Havre", "le-tetris-le-havre"),
            ("Laiterie", "Strasbourg", "la-laiterie-strasbourg"),
            ("ROCHER DE PALMER", "Cenon", "le-rocher-de-palmer-cenon"),
            ("CAP CAVAL", "Penmarc'h", "salle-cap-caval-penmarch"),
        )
        got, _ = alias.annotate(
            [lead(i, n, c) for i, (n, c, _) in enumerate(cases)],
            cat, EMPTY)
        for x, (_, _, venue_id) in zip(got, cases):
            self.assertEqual(x["venueIdIfKnown"], venue_id)
            self.assertFalse(x["publicationAllowed"])


if __name__ == "__main__":
    unittest.main()
