"""Reunion: independent geographic source for the CINOR Alain Lorraine library.

This verifies an exact building and city only. It does not validate any
specific OpenAgenda children's activity, date, age or source.
"""
from datetime import date
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_candidate_promotion import permitted, registry_location
from venue_registry import VENUES, verified_location

CITY = "Saint-Denis"
NAMES = ("Bibliothèque Intercommunale Alain Lorraine",
         "Bibliothèque Alain Lorraine")
LAT, LNG = -20.89270, 55.45130
OFFICIAL = "https://lecturepublique.cinor.org/cms/www.main.cls?surl=reseau-horaires"
OSM_BUILDING = "https://mapcarta.com/fr/W543425791"


def lead(name, **changes):
    row = {
        "collector": "openagenda-v2", "external_id": "55943123",
        "title": "Activité manuelle",
        "source_url": "https://openagenda.com/reseau-des-mediatheques-cinor/events/activite-manuelle-8019889",
        "date_start": "2026-11-18", "date_end": "2026-11-18",
        "city": CITY, "venue": name,
    }
    row.update(changes)
    return row


class CinorReunionVerifiedGeometry(unittest.TestCase):
    def test_library_has_exact_city_and_two_geographic_sources(self):
        for name in NAMES:
            with self.subTest(name=name):
                record = [v for v in VENUES
                          if v["city"] == CITY and name in v["aliases"]]
                self.assertEqual(len(record), 1)
                self.assertEqual((record[0]["lat"], record[0]["lng"]),
                                 (LAT, LNG))
                self.assertEqual((record[0]["official"], record[0]["geo_source"]),
                                 (OFFICIAL, OSM_BUILDING))
                self.assertEqual(registry_location(lead(name)), record[0])
                self.assertTrue(permitted(lead(name), date(2026, 11, 15)))
                self.assertTrue(verified_location({
                    "city": CITY, "venue": name, "lat": LAT, "lng": LNG
                })[0])

    def test_guessing_venue_or_coordinates_is_disallowed(self):
        for invalid in (
            lead("Bibliothèque de Saint-Denis"),
            lead("Bibliothèque Intercommunale Alain Lorraine annexe"),
            lead(NAMES[0], city="Le Gosier"),
        ):
            self.assertIsNone(registry_location(invalid))
            self.assertFalse(permitted(invalid, date(2026, 11, 15)))
        self.assertFalse(verified_location({
            "city": CITY, "venue": NAMES[0],
            "lat": LAT + 0.002, "lng": LNG
        })[0])

    def test_geography_does_not_approve_dates_or_ages(self):
        record = registry_location(lead(NAMES[0]))
        self.assertFalse(set(record) & {
            "time", "age_min", "age_max", "approved",
            "sessions", "date_start", "date_end",
        })
        self.assertFalse(permitted(
            lead(NAMES[0], source_url="https://example.com/fake"),
            date(2026, 11, 15)))
        self.assertFalse(permitted(
            lead(NAMES[0], date_start="2025-11-18", date_end="2025-11-18"),
            date(2026, 11, 15)))


if __name__ == "__main__":
    unittest.main()
