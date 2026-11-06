"""Tests offline, fail-closed, des fiches individuelles du Temps Machine."""
import json
from pathlib import Path
import unittest

import letempsmachine_adapter as m

TODAY = "2026-11-03"
SOURCE = {
    "name": "Le Temps Machine", "city": "Joué-lès-Tours",
    "department": "37", "url": m.AGENDA,
}
URL = "https://letempsmachine.com/agenda/release-party-birdstone-marave"
FIRST = """<html><head><meta property="og:title"
content="RELEASE PARTY ! BIRDSTONE + MARAVE | Le Temps Machine"/></head>
<main><article><h1>BIRDSTONE (RELEASE PARTY !) + MARAVE</h1>
<span>Rock</span><span>Scène Locale</span>
<time>jeudi 19 novembre 2026 19:30</time>
<p>Production : L'Asso - Le Temps Machine</p>
<p>Le Temps Machine, Le Club • Placement libre – Debout</p>
<p>Birdstone : rock progressif. Marave : punk.</p>
</article></main></html>"""
AGENDA = """<main><div><a href="/agenda/release-party-birdstone-marave">
BIRDSTONE + MARAVE</a><a href="/agenda/archives">Archives</a>
<a href="https://evil.example/agenda/forged">Attaque</a>
<a href="/agenda/release-party-birdstone-marave">Duplicate</a>
<a href="/agenda/nono-la-grinta-jaguarr">Nono</a></div></main>"""


class TempsMachineAdapterTests(unittest.TestCase):
    def test_agenda_query_strict_and_event_link_only(self):
        self.assertTrue(m.valid_agenda(m.AGENDA))
        self.assertTrue(m.valid_agenda(m.AGENDA+"&page=1"))
        for u in ("https://letempsmachine.com/agenda",
                  m.AGENDA+"&page=2", m.AGENDA+"&page=100",
                  m.AGENDA+"&event=all", "http://letempsmachine.com/agenda",
                  "https://evil.example/agenda?category=All&location=All",
                  m.AGENDA+"#invalid", m.AGENDA+"&page=1&page=1"):
            with self.subTest(u=u):
                self.assertFalse(m.valid_agenda(u))
        self.assertEqual(m.agenda_links(AGENDA, m.AGENDA),
                         [URL, "https://letempsmachine.com/agenda/nono-la-grinta-jaguarr"])
        with self.assertRaises(ValueError):
            m.agenda_links(AGENDA, "https://letempsmachine.com/actualites")

    def test_full_date_2026_and_invalid_dates(self):
        self.assertEqual(m.parse_day("jeudi 19 novembre 2026"), "2026-11-19")
        self.assertIsNone(m.parse_day("jeudi 19 novembre"))
        self.assertIsNone(m.parse_day("31 novembre 2026"))
        self.assertIsNone(m.parse_day("19 novembre 2026, 12 décembre 2026"))

    def test_official_release_party_correlated_genre_venue_year(self):
        row = m.candidate(FIRST, URL, SOURCE, TODAY)
        self.assertEqual(row["candidateId"],
                         "letempsmachine:2026-11-19:release-party-birdstone-marave")
        self.assertEqual((row["name"], row["date"], row["venue"], row["city"]),
                         ("BIRDSTONE (RELEASE PARTY !) + MARAVE",
                          "2026-11-19", "Le Temps Machine", "Joué-lès-Tours"))
        self.assertEqual(row["classification"], ["rock"])
        self.assertIsNone(row["localTime"])
        self.assertFalse(row["publicationAllowed"])
        self.assertTrue(row["reviewRequired"])
        self.assertTrue(row["officialDetailFound"])

    def test_never_accept_missing_year_room_genre_meta_or_foreign_domain(self):
        cases = {
            "missing_year": FIRST.replace("19 novembre 2026", "19 novembre"),
            "wrong_year": FIRST.replace("19 novembre 2026", "19 novembre 2025"),
            "missing_room": FIRST.replace("Le Temps Machine, Le Club", "Autre salle"),
            "outside_venue": FIRST.replace("Le Temps Machine, Le Club", "Hors les murs à Tours"),
            "missing_genre": FIRST.replace("<span>Rock</span>", "<span>Pop</span>"),
            "title_as_genre": FIRST.replace("<span>Rock</span>", "<span>Pop</span>").replace(
                "BIRDSTONE", "ROCK BAND"),
            "meta": FIRST.replace(" | Le Temps Machine", " | Autre Salle"),
            "canceled": FIRST.replace("BIRDSTONE (RELEASE PARTY !)", "BIRDSTONE (ANNULÉ)"),
        }
        for k, html in cases.items():
            with self.subTest(k=k), self.assertRaises(ValueError):
                m.candidate(html, URL, SOURCE, TODAY)
        with self.assertRaises(ValueError):
            m.candidate(FIRST, URL, {**SOURCE,"city":"Tours"}, TODAY)
        with self.assertRaises(ValueError):
            m.candidate(FIRST, URL+"?billet=1", SOURCE, TODAY)

    def test_rotation_dedup_and_published_match_can_be_prioritized(self):
        links = [URL, URL, "https://letempsmachine.com/agenda/nono-la-grinta-jaguarr"]
        self.assertEqual(len(m.choose(links, set(), TODAY, limit=5)), 2)
        self.assertEqual(m.choose([URL], {("officialUrl", URL)}, TODAY), [URL])

    def test_source_priority_no_published_write(self):
        rows = json.loads((Path(__file__).resolve().parent/"sources.json").read_text(
            encoding="utf-8"))["venues"]
        s = next(x for x in rows if x["id"] == "venue-source-013")
        self.assertEqual(s["adapter"], "letempsmachine_official_detail_review")
        self.assertEqual(s["priority"], "P1")
        self.assertEqual(s["url"], m.AGENDA)
        self.assertFalse(s["publicationAllowed"])
        self.assertFalse(s["publish_automatically"])
        self.assertLessEqual(s["maxAgendaPagesPerRun"], 2)
        self.assertLessEqual(s["maxDetailPagesPerRun"], 8)


if __name__ == "__main__":
    unittest.main()
