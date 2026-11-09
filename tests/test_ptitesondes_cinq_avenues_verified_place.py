"""Cinq-Avenues place: independently grounded building, never a session proof."""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from ptitesondes_places import validate, assert_append_only
from ptitesondes_public_place_venues import lookup_public_venue
from ptitesondes_candidate_promotion import permitted, registry_location
from venue_registry import verified_location
from proof_text import verify_event

PATH = ROOT / "docs/ptitesondes/lieux.json"
NAME = "Bibliothèque des Cinq-Avenues"
ID = "marseille-bibliotheque-cinq-avenues"
OFFICIAL = "https://www.bmvr.marseille.fr/reseau/bibliotheques-municipales-de-marseille"
MAP = "https://mapcarta.com/fr/N2499494870"
COORDS = (43.302307, 5.396262)


def catalogue():
    return json.loads(PATH.read_text(encoding="utf-8"))


def lead():
    return {
        "collector": "opendatasoft-index", "external_id": "24285475",
        "title": "Éveil musical",
        "source_url": "https://openagenda.com/bibliotheques-de-marseille/events/eveil-musical-8687467",
        "date_start": "2026-11-27", "date_end": "2026-11-27",
        "city": "Marseille", "venue": NAME,
    }


class IndependentlyReviewedCinqAvenuesTests(unittest.TestCase):
    def test_seventh_place_has_primary_location_and_osm_point(self):
        document = catalogue()
        self.assertEqual(validate(document), 7)
        found = [p for p in document["places"] if p["id"] == ID]
        self.assertEqual(len(found), 1)
        p = found[0]
        self.assertEqual((p["lat"], p["lng"]), COORDS)
        self.assertEqual(p["address"], "5 impasse Fissiaux, 13004 Marseille")
        self.assertEqual(p["category"], "mediatheque-jeunesse")
        self.assertEqual(p["official_url"], OFFICIAL)
        self.assertEqual(p["geo_source_url"], MAP)
        self.assertIsNone(p["age_min"])
        self.assertIsNone(p["age_max"])
        self.assertTrue(p["is_publicly_accessible"])
        self.assertFalse(set(p) & {
            "date_start", "date_end", "sessions", "time", "timings"
        })

    def test_existing_six_venues_are_append_only_unchanged(self):
        after = catalogue()
        before = deepcopy(after)
        before["places"] = before["places"][:-1]
        before["updated_at"] = "2026-11-06"
        self.assertEqual(len(before["places"]), 6)
        assert_append_only(before, after)
        altered = deepcopy(after)
        altered["places"][1]["name"] = "Un autre lieu"
        with self.assertRaises(ValueError):
            assert_append_only(before, altered)

    def test_exact_place_name_and_coordinates_only(self):
        matched = lookup_public_venue("Marseille", NAME)
        self.assertIsNotNone(matched)
        self.assertEqual(matched["public_place_id"], ID)
        self.assertEqual((matched["lat"], matched["lng"]), COORDS)
        for city, venue in (
            ("Marseille", "Bibliothèque du Merlan"),
            ("Marseille", NAME + " annexe"),
            ("Marseille", NAME + " - salle temporaire"),
            ("Montpellier", NAME),
            ("Marseille", "Bibliothèque Cinq Avenues Centre")
        ):
            with self.subTest(city=city, venue=venue):
                self.assertIsNone(lookup_public_venue(city, venue))
        self.assertTrue(verified_location({
            "city": "Marseille", "venue": NAME,
            "lat": COORDS[0], "lng": COORDS[1]
        })[0])
        self.assertFalse(verified_location({
            "city": "Marseille", "venue": NAME,
            "lat": 43.33056, "lng": 5.39888
        })[0])

    def test_new_geographic_eligibility_does_not_approve_event(self):
        example = lead()
        registry = registry_location(example)
        self.assertEqual(registry["public_place_id"], ID)
        self.assertTrue(permitted(example, date(2026, 11, 9)))
        unproven = {
            "source_url": example["source_url"], "title": example["title"],
            "category": "eveil-musical",
            "date_start": example["date_start"],
            "date_end": example["date_end"], "time": "10:00",
            "city": example["city"], "venue": NAME,
            "lat": COORDS[0], "lng": COORDS[1]
        }
        with patch("proof_text.read", return_value=(
                "<html><title>Loading</title>Loading...</html>", "")):
            ok, reason = verify_event(unproven, [])
        self.assertFalse(ok)
        self.assertIn("date", reason)

    def test_invalid_source_or_inferred_age_stays_rejected(self):
        for key, value in (
            ("geo_source_url", OFFICIAL),
            ("geo_source_url", "https://untrusted.invalid/cinq-avenues"),
            ("age_min", 0),
            ("is_publicly_accessible", False),
            ("lat", 400),
        ):
            changed = catalogue()
            changed["places"][-1][key] = value
            with self.subTest(field=key), self.assertRaises(ValueError):
                validate(changed)


if __name__ == "__main__":
    unittest.main()
