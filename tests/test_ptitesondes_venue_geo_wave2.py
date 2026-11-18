"""Offline checks for municipally identified, independently geocoded venues.

No event, organiser, audience, schedule, private decision or public release
is authorised by a matching building point.
"""
from pathlib import Path
import sys
import unittest
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from proof import meters
from venue_registry import VENUES, verified_location
from ptitesondes_candidate_promotion import registry_location

EXPECTED = {
    ("Villeurbanne", "Studio 24"): (45.757956, 4.899764),
    ("Rouen", "Bibliothèque Aretha-Franklin"): (49.431261, 1.082660),
    ("Rouen", "Bibliothèque Simone de Beauvoir"): (49.426213, 1.096972),
    ("Roubaix", "Médiathèque de Roubaix - La Grand-Plage"): (50.690508, 3.175283),
}


class VenueWave2Tests(unittest.TestCase):
    def test_exact_independently_verified_building_points(self):
        for (city, venue), (lat, lng) in EXPECTED.items():
            with self.subTest(city=city, venue=venue):
                record = registry_location({"city": city, "venue": venue})
                self.assertIsNotNone(record)
                self.assertEqual((record["lat"], record["lng"]), (lat, lng))
                allowed, message = verified_location({
                    "city": city, "venue": venue, "lat": lat, "lng": lng
                })
                self.assertTrue(allowed, message)

    def test_sources_independent_and_only_housenumber_coordinates(self):
        for (city, venue), point in EXPECTED.items():
            with self.subTest(city=city, venue=venue):
                row = registry_location({"city": city, "venue": venue})
                official = urlsplit(row["official"])
                independent = urlsplit(row["geo_source"])
                self.assertEqual(official.scheme, "https")
                self.assertEqual(independent.scheme, "https")
                self.assertNotEqual(official.hostname, independent.hostname)
                self.assertEqual(independent.hostname, "data.geopf.fr")
                self.assertIn("q=", independent.query)
                self.assertIn("limit=2", independent.query)
                self.assertLess(meters(point, (row["lat"], row["lng"])), 1)

    def test_no_wrong_city_or_similarly_named_neighbor(self):
        for (city, venue), (lat, lng) in EXPECTED.items():
            with self.subTest(city=city):
                self.assertIsNone(registry_location({
                    "city": "Autre commune", "venue": venue
                }))
                self.assertIsNone(registry_location({
                    "city": city, "venue": venue + " annexe"
                }))
                ok, _ = verified_location({
                    "city": "Autre commune", "venue": venue,
                    "lat": lat, "lng": lng
                })
                self.assertFalse(ok)

    def test_wrong_coordinates_always_blocked(self):
        for (city, venue), (lat, lng) in EXPECTED.items():
            with self.subTest(city=city):
                ok, _ = verified_location({
                    "city": city, "venue": venue,
                    "lat": lat + 0.002, "lng": lng
                })
                self.assertFalse(ok)

    def test_unproved_carvin_street_point_not_approved(self):
        # BAN returns a street centroid rather than building-level evidence
        # for Place de la Gare. Do not equate that point to L'Atelier Media.
        self.assertIsNone(registry_location({
            "city": "Carvin", "venue": "L'Atelier Media"
        }))

    def test_city_only_basse_pointe_never_becomes_a_venue(self):
        self.assertIsNone(registry_location({
            "city": "Basse-Pointe", "venue": "Basse-Pointe"
        }))

    def test_exact_aliases_unique_and_no_wildcard_enabling(self):
        for (city, venue) in EXPECTED:
            found = [v for v in VENUES
                     if v["city"] == city and venue in v["aliases"]]
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0]["aliases"], [venue])
            self.assertNotIn("*", found[0]["aliases"])

    def test_registry_validation_does_not_prove_session(self):
        # A correct building point cannot convey any missing session fields:
        # no title, day, organiser, audience or age is inferred here.
        for (city, venue) in EXPECTED:
            point = registry_location({"city": city, "venue": venue})
            self.assertNotIn("approved", point)
            self.assertNotIn("date_start", point)
            self.assertNotIn("audience", point)
            self.assertNotIn("age_min", point)
            self.assertNotIn("event", point)


if __name__ == "__main__":
    unittest.main()
