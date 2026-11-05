import json
from pathlib import Path
import sys
import unittest
from copy import deepcopy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from ptitesondes_places import validate, assert_append_only


def catalogue():
    return json.loads((ROOT / "docs/ptitesondes/lieux.json").read_text(encoding="utf-8"))


class FamilyPlaceCatalogueTests(unittest.TestCase):
    def test_real_mille_formes_record_separate_from_events(self):
        j = catalogue()
        self.assertEqual(validate(j), 1)
        loc = j["places"][0]
        self.assertEqual(loc["name"], "mille formes Montpellier")
        self.assertEqual((loc["lat"], loc["lng"]), (43.60826, 3.88612))
        self.assertEqual((loc["age_min"], loc["age_max"]), (0, 6))
        self.assertEqual(loc["official_url"].split("/")[2], "www.montpellier.fr")
        self.assertEqual(loc["geo_source_url"], "https://mapcarta.com/fr/N13508792408")
        self.assertFalse(any(k in loc for k in ("date_start", "date_end", "time", "timings")))

    def test_refuse_to_invent_representations_from_opening_hours(self):
        j = catalogue()
        for field, value in (("date_start", "2026-11-05"),
                             ("date_end", "2027-02-21"),
                             ("time", "09:30"),
                             ("sessions", ["2026-11-05"])):
            modified = deepcopy(j)
            modified["places"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate(modified)

    def test_refuse_unverified_source_and_wrong_gps(self):
        j = catalogue()
        for field, value in (
            ("geo_source_url", j["places"][0]["official_url"]),
            ("geo_source_url", "https://not-reviewed.invalid/coords"),
            ("lat", 250), ("lat", None),
            ("age_max", -1), ("is_publicly_accessible", False),
            ("reviewed_at", "2024-01-01"),
            ("official_url", "http://municipality.example/info")):
            modified = deepcopy(j)
            modified["places"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate(modified)

    def test_same_venue_under_different_id_is_duplicate(self):
        j = catalogue()
        j["places"].append(dict(j["places"][0], id="doublon-mille-formes"))
        with self.assertRaisesRegex(ValueError, "déjà répertorié"):
            validate(j)

    def test_append_only_and_no_historical_mutation(self):
        original = catalogue()
        same = deepcopy(original)
        assert_append_only(original, same)
        changed = deepcopy(original)
        changed["places"][0]["name"] = "Un autre endroit"
        with self.assertRaisesRegex(ValueError, "modifié"):
            assert_append_only(original, changed)
        removed = deepcopy(original)
        removed["places"] = []
        with self.assertRaisesRegex(ValueError, "supprimé"):
            assert_append_only(original, removed)

    def test_existing_outings_catalogue_unchanged_format(self):
        original = json.loads((ROOT / "docs/ptitesondes/sorties.json").read_text(encoding="utf-8"))
        self.assertEqual(set(original), {"version", "updated_at", "events"})
        self.assertGreaterEqual(len(original["events"]), 514)
        self.assertNotIn("places", original)


if __name__ == "__main__":
    unittest.main()
