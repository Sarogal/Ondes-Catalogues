"""Revue sans réseau du lieu exact Alcazar (adresse officielle + OSM indépendant).

Un point GPS documenté est une preuve de lieu seulement : ni séance, ni
horaire, ni public musical ne sont validés par ce registre à lui seul.
"""
import sys
from datetime import date
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_candidate_promotion import permitted, registry_location
from venue_registry import VENUES, verified_location


class AlcazarReviewedGeoTests(unittest.TestCase):
    def lead(self, venue="Bibliothèque de l'Alcazar", city="Marseille"):
        return {
            "external_id": "60187133", "collector": "opendatasoft-index",
            "title": "Éveil musical", "city": city, "venue": venue,
            "source_url": (
                "https://openagenda.com/bibliotheques-de-marseille/"
                "events/eveil-musical-9524766"
            ),
            "date_start": "2026-12-05", "date_end": "2026-12-05",
        }

    def test_exact_official_venue_has_independently_documented_point(self):
        records = [v for v in VENUES if v["city"] == "Marseille"
                   and "Bibliothèque de l'Alcazar" in v["aliases"]]
        self.assertEqual(len(records), 1)
        v = records[0]
        self.assertEqual(v["official"],
                         "https://www.marseille.fr/culture/actualites/20-ans-bibliotheque-alcazar")
        self.assertEqual(v["geo_source"], "https://mapcarta.com/N395241034")
        self.assertEqual((v["lat"], v["lng"]), (43.29897, 5.37669))
        self.assertEqual(registry_location(self.lead()), v)
        self.assertTrue(permitted(self.lead(), date(2026, 11, 11)))

    def test_similar_sounding_non_identical_venue_cannot_inherit_gps(self):
        self.assertIsNone(registry_location(self.lead(
            venue="Tramway Belsunce Alcazar")))
        self.assertIsNone(registry_location(self.lead(
            venue="Bibliothèque de l'Alcazar annexe")))
        self.assertIsNone(registry_location(self.lead(city="Lyon")))
        self.assertFalse(permitted(self.lead(
            venue="Tramway Belsunce Alcazar"), date(2026, 11, 11)))

    def test_independent_venue_gps_rejects_displacement(self):
        event = {
            "city": "Marseille", "venue": "Bibliothèque de l'Alcazar",
            "lat": 43.29897, "lng": 5.37669,
        }
        self.assertTrue(verified_location(event)[0])
        moved = dict(event, lat=43.306, lng=5.37669)
        self.assertFalse(verified_location(moved)[0])
        wrong_city = dict(event, city="Nice")
        self.assertFalse(verified_location(wrong_city)[0])

    def test_no_publication_authority_created(self):
        # Tests statiques : cette évolution ne crée aucun passage direct
        # vers une publication, ni des heures ou des âges supposés.
        venue = registry_location(self.lead())
        self.assertNotIn("date_start", venue)
        self.assertNotIn("time", venue)
        self.assertNotIn("age_min", venue)


if __name__ == "__main__":
    unittest.main()
