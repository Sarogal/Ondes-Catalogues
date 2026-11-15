"""Guadeloupe: audited library geometry is not approval of an outing.

Institutional venue identity/address: BnF CCFr; exact named building:
OpenStreetMap way 125054083. Each child session must still pass its own
official UID, date/time, age, organizer and duplicate checks.
"""
from datetime import date
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from ptitesondes_candidate_promotion import permitted, registry_location
from venue_registry import VENUES, verified_location

CITY = "Le Gosier"
VENUE = "Médiathèque Raoul Georges Nicolo"
LAT, LNG = 16.20547, -61.48950
INSTITUTION = "https://ccfr.bnf.fr/portailccfr/ark:/16871/0027125"
OSM_BUILDING = "https://mapcarta.com/fr/W125054083"


def dummy_lead(**overrides):
    lead = {
        "collector": "openagenda-v2",
        "external_id": "12345678",
        "title": "Fausse séance de test sans preuve indépendante",
        "source_url": "https://openagenda.com/test/events/fiche-test",
        "date_start": "2026-11-25", "date_end": "2026-11-25",
        "city": CITY, "venue": VENUE,
    }
    lead.update(overrides)
    return lead


class GosierIndependentGpsReview(unittest.TestCase):
    def test_exact_identity_and_dual_provenance(self):
        matches = [v for v in VENUES
                   if v["city"] == CITY and VENUE in v["aliases"]]
        self.assertEqual(len(matches), 1)
        place = matches[0]
        self.assertEqual((place["lat"], place["lng"]), (LAT, LNG))
        self.assertEqual((place["official"], place["geo_source"]),
                         (INSTITUTION, OSM_BUILDING))
        self.assertEqual(registry_location(dummy_lead()), place)
        self.assertTrue(permitted(dummy_lead(), date(2026, 11, 15)))
        self.assertTrue(verified_location({
            "city": CITY, "venue": VENUE, "lat": LAT, "lng": LNG
        })[0])

    def test_no_city_center_substitution_or_fuzzy_venue(self):
        for invalid in (
            dummy_lead(venue="Le Gosier"),
            dummy_lead(venue=VENUE + " annexe"),
            dummy_lead(city="Basse-Pointe"),
        ):
            with self.subTest(invalid=invalid["venue"]):
                self.assertIsNone(registry_location(invalid))
                self.assertFalse(permitted(invalid, date(2026, 11, 15)))
        self.assertFalse(verified_location({
            "city": CITY, "venue": VENUE,
            "lat": LAT + 0.002, "lng": LNG
        })[0])

    def test_gps_does_not_certify_a_children_session(self):
        place = registry_location(dummy_lead())
        self.assertFalse(set(place) & {
            "time", "age_min", "age_max", "sessions", "approved",
            "date_start", "date_end", "category",
        })
        self.assertFalse(permitted(
            dummy_lead(source_url="https://villedugosier.fr/events/test"),
            date(2026, 11, 15)))
        self.assertFalse(permitted(
            dummy_lead(date_start="2025-11-25", date_end="2025-11-25"),
            date(2026, 11, 15)))


if __name__ == "__main__":
    unittest.main()
