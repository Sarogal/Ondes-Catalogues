"""Tests adversariaux : un lieu public ne signe jamais une séance."""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from ptitesondes_public_place_venues import (
    PUBLIC_PLACES, approved_public_venues, lookup_public_venue,
)
from ptitesondes_candidate_promotion import permitted, registry_location
from proof_text import verify_event
from venue_registry import verified_location


class ApprovedPublicVenuesTests(unittest.TestCase):
    def test_same_official_places_are_reused_with_exact_coordinates(self):
        cases = (
            ("Marseille", "Bibliothèque de l'Alcazar", 43.2989721, 5.3766901),
            ("Marseille", "Médiathèque Salim-Hatubou", 43.3686591, 5.3520638),
            ("Pacé", "Totems", 48.1462808, -1.7739782),
        )
        for city, venue, lat, lng in cases:
            with self.subTest(city=city, venue=venue):
                matched = lookup_public_venue(city, venue)
                self.assertIsNotNone(matched)
                self.assertEqual((matched["lat"], matched["lng"]), (lat, lng))
                self.assertTrue(verified_location({
                    "city": city, "venue": venue, "lat": lat, "lng": lng,
                })[0])
                self.assertFalse(verified_location({
                    "city": city, "venue": venue, "lat": lat + .01, "lng": lng,
                })[0])

    def test_reviewed_alias_does_not_turn_into_fuzzy_matching(self):
        for venue in (
            "Bibliothèque de l'Alcazar annexe",
            "Bibliothèque de l'Alcazar — salle polyvalente",
            "L'Alcazar",
            "Bibliothèque Alcazar du Merlan",
        ):
            self.assertIsNone(lookup_public_venue("Marseille", venue))
        self.assertIsNone(lookup_public_venue("Bordeaux", "Bibliothèque de l'Alcazar"))
        self.assertIsNone(lookup_public_venue("Marseille", "Bibliothèque du Merlan"))
        self.assertIsNone(lookup_public_venue(None, "Bibliothèque de l'Alcazar"))
        self.assertIsNone(lookup_public_venue("Marseille", None))

    def test_same_openagenda_gate_can_now_examine_alcazar_dates(self):
        lead = {
            "collector": "opendatasoft-index",
            "external_id": "32333505",
            "title": "Éveil musical",
            "source_url": "https://openagenda.com/bibliotheques-de-marseille/events/eveil-musical-5030115",
            "city": "Marseille", "venue": "Bibliothèque de l'Alcazar",
            "date_start": "2026-11-18", "date_end": "2026-11-18",
        }
        self.assertEqual(registry_location(lead)["public_place_id"],
                         "marseille-bibliotheque-alcazar")
        self.assertTrue(permitted(lead, date(2026, 11, 9)))
        self.assertFalse(permitted(dict(lead, venue="Bibliothèque du Merlan"),
                                   date(2026, 11, 9)))

    def test_verified_building_cannot_verify_an_unproven_session(self):
        event = {
            "city": "Marseille", "venue": "Bibliothèque de l'Alcazar",
            "lat": 43.2989721, "lng": 5.3766901,
            "title": "Éveil musical", "date_start": "2026-11-18",
            "date_end": "2026-11-18", "time": "10:00",
            "source_url": "https://openagenda.com/bibliotheques-de-marseille/events/eveil-musical-5030115",
        }
        with patch("proof_text.read", return_value=(
                "<html><title>Loading</title>Loading...</html>", "")):
            approved, why = verify_event(event, [])
        self.assertFalse(approved)
        self.assertIn("date", why)

    def test_bad_schema_or_missing_provenance_fails_closed(self):
        source = json.loads(PUBLIC_PLACES.read_text(encoding="utf-8"))
        def check(changed):
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "lieux.json"
                path.write_text(json.dumps(changed), encoding="utf-8")
                self.assertIsNone(lookup_public_venue(
                    "Marseille", "Bibliothèque de l'Alcazar", path))
        bad = deepcopy(source)
        bad["places"][3]["geo_precision"] = "commune"
        check(bad)
        bad = deepcopy(source)
        bad["places"][3]["geo_source_url"] = bad["places"][3]["official_url"]
        check(bad)
        bad = deepcopy(source)
        bad["places"][3]["reviewed_at"] = "2035-01-01"
        check(bad)
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(approved_public_venues(
                Path(tmp) / "not-here.json"), [])

    def test_two_same_name_city_candidates_are_not_resolved_by_guess(self):
        bad = json.loads(PUBLIC_PLACES.read_text(encoding="utf-8"))
        spoof = deepcopy(bad["places"][3])
        spoof["id"] = "marseille-bibliotheque-alcazar-fake"
        spoof["name"] = "Bibliothèque de l'Alcazar"
        spoof["address"] = "60 cours Belsunce, 13001 Marseille"
        spoof["lat"] = 43.2991
        spoof["geo_source_url"] = "https://www.openstreetmap.org/node/999999"
        bad["places"].append(spoof)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lieux.json"
            path.write_text(json.dumps(bad), encoding="utf-8")
            self.assertIsNone(lookup_public_venue(
                "Marseille", "Bibliothèque de l'Alcazar", path))


if __name__ == "__main__":
    unittest.main()
