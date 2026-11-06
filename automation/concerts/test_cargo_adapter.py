"""Offline first-party Le Cargö tests; the live site has complete ticket facts."""
import json
from pathlib import Path
import unittest

import cargo_adapter as m

TODAY = "2026-11-03"
SOURCE = {"name": "Le Cargö", "city": "Caen", "department": "14",
          "url": m.AGENDA}
URL = "https://lecargo.fr/programmation/concert/psykup-7-weeks/"
AGENDA_HTML = """<main><a href="/programmation/concert/psykup-7-weeks/">Psykup</a>
<a href="/programmation/concert/psykup-7-weeks/">Psykup duplicate</a>
<a href="/programmation/concert/fff/">FFF</a>
<a href="/programmation/atelier/fff/">Not concert</a>
<a href="https://evil.example/programmation/concert/fff/">evil</a></main>"""
DETAIL = """<html><main><h1>PSYKUP + 7 WEEKS</h1>
<div>Concert</div><p>PSYKUP</p>
<p>Machine de guerre live. Hardcore, jazz, death, funk, thrash et pop.</p>
<p>7WEEKS heavy rock. Au Hellfest en 2024 ; album de 2025.</p>
<ul><li>vendredi 13 novembre 2026</li>
<li>Club</li><li>Ouverture des portes : 20h</li>
<li>Début des concerts : 20h30</li></ul></main></html>"""
FFF = """<html><main><h1>FFF + DJ Bluff</h1><div>Concert</div>
<p>Le 31 octobre 2025, F.F.F. sortait un album. En 2026 tournée.</p>
<p>DJ Bluff : disco, pop, électro et rock.</p>
<ul><li>samedi 28 novembre 2026</li><li>Grande salle</li>
<li>Ouverture des portes : 19h30</li><li>Début des concerts : 20h30</li>
</ul></main></html>"""


class CargoTests(unittest.TestCase):
    def test_event_link_filters_and_limit(self):
        self.assertEqual(m.agenda_links(AGENDA_HTML), [
            URL, "https://lecargo.fr/programmation/concert/fff/"])
        self.assertLessEqual(len(m.selected_urls(
            [f"https://lecargo.fr/programmation/concert/event-{x}/"
             for x in range(30)], set(), TODAY, 100)), 8)
        with self.assertRaises(ValueError):
            m.agenda_links(AGENDA_HTML, "https://lecargo.fr/programmation/")
        for url in (URL+"?utm=1", "https://evil.example/programmation/concert/foo/",
                    "https://lecargo.fr/programmation/concert/"):
            self.assertIsNone(m.event_url(url))

    def test_psykup_full_date_bios_ignored_and_exact_start(self):
        c = m.candidate(DETAIL, URL, SOURCE, TODAY)
        self.assertEqual(c["date"], "2026-11-13")
        self.assertEqual(c["name"], "PSYKUP + 7 WEEKS")
        self.assertEqual(c["leadArtist"], "PSYKUP")
        self.assertEqual(c["classification"], ["Hardcore"])
        self.assertEqual(c["announcedDoorTime"], "20:00")
        self.assertEqual(c["localTime"], "20:30")
        self.assertEqual(c["timeMeaning"], "explicit_first_party_concert_start")
        self.assertTrue(c["reviewRequired"])
        self.assertFalse(c["publicationAllowed"])

    def test_fff_album_year_does_not_corrupt_event_date(self):
        c=m.candidate(FFF, "https://lecargo.fr/programmation/concert/fff/", SOURCE, TODAY)
        self.assertEqual(c["date"], "2026-11-28")
        self.assertEqual(c["name"], "FFF + DJ Bluff")
        self.assertEqual(c["announcedDoorTime"], "19:30")
        self.assertEqual(c["localTime"], "20:30")

    def test_rejects_ambiguous_or_unsubstantiated_information(self):
        bad = {
            "no_year": DETAIL.replace("13 novembre 2026", "13 novembre"),
            "bad_day": DETAIL.replace("13 novembre 2026", "31 novembre 2026"),
            "old_date": DETAIL.replace("13 novembre 2026", "13 novembre 2025"),
            "no_room": DETAIL.replace("<li>Club</li>", "<li>Salle inconnue</li>"),
            "offsite": DETAIL.replace("<li>Club</li>", "<li>Bibliothèque Auditorium Club</li>"),
            "no_doors": DETAIL.replace("Ouverture des portes :", "Horaire:"),
            "no_genre": DETAIL.replace("Hardcore, jazz, death, funk, thrash", "Jazz, electro, funk, pop").replace(
                "7WEEKS heavy rock.", "7WEEKS jazz."),
            "festival": DETAIL.replace("PSYKUP + 7 WEEKS</h1>", "PSYKUP FESTIVAL</h1>"),
        }
        for key, html in bad.items():
            with self.subTest(key=key), self.assertRaises(ValueError):
                m.candidate(html,URL,SOURCE,TODAY)
        with self.assertRaises(ValueError):
            m.candidate(DETAIL, URL, {**SOURCE,"city":"Rouen"}, TODAY)

    def test_absent_explicit_start_never_uses_door_time_as_concert_time(self):
        html = DETAIL.replace("Début des concerts :", "Infos pratiques :")
        c=m.candidate(html, URL, SOURCE, TODAY)
        self.assertEqual(c["announcedDoorTime"],"20:00")
        self.assertIsNone(c["localTime"])
        self.assertEqual(c["timeMeaning"],"unknown")

    def test_private_p1_source_only(self):
        d=json.loads((Path(__file__).resolve().parent/"sources.json").read_text(encoding="utf-8"))
        c=next(x for x in d["venues"] if x["id"]=="venue-source-019")
        self.assertEqual(c["adapter"], "cargo_official_detail_review")
        self.assertEqual(c["priority"],"P1")
        self.assertFalse(c["publish_automatically"])
        self.assertFalse(c["publicationAllowed"])
        self.assertLessEqual(c["maxDetailPagesPerRun"],8)


if __name__=="__main__":
    unittest.main()
