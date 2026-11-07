"""Non-regression tests for exact official programme extraction (offline only)."""
import json
from datetime import date
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from ptitesondes_place_agenda_curated import (
    montpellier_leads, toulouse_bebes_leads, times_written, curated_leads
)
from ptitesondes_place_agenda_watch import run_watch


def sources():
    d = json.loads((ROOT / "scripts/ptitesondes_place_agenda_sources.json").read_text(encoding="utf-8"))
    return {s["id"]: s for s in d["sources"]}


def catalogue():
    return json.loads((ROOT / "docs/ptitesondes/lieux.json").read_text(encoding="utf-8"))


MONTPELLIER = """
<html><body><h1>mille formes Montpellier</h1>
<h2>Octobre 2026</h2>
<h3>Dimanche 18 octobre de 10h à 12h - Petits ateliers</h3>
<p>LA PETITE FABRIQUE DE L'ÉQUILIBRE par le Centre Balthazar</p>
<p>De 2 à 6 ans et adultes accompagnants</p>
<h2>Novembre 2026</h2>
<h3>Dimanche 8 et dimanche 22 novembre de 10h à 12h - Petits ateliers</h3>
<p>LA PETITE FABRIQUE DE L'ÉQUILIBRE par le Centre Balthazar</p>
<p>Les enfants découvrent le cirque.</p>
<p>De 2 à 6 ans &amp; adultes accompagnants</p>
<h3>Jeudi 5 et jeudi 19 novembre de 14h à 15h30</h3>
<p>PETITS CHANTS PRÉNATAUX avec la musicienne</p>
<p>Pour les adultes et l'enfant à venir</p>
<h3>Mercredi 18 novembre : CARTE BLANCHE AU FESTIVAL DE L'EVEIL</h3>
<p>OPERA BUISSONNIER à 10h et à 11h par la Compagnie Ostara</p>
<p>De 1 an à 6 ans et adultes accompagnants</p>
<h2>Décembre 2026</h2>
<h3>Samedi 12 décembre à 11h - Petit spectacle</h3>
<p>LA CLEF DES SONGES par Compagnie Bouillonne</p>
<p>De 2 à 6 ans et adultes accompagnants</p>
<h3>Samedi 19 décembre et dimanche 20 décembre à 10h30</h3>
<p>CABARET BEBE SOUS LA NEIGE - À voir ensemble</p>
<p>De 6 mois à 3 ans &amp; adultes accompagnants</p>
<h3>Vendredi 25 décembre de 10h à 18h - Ouverture habituelle</h3>
<p>Ouverture du centre et de la galerie</p>
<p>De 0 à 6 ans et adultes accompagnants</p>
</body></html>
"""

TOULOUSE = """
<html><body>
<h1>Les bébés explorateurs : formes et matières</h1>
<ul><li>7 → 21 novembre 2026</li><li>Gratuit sur inscription</li>
<li>Museum de Toulouse, centre-ville</li></ul>
<p>Horaires</p>
<p>novembre 2026 samedi 7 10:30 - 11:00 samedi 21 10:30 - 11:00</p>
<p>Lecture pour les 0-3 ans à la médiathèque jeunesse du Muséum.</p>
<h2>Dates et horaires :</h2>
<p>samedis 7 et 21 novembre de 10h30 à 11h</p>
<h2>+ d'infos :</h2>
<p>de 0 à 3 ans ; gratuit ; lieu : médiathèque jeunesse "Pourquoi Pas ?"</p>
</body></html>
"""


class OfficialFamilyVenueSchedules(unittest.TestCase):
    def test_range_is_one_session_not_two(self):
        self.assertEqual(times_written("de 10h à 12h"), ["10:00"])
        self.assertEqual(times_written("à 10h et à 11h"), ["10:00", "11:00"])
        self.assertEqual(times_written("à 10h30"), ["10:30"])
        self.assertEqual(times_written("de 12h à 10h"), [])

    def test_montpellier_two_dates_plus_opera_safely(self):
        source = sources()["montpellier-mille-formes-programme"]
        leads = montpellier_leads(source, MONTPELLIER, date(2026, 11, 7))
        starts = {(e["name"], e["start"][:16]) for e in leads}
        self.assertIn(("LA PETITE FABRIQUE DE L'ÉQUILIBRE", "2026-11-08T10:00"), starts)
        self.assertIn(("LA PETITE FABRIQUE DE L'ÉQUILIBRE", "2026-11-22T10:00"), starts)
        self.assertIn(("OPERA BUISSONNIER", "2026-11-18T10:00"), starts)
        self.assertIn(("OPERA BUISSONNIER", "2026-11-18T11:00"), starts)
        self.assertNotIn(("PETITS CHANTS PRÉNATAUX", "2026-11-19T14:00"), starts)
        self.assertTrue(all(e["status"] == "requires_independent_session_proof" for e in leads))

    def test_montpellier_bad_day_and_undated_hours_rejected(self):
        source = sources()["montpellier-mille-formes-programme"]
        bad = MONTPELLIER.replace("Dimanche 8 et dimanche 22 novembre",
                                  "Lundi 8 et mardi 22 novembre")
        leads = montpellier_leads(source, bad, date(2026, 11, 7))
        self.assertFalse(any(e["name"] == "LA PETITE FABRIQUE DE L'ÉQUILIBRE"
                             for e in leads))
        self.assertFalse(any(e["name"] == "Ouverture du centre et de la galerie"
                             for e in leads))

    def test_toulouse_real_listed_days_only(self):
        source = sources()["toulouse-pourquoi-pas-bebes-explorateurs"]
        leads = toulouse_bebes_leads(source, TOULOUSE, date(2026, 11, 7))
        self.assertEqual([e["start"][:16] for e in leads],
                         ["2026-11-07T10:30", "2026-11-21T10:30"])
        self.assertEqual(len(leads), 2)
        self.assertTrue(all(e["place_id"] == source["place_id"] for e in leads))

    def test_toulouse_mismatch_location_age_or_date_is_refused(self):
        source = sources()["toulouse-pourquoi-pas-bebes-explorateurs"]
        variants = (
            TOULOUSE.replace("Pourquoi Pas ?", "Salle des fêtes"),
            TOULOUSE.replace("de 0 à 3 ans", "Adultes uniquement"),
            TOULOUSE.replace("samedi 21", "mardi 21"),
            TOULOUSE.replace("samedis 7 et 21", "samedis 7 et 22"),
            TOULOUSE.replace("21 novembre 2026", "21 novembre 2027"),
        )
        for html in variants:
            with self.subTest(html=html[:90]):
                self.assertEqual(curated_leads(source, html, date(2026, 11, 7)), [])

    def test_historical_schedule_does_not_reappear_forever(self):
        self.assertEqual(toulouse_bebes_leads(
            sources()["toulouse-pourquoi-pas-bebes-explorateurs"],
            TOULOUSE, date(2026, 12, 1)), [])

    def test_watch_outputs_private_review_candidates_not_patch(self):
        registry = {"schema": "ptitesondes.place_agenda_watch.v1",
                    "sources": [sources()["toulouse-pourquoi-pas-bebes-explorateurs"]]}
        state, report = run_watch(registry, catalogue(), getter=lambda url: TOULOUSE,
                                  today=date(2026, 11, 7))
        self.assertEqual(len(report["event_candidates"]), 2)
        self.assertEqual(report["policy"], "no_automatic_publication")
        self.assertTrue(all(x["status"] == "requires_independent_session_proof"
                            for x in report["event_candidates"]))
        self.assertNotIn("additions", report)
        self.assertEqual(len(state["fingerprints"]), 1)


if __name__ == "__main__":
    unittest.main()
