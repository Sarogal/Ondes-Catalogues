import csv
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from ptitesondes_acceslibre_geo_hints import COLUMNS, scan, scan_file, _trusted_export

DAY = date(2026, 11, 26)
DOC = dict(events=[
    dict(id="a", city="Nantes", venue="Théâtre de Jeanne", department="Loire-Atlantique (44)",
         date_start="2026-12-01"),
    dict(id="b", city="Nantes", venue="Théâtre de Jeanne", department="Loire-Atlantique (44)",
         date_start="2026-12-02"),
    dict(id="c", city="Montpellier", venue="Théâtre Tabard", department="Hérault (34)",
         date_start="2026-12-01"),
])
ROW = dict(id="erp-a", name="LE THEATRE DE JEANNE", commune="Nantes",
           code_insee="44109", postal_code="44100", numero="5", voie="Rue des Salorges",
           latitude="47.2", longitude="-1.57", site_internet="https://theatre.example/")


class AcceslibreTests(unittest.TestCase):
    def test_exact_name_and_commune_with_definite_article(self):
        report = scan(DOC, DAY, [ROW, dict(ROW, id="other-city", commune="Rennes")])
        self.assertEqual(report["unique_hints"], 1)
        self.assertEqual(report["covered_missing_events"], 2)
        self.assertFalse(report["publication_ready"])
        self.assertEqual(report["public_writes"], 0)
        self.assertTrue(next(iter(report["hints"].values()))["independent_recheck_required"])

    def test_distinct_erp_or_conflicting_duplicate_is_ambiguous(self):
        for other in (dict(ROW, id="erp-b"), dict(ROW, latitude="47.3")):
            report = scan(DOC, DAY, [ROW, other])
            self.assertEqual(report["unique_hints"], 0)
            self.assertEqual(report["ambiguous_groups"], 1)

    def test_not_a_fuzzy_name_or_invalid_point(self):
        for other in (dict(ROW, name="Théâtre de Jeanne annexe"), dict(ROW, latitude="nan"),
                      dict(ROW, latitude="0", longitude="0"), dict(ROW, code_insee="34172")):
            self.assertEqual(scan(DOC, DAY, [other])["unique_hints"], 0)
        report = scan(DOC, DAY, [dict(ROW, site_internet="https://127.0.0.1/")])
        self.assertIsNone(next(iter(report["hints"].values()))["hint"]["website_hint"])

    def test_csv_semicolon_and_comma_and_bad_header(self):
        with TemporaryDirectory() as folder:
            p = Path(folder)/"export.csv"
            for delimiter in (";", ","):
                with p.open("w", encoding="utf-8-sig", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=sorted(COLUMNS), delimiter=delimiter)
                    writer.writeheader()
                    writer.writerow(ROW)
                self.assertEqual(scan_file(DOC, DAY, p)["unique_hints"], 1)
            p.write_text("name;commune\nThéâtre;Nantes\n")
            with self.assertRaises(ValueError):
                scan_file(DOC, DAY, p)

    def test_transport_boundaries(self):
        self.assertTrue(_trusted_export("https://static.data.gouv.fr/resources/file.csv"))
        for url in ("http://static.data.gouv.fr/file", "https://static.data.gouv.fr.evil.example/file",
                    "https://user@static.data.gouv.fr/file", "https://127.0.0.1/file"):
            self.assertFalse(_trusted_export(url))
