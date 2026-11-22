"""Adversarial, fully offline tests for the private DILA coverage sweep."""
from contextlib import redirect_stdout
from datetime import date, timedelta
from io import StringIO
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_municipal_domain_coverage import coverage, main

DAY = date(2026, 11, 20)
DILA = "Direction de l'information légale et administrative (Premier ministre)"


def lead(city, venue, uid):
    return {
        "collector": "openagenda-v2", "external_id": str(uid),
        "title": "Atelier famille", "city": city, "venue": venue,
        "source_url": f"https://openagenda.com/test-agenda/events/{uid}_atelier",
        "date_start": "2026-12-10", "date_end": "2026-12-10",
    }


def backlog():
    return [
        lead("Ville-des-Bois", "Maison des enfants", 101),
        lead("Ville-des-Bois", "Maison des enfants", 102),
        lead("Ville-des-Bois", "Bibliothèque du Moulin", 103),
        lead("Village-des-Prés", "Maison des loisirs", 104),
    ]


def dila(city):
    return {"total_count": 1, "results": [{
        "nom": f"Mairie - {city}", "categorie": "SL",
        "version_type": "Publiable", "statut_de_diffusion": "true",
        "copyright": DILA,
        "url_service_public":
            "https://lannuaire.service-public.gouv.fr/occitanie/aveyron/uuid",
        "code_insee_commune": "12345",
        "pivot": json.dumps([{
            "type_service_local": "mairie",
            "code_insee_commune": ["12345"],
        }]),
        "adresse": json.dumps([{"nom_commune": city, "pays": "France"}]),
        "site_internet": json.dumps([{
            "libelle": "", "valeur": "https://www.ville-du-exemple.fr/",
        }]),
    }]}


class MunicipalDomainCoverageTests(unittest.TestCase):
    def test_preview_is_strictly_offline_and_private(self):
        forbidden = Mock(side_effect=AssertionError("network forbidden"))
        r = coverage(backlog(), DAY, dila_fetch=forbidden)
        forbidden.assert_not_called()
        self.assertEqual(r["backlog_leads_total"], 4)
        self.assertEqual(r["unknown_venue_leads"], 4)
        self.assertEqual(r["unknown_unique_venue_groups"], 3)
        self.assertEqual(r["all_unknown_municipalities"], 2)
        self.assertEqual(r["municipalities_queried"], 0)
        self.assertEqual(r["leads_in_municipalities_with_homepage"], 0)
        self.assertEqual(r["public_writes"], 0)
        self.assertFalse(r["publication_ready"])

    def test_full_live_mock_counts_venues_and_leads_but_never_approves(self):
        source = Mock(side_effect=lambda city: dila(city))
        r = coverage(backlog(), DAY, live=True, max_cities=12,
                     dila_fetch=source)
        self.assertEqual(source.call_count, 2)
        self.assertEqual(r["municipalities_with_official_homepage"], 2)
        self.assertEqual(r["venues_in_municipalities_with_homepage"], 3)
        self.assertEqual(r["leads_in_municipalities_with_homepage"], 4)
        self.assertEqual(r["venue_evidence_approved"], 0)
        self.assertEqual(r["event_sessions_approved"], 0)
        self.assertEqual(r["public_writes"], 0)
        self.assertFalse(r["publication_ready"])

    def test_one_municipality_missing_keeps_other_and_no_false_approval(self):
        def source(city):
            return (dila(city) if city == "Ville-des-Bois"
                    else {"total_count": 0, "results": []})
        r = coverage(backlog(), DAY, live=True, max_cities=12,
                     dila_fetch=source)
        self.assertEqual(r["municipalities_with_official_homepage"], 1)
        self.assertEqual(r["venues_in_municipalities_with_homepage"], 2)
        self.assertEqual(r["leads_in_municipalities_with_homepage"], 3)
        self.assertEqual(r["venue_evidence_approved"], 0)

    def test_unavailable_directory_is_not_treated_as_no_municipality(self):
        def source(city):
            if city == "Ville-des-Bois":
                raise TimeoutError("provider unavailable")
            return dila(city)
        r = coverage(backlog(), DAY, live=True, dila_fetch=source)
        self.assertEqual(r["directory_unavailable"], 1)
        self.assertEqual(r["leads_in_municipalities_with_homepage"], 1)
        self.assertEqual(r["venues_in_municipalities_with_homepage"], 1)

    def test_rotation_bounded_and_all_cities_reached(self):
        candidates = [lead(f"Ville-{index}", f"Maison-{index}", index + 100)
                      for index in range(7)]
        seen = set()
        for shift in range(7):
            r = coverage(candidates, DAY + timedelta(days=shift),
                         max_cities=2)
            self.assertEqual(len(r["private_records"]), 2)
            seen.update(x["city_private"] for x in r["private_records"])
        self.assertEqual(len(seen), 7)

    def test_invalid_configuration_or_backlog_blocks_without_network(self):
        for kwargs in ({"max_cities": 0}, {"max_cities": 61},
                       {"live": "true"}, {"dila_fetch": None}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                coverage(backlog(), DAY, **kwargs)
        with self.assertRaises(ValueError):
            coverage("not a backlog", DAY)

    def test_cli_preview_writes_only_to_private_report_and_redacts_stdout(self):
        with TemporaryDirectory() as tmp:
            folder = Path(tmp)
            src = folder / "backlog.json"
            output = folder / "coverage.json"
            src.write_text(json.dumps(backlog()), encoding="utf-8")
            stdout = StringIO()
            with patch.object(sys, "argv", [
                "program", "--private-backlog", str(src),
                "--private-report", str(output), "--day", "2026-11-20",
            ]), redirect_stdout(stdout):
                main()
            public = json.loads(stdout.getvalue())
            private = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(public["unknown_unique_venue_groups"], 3)
            self.assertNotIn("private_records", public)
            self.assertNotIn("Maison des enfants", stdout.getvalue())
            self.assertNotIn("Ville-des-Bois", stdout.getvalue())
            self.assertEqual(len(private["private_records"]), 2)
            self.assertEqual(private["public_writes"], 0)


if __name__ == "__main__":
    unittest.main()
