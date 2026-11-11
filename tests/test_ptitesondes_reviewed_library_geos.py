"""GPS reviews for three real library backlog locations (no event approval).

The two proofs per venue document the building only. Dates, audience, official
organizer pages, and session times still need independent checks.
"""
from datetime import date
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_candidate_promotion import permitted, registry_location
from ptitesondes_public_place_venues import lookup_public_venue
from venue_registry import VENUES, verified_location


REVIEWED = (
    ("Nantes", "Médiathèque Luce Courville", 47.26184, -1.57400,
     "https://metropole.nantes.fr/lieu/mediatheque-luce-courville",
     "https://mapcarta.com/fr/W84294254"),
    ("Marseille", "Bibliothèque du Merlan", 43.33056, 5.39888,
     "https://www.marseille-tourisme.com/offres/bibliotheque-du-merlan-marseille-14eme-fr-3381351/",
     "https://mapcarta.com/fr/N1920263029"),
    ("Marseille", "Bibliothèque Saint-André", 43.35741, 5.34259,
     "https://www.marseille-tourisme.com/offres/bibliotheque-saint-andre-marseille-16eme-fr-3382594/",
     "https://tofromfrance.com/en/lieu/bibliotheque-saint-andre"),
)


def lead(city, venue):
    return {
        "external_id": "12345678",
        "collector": "openagenda-v2",
        "title": "Éveil musical", "city": city, "venue": venue,
        "source_url": "https://openagenda.com/test-events/events/fiche-test",
        "date_start": "2026-12-05", "date_end": "2026-12-05",
    }


class ReviewedLibraryGeoTests(unittest.TestCase):
    def test_exact_buildings_have_two_pinned_sources_and_coordinates(self):
        for city, venue, lat, lng, official, geographic in REVIEWED:
            with self.subTest(venue=venue):
                records = [
                    v for v in VENUES if v["city"] == city
                    and venue in v["aliases"]
                ]
                self.assertEqual(len(records), 1)
                place = records[0]
                self.assertEqual((place["lat"], place["lng"]), (lat, lng))
                self.assertEqual(place["official"], official)
                self.assertEqual(place["geo_source"], geographic)
                self.assertEqual(registry_location(lead(city, venue)), place)
                self.assertTrue(permitted(lead(city, venue), date(2026, 11, 12)))

    def test_no_guessing_on_nearby_or_similar_place(self):
        for city, venue, lat, lng, *_ in REVIEWED:
            with self.subTest(venue=venue):
                self.assertIsNone(registry_location(lead(city, venue + " annexe")))
                self.assertIsNone(registry_location(lead("Paris", venue)))
                self.assertFalse(permitted(lead(city, venue + " annexe"),
                                           date(2026, 11, 12)))
                self.assertTrue(verified_location({
                    "city": city, "venue": venue, "lat": lat, "lng": lng
                })[0])
                self.assertFalse(verified_location({
                    "city": city, "venue": venue, "lat": lat + .002, "lng": lng
                })[0])

    def test_only_geography_is_validated_not_audience_or_session(self):
        for city, venue, lat, lng, *_ in REVIEWED:
            with self.subTest(venue=venue):
                record = lead(city, venue)
                self.assertFalse(permitted(dict(record, date_start="2025-01-01",
                                                date_end="2025-01-01"),
                                           date(2026, 11, 12)))
                self.assertFalse(permitted(dict(record,
                                                source_url="https://other.example/events/a"),
                                           date(2026, 11, 12)))
                # Venue entries deliberately have no age, schedule or
                # publication permission field.
                self.assertTrue(all(
                    k not in registry_location(record)
                    for k in ("age_min", "age_max", "time", "approved")
                ))

    def test_alcazar_previously_approved_public_place_not_shadowed(self):
        self.assertIsNotNone(lookup_public_venue(
            "Marseille", "Bibliothèque de l'Alcazar"))
        self.assertFalse(any(
            v["city"] == "Marseille" and
            "Bibliothèque de l'Alcazar" in v["aliases"]
            for v in VENUES
        ))


if __name__ == "__main__":
    unittest.main()
