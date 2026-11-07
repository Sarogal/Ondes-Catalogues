"""No network: adversarial checks on Pacé's official Totems agenda discovery."""
from datetime import date
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from ptitesondes_place_agenda_pace import (
    detail_url, find_index_hints, detail_candidates, pace_agenda_leads,
    MAX_DETAILS_PER_CYCLE,
)
from ptitesondes_place_agenda_watch import run_watch


def source():
    registry = json.loads((ROOT / "scripts/ptitesondes_place_agenda_sources.json").read_text(encoding="utf-8"))
    return next(s for s in registry["sources"] if s["id"] == "pace-totems-official-agenda")


def catalogue():
    return json.loads((ROOT / "docs/ptitesondes/lieux.json").read_text(encoding="utf-8"))


INDEX = """<html><body>
<h1>Agenda de Pacé</h1>
<h2><a href="/evenement/bebes-lecteurs-decembre/">Bébés lecteurs</a></h2>
<p>Le 10 décembre</p><p>Totems - 12 Chemin de la Métairie - 35740 Pacé</p>
<h2><a href="https://www.ville-pace.bzh/evenement/la-bobine-des-enfants-decembre/">
La bobine des enfants</a></h2>
<h2><a href="/evenement/soiree-adultes/">Soirée adultes</a></h2>
<h2><a href="https://evil.example/evenement/bebes-lecteurs/">Bébés lecteurs</a></h2>
</body></html>"""

BABIES = """<html><body><h1>Bébés lecteurs</h1>
<p>Le 10 décembre 2026 09:30 - 10:30</p>
<p>Publié le 02/10/26</p>
<p>Activité d'éveil pour les tout-petits de 9 mois à 2 ans :
histoires, comptines et chansons.</p>
<p>Jeudi 10 décembre à 9h30 et à 10h30. Réservation conseillée.</p>
<p>Totems - 12 Chemin de la Métairie - 35740 Pacé - Pacé - 35740</p>
</body></html>"""

KIDS_MOVIE = """<html><body><h1>La bobine des enfants</h1>
<p>Le 02 décembre 2026 15:00 - 17:30</p>
<p>Projection d'un film suivie de jeux. Mercredi 2 décembre à 15h.</p>
<p>A partir de 6 ans.</p>
<p>Totems - 12 Chemin de la Métairie - 35740 Pacé - Pacé - 35740</p>
</body></html>"""


class PaceFamilyAgendaTests(unittest.TestCase):
    def test_only_exact_official_detail_paths(self):
        base = source()["url"]
        self.assertEqual(detail_url(base, "/evenement/bebes-lecteurs-decembre/"),
                         "https://www.ville-pace.bzh/evenement/bebes-lecteurs-decembre/")
        for bad in (
            "https://evil.example/evenement/bebes-lecteurs/",
            "http://www.ville-pace.bzh/evenement/bebes-lecteurs/",
            "https://www.ville-pace.bzh@evil.example/evenement/bebes-lecteurs/",
            "https://www.ville-pace.bzh/evenement/bebes-lecteurs/?token=1",
            "https://www.ville-pace.bzh/evenement/bebes-lecteurs/#preview",
            "https://www.ville-pace.bzh:8443/evenement/bebes-lecteurs/",
            "https://www.ville-pace.bzh/wp-admin/",
        ):
            with self.subTest(url=bad):
                self.assertIsNone(detail_url(base, bad))

    def test_index_only_uses_children_and_official_host(self):
        urls = find_index_hints(source()["url"], INDEX, date(2026, 11, 7))
        self.assertEqual(len(urls), 2)
        self.assertTrue(all(u.startswith("https://www.ville-pace.bzh/evenement/") for u in urls))

    def test_babies_have_two_exact_sessions_but_no_public_approval(self):
        url = "https://www.ville-pace.bzh/evenement/bebes-lecteurs-decembre/"
        leads = detail_candidates(source(), url, BABIES, date(2026, 11, 7))
        self.assertEqual({x["start"][:16] for x in leads},
                         {"2026-12-10T09:30", "2026-12-10T10:30"})
        self.assertTrue(all(x["status"] == "requires_independent_session_proof"
                            and x["place_id"] == "pace-totems" for x in leads))

    def test_children_movie_and_explicit_age(self):
        url = "https://www.ville-pace.bzh/evenement/la-bobine-des-enfants-decembre/"
        leads = detail_candidates(source(), url, KIDS_MOVIE, date(2026, 11, 7))
        self.assertEqual(len(leads), 1)
        self.assertEqual(leads[0]["start"][:16], "2026-12-02T15:00")

    def test_refuse_stale_adult_wrong_place_different_time_and_cancelled(self):
        url = "https://www.ville-pace.bzh/evenement/bebes-lecteurs-decembre/"
        cases = (
            BABIES.replace("10 décembre 2026", "10 octobre 2026"),
            BABIES.replace("9 mois à 2 ans", "à partir de 18 ans"),
            BABIES.replace("Totems - 12 Chemin de la Métairie", "Le Ponant - 12 Chemin de la Métairie"),
            BABIES.replace("09:30 - 10:30", "11:30 - 12:30"),
            BABIES.replace("Jeudi 10 décembre", "Vendredi 10 décembre"),
            BABIES.replace("Bébés lecteurs</h1>", "Bébés lecteurs (ANNULÉ)</h1>"),
            BABIES.replace("09:30 - 10:30", "09:30"),
        )
        for html in cases:
            with self.subTest(case=html[:100]):
                self.assertEqual(detail_candidates(source(), url, html, date(2026, 11, 7)), [])

    def test_discover_and_fetch_only_bounded_official_details(self):
        s = source()
        accessed = []
        def read(url):
            accessed.append(url)
            if url == s["url"]:
                return INDEX.replace("<h1>Agenda", "<h1>Totems Agenda")
            if url.endswith("/bebes-lecteurs-decembre/"):
                return BABIES
            if url.endswith("/la-bobine-des-enfants-decembre/"):
                return KIDS_MOVIE
            raise OSError("unknown URL")
        registry = {"schema": "ptitesondes.place_agenda_watch.v1", "sources": [s]}
        state, report = run_watch(registry, catalogue(), getter=read, today=date(2026, 11, 7))
        self.assertEqual(len(report["event_candidates"]), 3)
        self.assertTrue(all(x["status"] == "requires_independent_session_proof"
                            for x in report["event_candidates"]))
        self.assertLessEqual(len(accessed) - 1, MAX_DETAILS_PER_CYCLE)
        self.assertEqual(len(state["fingerprints"]), 1)

    def test_no_index_link_means_no_extra_network_call(self):
        count = 0
        def read(_):
            nonlocal count
            count += 1
            return '<h1>Totems</h1><p>Aucun nouveau rendez-vous annoncé</p>'
        self.assertEqual(pace_agenda_leads(source(), read(None), date(2026, 11, 7), read), [])
        self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
