"""Fail-closed Chato'do (Blois) official event leads, no publication."""
from __future__ import annotations

import json
from pathlib import Path
import unittest

import chatodo_adapter as module

ROOT = Path(__file__).resolve().parent
SOURCE = {"name": "Le Chato'do", "city": "Blois", "department": "41"}
PAGE = '''<main><article>
<p>jeudi 12 novembre 2026</p><p>18:30 @ 22:30</p>
<p>electro clash</p><p>POST-ROCK</p><p>Gratuit</p>
<p>Le Club</p><p>Ouverture de 18h30 à 22h30. Début du concert à 19h30.</p>
<p>Wicked Vessel et Ultramoderne font partie de ces groupes...</p>
</article></main>'''
DETAIL = '''<html><head><meta property="og:title"
content="Wicked Vessel + Ultramoderne - Chato'do"/></head>''' + PAGE + '</html>'
FLYING = '''<html><head><title>The Flying Bones - Chato'do</title></head>
<main><article><p>jeudi 05 novembre 2026</p><p>18:30 @ 22:30</p>
<p>rock garage</p><p>Gratuit</p><p>Le Club</p>
<p>Ouverture de 18h30 à 22h30. Début du concert à 19h30.</p>
<p>The Flying Bones est un duo rock/garage.</p>
</article></main></html>'''
WICKED_URL = "https://chatodo.com/agenda/evenement/wicked-vessel-ultramoderne/"
FLYING_URL = "https://chatodo.com/agenda/evenement/the-flying-bones/"


class ChatodoAdapterTests(unittest.TestCase):
    def test_official_agenda_links_only_no_photo_articles(self):
        html = '''<main><a href="/agenda/evenement/the-flying-bones/">Flying</a>
        <a href="/opac-photos/">Photo</a>
        <a href="https://bad.example/agenda/evenement/unknown/">No</a>
        <a href="/agenda/evenement/wicked-vessel-ultramoderne/">Wicked</a>
        <a href="/agenda/evenement/the-flying-bones/">duplicate</a></main>'''
        self.assertEqual(module.official_links(html, module.AGENDA),
                         [FLYING_URL, WICKED_URL])
        with self.assertRaises(ValueError):
            module.official_links(html, "https://chatodo.com/opac-photos/")
        self.assertTrue(module.agenda_url(module.AGENDA + "page/2/"))
        self.assertFalse(module.agenda_url(module.AGENDA + "page/12/"))
        self.assertIsNone(module.event_url(WICKED_URL + "?coupon=1"))

    def test_full_year_and_real_calendar_date_required(self):
        self.assertEqual(module.parse_date("jeudi 12 novembre 2026"), "2026-11-12")
        self.assertEqual(module.parse_date("05 novembre 2026"), "2026-11-05")
        self.assertIsNone(module.parse_date("12 novembre"))
        self.assertIsNone(module.parse_date("31 novembre 2026"))

    def test_correct_two_official_dates_titles_and_venue(self):
        for html, link, title, day in (
            (FLYING, FLYING_URL, "The Flying Bones", "2026-11-05"),
            (DETAIL, WICKED_URL, "Wicked Vessel + Ultramoderne", "2026-11-12"),
        ):
            with self.subTest(link=link):
                row = module.candidate(html, link, SOURCE, "2026-11-03")
                self.assertEqual((row["name"], row["date"], row["venue"]),
                                 (title, day, "Le Chato'do"))
                self.assertTrue(row["officialDetailFound"])
                self.assertIsNone(row["localTime"])
                self.assertFalse(row["publicationAllowed"])
                self.assertTrue(row["reviewRequired"])

    def test_reject_missing_year_ambiguous_dates_unknown_genre_location(self):
        cases = [
            DETAIL.replace("12 novembre 2026", "12 novembre"),
            DETAIL.replace("12 novembre 2026", "12 novembre 2026 et 14 novembre 2026"),
            DETAIL.replace("POST-ROCK", "music electro"),
            DETAIL.replace("Le Club", "Ailleurs"),
            DETAIL.replace("Wicked Vessel + Ultramoderne - Chato'do", "Festival - Chato'do"),
            DETAIL.replace("Wicked Vessel + Ultramoderne - Chato'do", "Wicked Vessel - Autre salle"),
        ]
        for html in cases:
            with self.subTest(html=html[:110]):
                with self.assertRaises(ValueError):
                    module.candidate(html, WICKED_URL, SOURCE, "2026-11-03")
        with self.assertRaises(ValueError):
            module.candidate(DETAIL, WICKED_URL, {**SOURCE, "city":"Caen"}, "2026-11-03")
        with self.assertRaises(ValueError):
            module.candidate(DETAIL, WICKED_URL, SOURCE, "2026-11-13")

    def test_dedup_rotation_and_no_auto_approval(self):
        chosen = module.selected_urls(
            [FLYING_URL, WICKED_URL, WICKED_URL],
            {("officialUrl", FLYING_URL)}, "2026-11-03", limit=1)
        self.assertEqual(chosen, [WICKED_URL])

    def test_source_is_p1_and_discovery_only(self):
        data = json.loads((ROOT / "sources.json").read_text(encoding="utf-8"))
        row = next(x for x in data["venues"] if x["id"] == "venue-source-014")
        self.assertEqual(row["adapter"], "chatodo_official_detail_review")
        self.assertEqual(row["priority"], "P1")
        self.assertEqual(row["url"], module.AGENDA)
        self.assertFalse(row["publish_automatically"])
        self.assertFalse(row["publicationAllowed"])
        self.assertLessEqual(row["maxDetailPagesPerRun"], 8)
        self.assertLessEqual(row["maxAgendaPagesPerRun"], 2)


if __name__ == "__main__":
    unittest.main()
