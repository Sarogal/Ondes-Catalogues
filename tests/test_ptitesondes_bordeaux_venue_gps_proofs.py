"""Bordeaux venue GPS: two independently evidenced places, never event approval.

Addresses are institutional; precise points are from OSM building/node IDs.
The existing date, audience, canonical UID and organizer-proof gates remain.
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


VENUES_REVIEWED = (
    (
        "Bordeaux", "L'Impromptu", 44.83066, -0.57144,
        "https://www.bordeaux-metropole.fr/agenda/31198327_cine-concert-sur-des-films-de-charlie-chaplin-8305480",
        "https://mapcarta.com/N13175174077",
        "31198327",
        "https://openagenda.com/arteviva/events/cine-concert-sur-des-films-de-charlie-chaplin-8305480",
        "2026-11-21",
    ),
    (
        "Bordeaux", "Bibliothèque Pierre Veilletet", 44.85744, -0.62340,
        "https://mednum.gironde.fr/site/showInfos/341",
        "https://mapcarta.com/fr/W604935301",
        "24522203",
        "https://openagenda.com/bordeaux-bibliotheques/events/24522203_rendez-vous-musical-des-3-6",
        "2026-11-21",
    ),
)


def lead(item):
    city, venue, lat, lng, official, geographic, uid, url, day = item
    return {
        "collector": "openagenda-v2", "external_id": uid,
        "title": "Événement test sans preuve de séance", "city": city,
        "venue": venue, "source_url": url,
        "date_start": day, "date_end": day,
    }


class ReviewedBordeauxVenueProofs(unittest.TestCase):
    def test_exact_identity_is_backed_by_two_pinned_sources(self):
        for item in VENUES_REVIEWED:
            city, venue, lat, lng, official, geographic, *_ = item
            with self.subTest(venue=venue):
                matches = [entry for entry in VENUES
                           if entry["city"] == city and venue in entry["aliases"]]
                self.assertEqual(len(matches), 1)
                entry = matches[0]
                self.assertEqual((entry["lat"], entry["lng"]), (lat, lng))
                self.assertEqual((entry["official"], entry["geo_source"]),
                                 (official, geographic))
                self.assertEqual(registry_location(lead(item)), entry)
                self.assertTrue(permitted(lead(item), date(2026, 11, 14)))

    def test_near_names_and_wrong_building_gps_are_not_approved(self):
        for item in VENUES_REVIEWED:
            city, venue, lat, lng, *_ = item
            with self.subTest(venue=venue):
                self.assertIsNone(registry_location(dict(
                    lead(item), venue=venue + " - annexe")))
                self.assertIsNone(registry_location(dict(
                    lead(item), city="Paris")))
                self.assertFalse(permitted(dict(
                    lead(item), venue=venue + " - annexe"),
                    date(2026, 11, 14)))
                self.assertTrue(verified_location({
                    "city": city, "venue": venue, "lat": lat, "lng": lng,
                })[0])
                self.assertFalse(verified_location({
                    "city": city, "venue": venue, "lat": lat + 0.002,
                    "lng": lng,
                })[0])

    def test_official_session_and_age_are_still_independent(self):
        for item in VENUES_REVIEWED:
            with self.subTest(venue=item[1]):
                record = registry_location(lead(item))
                self.assertFalse(set(record) & {
                    "age_min", "age_max", "time", "approved",
                    "sessions", "date_start", "date_end",
                })
                self.assertFalse(permitted(dict(
                    lead(item), source_url="https://example.org/event"),
                    date(2026, 11, 14)))
                self.assertFalse(permitted(dict(
                    lead(item), date_start="2025-11-21",
                    date_end="2025-11-21"),
                    date(2026, 11, 14)))
                event = {
                    "id": "openagenda-" + item[6] + "-" + item[8],
                    "title": "Événement test sans preuve de séance",
                    "category": "conte-musical", "category_label": "Conte musical",
                    "city": item[0], "venue": item[1], "lat": item[2],
                    "lng": item[3], "source_url": item[7],
                    "date_start": item[8], "date_end": item[8],
                    "time": "10:00", "age_min": 4, "price": "Gratuit",
                }
                with patch("proof_text.read", return_value=(None, "page inaccessible")):
                    verified, _ = verify_event(event, [])
                self.assertFalse(verified)


if __name__ == "__main__":
    unittest.main()
