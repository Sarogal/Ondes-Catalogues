import importlib.util
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "grossesondes_ministere_discovery.py"
SPEC = importlib.util.spec_from_file_location("ministry_discovery", SCRIPT)
d = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(d)


class MinistryDiscoveryTests(unittest.TestCase):
    def test_double_bom_csv(self):
        data = ("\ufeff\ufeffNom du festival;Commune principale de déroulement;"
                "Département principal de déroulement;Sous-catégorie musique\n"
                "Heavy Metal Breizh;Pluméliau-Bieuzy;Morbihan;Métal, hard rock\n").encode()
        rows = d.read_ministry_csv(data)
        self.assertEqual(rows[0]["Nom du festival"], "Heavy Metal Breizh")

    def test_future_edition_always_unconfirmed(self):
        known = d.known_records(
            {"schema": 2, "knownFestivals": [{"name": "Hellfest", "department": "44"}]},
            {"schema": 1, "festivals": []},
        )
        rows = [
            {"Nom du festival": "Hellfest Open Air", "Commune principale de déroulement": "Clisson",
             "Code Insee commune": "44043", "Département principal de déroulement": "Loire-Atlantique",
             "Sous-catégorie musique": "Métal", "Identifiant": "x"},
            {"Nom du festival": "Metal Breizh", "Commune principale de déroulement": "Pluméliau",
             "Code Insee commune": "56173", "Département principal de déroulement": "Morbihan",
             "Sous-catégorie musique": "Métal", "Identifiant": "y"},
        ]
        report = d.discover(rows, known)
        self.assertEqual(report["candidates_found"], 2)
        self.assertEqual(report["candidates"][0]["status"], "deja_present_a_controler")
        self.assertTrue(all(not x["future_edition_confirmed"] for x in report["candidates"]))

    def test_department_insee(self):
        self.assertEqual(d.department_code({"Code Insee commune": "62164"}), "62")
        self.assertEqual(d.department_code({"Code Insee commune": "2A004"}), "2A")

    def test_invalid_schema_rejected(self):
        with self.assertRaises(ValueError):
            d.known_records({"schema": 1, "knownFestivals": []}, {"schema": 1, "festivals": []})

    def test_unexpected_csv_rejected(self):
        with self.assertRaises(ValueError):
            d.read_ministry_csv(b"name;city\nFoo;Paris\n")


if __name__ == "__main__":
    unittest.main()
