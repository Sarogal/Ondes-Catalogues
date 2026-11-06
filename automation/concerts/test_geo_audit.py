"""Tests hors réseau : couverture et limites de l'audit des repères Concerts."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import geo_audit as geo


class GeoAuditTests(unittest.TestCase):
    def fixture(self):
        return {
            "schemaVersion": 1, "updatedAt": "2026-11-03",
            "venues": [
                {"id": "rex", "name": "Le Rex", "city": "Toulouse",
                 "region": "Occitanie", "latitude": 43.604, "longitude": 1.444,
                 "geoPrecision": "centre de commune (position indicative, pas la salle)"},
                {"id": "known", "name": "Salle B", "city": "Brest",
                 "latitude": 48.3, "longitude": -4.4,
                 "geoPrecision": "point du bâtiment (OpenStreetMap)"},
                {"id": "missing", "name": "Salle C", "city": "Lyon",
                 "latitude": None, "longitude": None, "geoPrecision": None},
            ],
            "events": [
                {"id": "c1", "venueId": "rex"},
                {"id": "c2", "venueId": "rex"},
                {"id": "c3", "venueId": "known"},
            ],
        }

    def test_priorites_et_decompte_sans_assimiler_un_lieu_non_signale_a_une_preuve(self):
        report = geo.analyze(self.fixture())
        self.assertEqual((len(report["venues"]), report["concerts"]), (3, 3))
        self.assertEqual(report["venuesToReview"], 2)
        self.assertEqual(report["concertsWithVenuesToReview"], 2)
        self.assertEqual(report["venues"][0]["venueId"], "rex")
        self.assertEqual(report["venues"][0]["concertsAffected"], 2)
        self.assertEqual(report["venues"][1]["venueId"], "missing")
        self.assertFalse(report["venues"][-1]["requiresReview"])
        self.assertTrue(all(not v["publicationAllowed"] for v in report["venues"]))
        self.assertTrue(report["publishesNothing"])

    def test_reference_invalide_rejetee(self):
        data = self.fixture()
        data["schemaVersion"] = 2
        with self.assertRaises(ValueError):
            geo.analyze(data)
        data = self.fixture()
        data["events"].append({"id": "c1", "venueId": "known"})
        with self.assertRaises(ValueError):
            geo.analyze(data)
        data = self.fixture()
        data["events"].append({"id": "c4", "venueId": "introuvable"})
        with self.assertRaises(ValueError):
            geo.analyze(data)

    def test_precisions_inconnues_et_coordonnees_invalides(self):
        venue = {"latitude": float("nan"), "longitude": 1, "geoPrecision": "précis"}
        self.assertEqual(geo.geo_status(venue), "missing_coordinates")
        venue["latitude"] = 43
        venue["geoPrecision"] = ""
        self.assertEqual(geo.geo_status(venue), "unknown_precision")
        venue["geoPrecision"] = "salle (à recontrôler)"
        self.assertEqual(geo.geo_status(venue), "coarse_position")
        venue["geoPrecision"] = "centre indicatif du bâtiment nommé Le Trabendo"
        self.assertEqual(geo.geo_status(venue), "coarse_position")

    def test_ecrit_seulement_des_rapports_prives(self):
        with tempfile.TemporaryDirectory() as folder:
            geo.save(Path(folder), geo.analyze(self.fixture()))
            report = json.loads((Path(folder) / "geopins_audit.json").read_text(encoding="utf-8"))
            self.assertTrue((Path(folder) / "RAPPORT_GEO.md").is_file())
            self.assertTrue(report["publishesNothing"])
            self.assertEqual(report["venuesToReview"], 2)

    def test_source_externe_refusee(self):
        with self.assertRaises(ValueError):
            geo.load_live_catalogue("https://example.org/faux.json")


if __name__ == "__main__":
    unittest.main()
