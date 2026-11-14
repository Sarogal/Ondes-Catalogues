"""Independent GPS provenance only for three verified music/children venues.

The registry is an admission gate, not evidence of a specific date, time,
audience, musical content, or authorization to publish an event.
"""
from datetime import date
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from ptitesondes_candidate_promotion import permitted, registry_location
from proof_text import verify_event
from venue_registry import VENUES, verified_location

REVIEWED = (
    (
        "Tourcoing", "Médiathèque Andrée Chedid",
        50.72973, 3.14418,
        "https://mediatheques.tourcoing.fr/les-mediatheques/mediatheque-andree-chedid",
        "https://mapcarta.com/fr/W78512642",
    ),
    (
        "Paris", "Théâtre Mandapa",
        48.82762, 2.34518,
        "https://www.centre-mandapa.fr/infos-pratiques",
        "https://mapcarta.com/N4405707193",
    ),
    (
        "Massy", "Paul B",
        48.73090, 2.28287,
        "https://paul-b.fr/infos-pratiques/",
        "https://mapcarta.com/fr/W70691345",
    ),
)


def lead(city, venue):
    return {
        "collector": "opendatasoft-index", "external_id": "12345678",
        "title": "Spectacle enfant test - sans vérification officielle",
        "source_url": "https://openagenda.com/test/events/spectacle-enfant-test",
        "date_start": "2026-12-12", "date_end": "2026-12-12",
        "city": city, "venue": venue,
    }


class ReviewedMusicVenueGpsTests(unittest.TestCase):
    def test_each_exact_venue_has_one_official_and_one_independent_osm_source(self):
        for city, venue, lat, lng, official, geo_source in REVIEWED:
            with self.subTest(venue=venue):
                matches = [row for row in VENUES
                           if row["city"] == city and venue in row["aliases"]]
                self.assertEqual(len(matches), 1)
                entry = matches[0]
                self.assertEqual((entry["lat"], entry["lng"]), (lat, lng))
                self.assertEqual((entry["official"], entry["geo_source"]),
                                 (official, geo_source))
                self.assertEqual(registry_location(lead(city, venue)), entry)
                self.assertTrue(permitted(lead(city, venue), date(2026, 11, 14)))
                self.assertTrue(verified_location({
                    "city": city, "venue": venue, "lat": lat, "lng": lng,
                })[0])

    def test_near_names_wrong_cities_and_wrong_locations_are_rejected(self):
        for city, venue, lat, lng, *_ in REVIEWED:
            with self.subTest(venue=venue):
                for invalid in (
                    dict(lead(city, venue), city="Rouen"),
                    dict(lead(city, venue), venue="Annexe de " + venue),
                    dict(lead(city, venue), venue=venue + " bis"),
                ):
                    self.assertIsNone(registry_location(invalid))
                    self.assertFalse(permitted(invalid, date(2026, 11, 14)))
                self.assertFalse(verified_location({
                    "city": city, "venue": venue, "lat": lat + 0.002, "lng": lng,
                })[0])

    def test_the_venue_registry_does_not_issue_event_proof(self):
        for city, venue, lat, lng, *_ in REVIEWED:
            with self.subTest(venue=venue):
                entry = registry_location(lead(city, venue))
                self.assertFalse(set(entry) & {
                    "age_min", "age_max", "time", "approved", "sessions",
                    "date_start", "date_end", "category",
                })
                for invalid in (
                    dict(lead(city, venue),
                         source_url="https://other.invalid/event"),
                    dict(lead(city, venue),
                         date_start="2025-12-12", date_end="2025-12-12"),
                    dict(lead(city, venue),
                         date_end="2026-12-13"),
                ):
                    self.assertFalse(permitted(invalid, date(2026, 11, 14)))
                event = {
                    "id": "openagenda-12345678-2026-12-12",
                    "title": "Spectacle enfant test - sans preuve indépendante",
                    "category": "conte-musical",
                    "category_label": "Conte musical",
                    "date_start": "2026-12-12", "date_end": "2026-12-12",
                    "time": "10:00", "city": city, "venue": venue,
                    "lat": lat, "lng": lng, "age_min": 4,
                    "source_url": "https://openagenda.com/test/events/spectacle-enfant-test",
                }
                with patch("proof_text.read", return_value=(None, "page inaccessible")):
                    allowed, _ = verify_event(event, [])
                self.assertFalse(allowed)


if __name__ == "__main__":
    unittest.main()
