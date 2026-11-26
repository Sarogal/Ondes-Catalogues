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


class IndependentAcceslibreHintsTests(unittest.TestCase):
    def test_cache_is_private_optional_and_expires(self):
        from ptitesondes_acceslibre_geo_hints import load_hints
        from datetime import timedelta
        from ptitesondes_catalogue_geo_rotation import write_state
        report = scan(DOC, DAY, [ROW])
        with TemporaryDirectory() as folder:
            p = Path(folder)/"hints.json"
            self.assertEqual(load_hints(p, DAY), {})
            write_state(p, report)
            self.assertEqual(load_hints(p, DAY), report["hints"])
            self.assertEqual(load_hints(p, DAY+timedelta(days=8)), {})
            write_state(p, dict(report, publication_ready=True))
            self.assertEqual(load_hints(p, DAY), {})

    def test_live_independent_proof_required_even_with_valid_hint(self):
        from unittest.mock import patch, Mock
        from ptitesondes_acceslibre_geo_hints import independent_hint_location
        from ptitesondes_catalogue_geo_research import research_queue
        from ptitesondes_catalogue_geo_rotation import identity
        report = scan(DOC, DAY, [ROW])
        group = next(g for g in research_queue(DOC, DAY)["research_groups"]
                     if g["city"] == "Nantes")
        hint = report["hints"][identity(group)]
        reader = Mock(return_value="<html>venue</html>")
        commune = lambda _: [dict(nom="Nantes", code="44109", codeDepartement="44")]
        valid = dict(lat=47.2, lng=-1.57, official=ROW["site_internet"], geo_source="BAN + OSM")
        with patch("ptitesondes_acceslibre_geo_hints._external_location", return_value=None):
            self.assertIsNone(independent_hint_location(group, hint, html_get=reader, commune_get=commune))
        with patch("ptitesondes_acceslibre_geo_hints._external_location", return_value=valid):
            self.assertEqual(independent_hint_location(group, hint, html_get=reader, commune_get=commune)["lat"], 47.2)
            self.assertIsNone(independent_hint_location(group, hint, html_get=reader, commune_get=lambda _: []))
        with patch("ptitesondes_acceslibre_geo_hints._external_location", return_value=dict(valid, lat=48.0)):
            self.assertIsNone(independent_hint_location(group, hint, html_get=reader, commune_get=commune))

    def test_does_not_override_existing_proof_or_conflict(self):
        from unittest.mock import Mock
        from ptitesondes_acceslibre_geo_hints import hinted_researcher
        from ptitesondes_catalogue_geo_research import research_queue
        group = research_queue(DOC, DAY)["research_groups"][0]
        verify = Mock(side_effect=AssertionError("must not override"))
        for status in ("independent_venue_point_found", "independent_points_conflict"):
            old = dict(status=status, publication_ready=False)
            self.assertEqual(hinted_researcher({}, base=lambda *_: old, verify=verify)(group, DAY), old)
        verify.assert_not_called()


    def test_missing_website_is_discovered_but_still_requires_independent_recheck(self):
        from unittest.mock import Mock, patch
        from ptitesondes_acceslibre_geo_hints import independent_hint_location
        from ptitesondes_catalogue_geo_research import research_queue
        from ptitesondes_catalogue_geo_rotation import identity
        group = research_queue(DOC, DAY)["research_groups"][0]
        report = scan(DOC, DAY, [dict(ROW, site_internet="")])
        hint = report["hints"][identity(group)]
        tags = dict(name=group["venue"], website="https://theatre.example/")
        node = dict(type="node", id=1, lat=47.2, lon=-1.57, tags=tags)
        osm = Mock(return_value={"elements":[node]})
        reader = Mock(return_value="<html>venue</html>")
        commune = lambda _: [dict(nom="Nantes", code="44109", codeDepartement="44")]
        valid = dict(lat=47.2, lng=-1.57, official=ROW["site_internet"], geo_source="BAN + OSM")
        with patch("ptitesondes_acceslibre_geo_hints._external_location", return_value=valid) as proof:
            self.assertIsNotNone(independent_hint_location(group, hint, html_get=reader,
                osm_get=osm, commune_get=commune))
            proof.assert_called_once()
            reader.assert_called_once_with(ROW["site_internet"])
        with patch("ptitesondes_acceslibre_geo_hints._external_location", return_value=None):
            self.assertIsNone(independent_hint_location(group, hint, html_get=reader,
                osm_get=osm, commune_get=commune))
        for objects in ([node, dict(node, id=2)], [dict(node, tags=dict(tags, website="http://127.0.0.1"))],
                        [dict(node, tags=dict(tags, name="Another theatre"))]):
            with patch("ptitesondes_acceslibre_geo_hints._external_location") as proof:
                self.assertIsNone(independent_hint_location(group, hint, html_get=reader,
                    osm_get=lambda _: {"elements":objects}, commune_get=commune))
                proof.assert_not_called()

    def test_same_host_event_page_is_discovery_not_authorization(self):
        from unittest.mock import Mock, patch
        from ptitesondes_acceslibre_geo_hints import independent_hint_location
        from ptitesondes_catalogue_geo_research import research_queue
        from ptitesondes_catalogue_geo_rotation import identity
        group = research_queue(DOC, DAY)["research_groups"][0]
        group["source_urls"] = ["https://other.example/event", "https://theatre.example/event"]
        hint = scan(DOC, DAY, [ROW])["hints"][identity(group)]
        reader = Mock(return_value="<html>venue</html>")
        commune = lambda _: [dict(nom="Nantes", code="44109", codeDepartement="44")]
        valid = dict(lat=47.2, lng=-1.57, official=group["source_urls"][1], geo_source="BAN + OSM")
        with patch("ptitesondes_acceslibre_geo_hints._external_location", side_effect=[None, valid]):
            self.assertIsNotNone(independent_hint_location(group, hint, html_get=reader, commune_get=commune))
        self.assertEqual([c.args[0] for c in reader.call_args_list],
                         [ROW["site_internet"], group["source_urls"][1]])
