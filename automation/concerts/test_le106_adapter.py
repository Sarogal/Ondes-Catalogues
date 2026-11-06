"""Tests fermés : adapter Le 106, aucune piste brute ne devient approuvée."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
import unittest

import le106_adapter as adapter

ROOT = Path(__file__).resolve().parent
TODAY = "2026-11-03"
SOURCE = {
    "name": "Le 106", "city": "Rouen", "department": "76",
    "url": "https://le106.com/agenda",
}
DETAIL = """<main><article><p>Rock</p><p>Carte club Club</p>
<h1>Johnny Mafia <br/>+ Les Agamemnonz</h1>
<p>En ouverture, les surf-rockeurs Les Agamemnonz.</p>
<p>Le 106 • Placement libre</p><p>Production : Le 106</p></article></main>"""
CARD = """<article class="views-row event-card">
<time datetime="2027-02-12T20:00:00">vendredi 12 février 2027</time>
<span class="tag">Rock</span>
<a href="/agenda/johnny-mafia-les-agamemnonz">Johnny Mafia</a>
</article>"""
PUNK = """<article class="event-card"><time datetime="2026-11-17T18:30:00">17 novembre 2026</time>
<span>Punk / Rock</span><a href="/agenda/elktrk-skin-yu-kaask">ELKTRK SKIN</a></article>"""


class Le106AdapterTests(unittest.TestCase):
    def test_official_bounded_agenda_and_nominal_detail_only(self):
        self.assertTrue(adapter.valid_agenda("https://le106.com/agenda"))
        self.assertTrue(adapter.valid_agenda("https://le106.com/agenda?page=5"))
        for url in ("https://le106.com/agenda?page=6",
                    "https://le106.com/agenda?genre=rock",
                    "http://le106.com/agenda",
                    "https://evil.example/agenda",
                    "https://le106.com/agenda#hidden",
                    "https://le106.com.evil.example/agenda"):
            with self.subTest(url=url):
                self.assertFalse(adapter.valid_agenda(url))
        self.assertEqual(adapter.event_url("/agenda/johnny-mafia-les-agamemnonz"),
                         "https://le106.com/agenda/johnny-mafia-les-agamemnonz")
        for url in ("https://example.org/agenda/johnny-mafia-les-agamemnonz",
                    "https://le106.com/agenda/johnny-mafia-les-agamemnonz?page=1",
                    "http://le106.com/agenda/johnny-mafia-les-agamemnonz"):
            self.assertIsNone(adapter.event_url(url))

    def test_year_required_no_month_or_venue_guess(self):
        self.assertEqual(adapter.parse_day("vendrediVen. 12. février02. 2027"),
                         "2027-02-12")
        self.assertEqual(adapter.parse_day("12 février 2027"), "2027-02-12")
        self.assertEqual(adapter.parse_day("2027-02-12T20:00:00"), "2027-02-12")
        self.assertIsNone(adapter.parse_day("12 février"))
        self.assertIsNone(adapter.parse_day("vendredi 12 février03. 2026"))
        self.assertIsNone(adapter.parse_day("31 février 2027"))
        self.assertIsNone(adapter.parse_day("2027-02-30"))

    def test_official_card_requires_full_date_genre_and_single_event_link(self):
        html = (CARD + PUNK +
                """<article class="event-card"><time>13 mars</time><span>Metal</span>
                <a href="/agenda/sans-annee">Sans année</a></article>""" +
                """<article class="event-card"><time datetime="2027-03-12">12 mars</time>
                <span>Hip Hop</span><a href="/agenda/rap">Rap</a></article>""" +
                """<article class="event-card"><time datetime="2027-03-13">13 mars</time>
                <span>Rock</span><a href="/agenda/festival-de-rock">Festival de rock</a></article>""" +
                """<article class="event-card"><time datetime="2027-03-14">14 mars</time>
                <span>Rock</span><a href="/agenda/annule">Annulé</a></article>""" +
                """<article class="event-card"><time datetime="2027-03-15">15 mars</time>
                <span>Rock</span><a href="/agenda/one">One</a>
                <a href="/agenda/two">Two</a></article>""")
        cards = adapter.agenda_cards(html, today=TODAY)
        self.assertEqual({x["date"] for x in cards}, {"2027-02-12", "2026-11-17"})
        self.assertEqual({x["url"] for x in cards}, {
            "https://le106.com/agenda/johnny-mafia-les-agamemnonz",
            "https://le106.com/agenda/elktrk-skin-yu-kaask"})
        self.assertTrue(all(x["evidence"] == "official_agenda_card_with_year"
                            for x in cards))
        self.assertEqual(adapter.agenda_cards(CARD, today="2027-02-13"), [])

    def test_complete_artist_bill_from_detail_not_fabricated_start(self):
        card = adapter.agenda_cards(CARD, today=TODAY)[0]
        row = adapter.candidate(DETAIL, card["url"], card, SOURCE, TODAY)
        self.assertEqual(row["name"], "Johnny Mafia + Les Agamemnonz")
        self.assertEqual(row["leadArtist"], "Johnny Mafia")
        self.assertEqual(row["date"], "2027-02-12")
        self.assertEqual(row["venue"], "Le 106")
        self.assertEqual(row["candidateId"],
                         "le106:2027-02-12:johnny-mafia-les-agamemnonz")
        self.assertIsNone(row["localTime"])
        self.assertFalse(row["publicationAllowed"])
        self.assertTrue(row["reviewRequired"])
        self.assertTrue(row["officialDetailFound"])

    def test_reject_altered_location_or_detail(self):
        card = adapter.agenda_cards(CARD, today=TODAY)[0]
        for detail, source in (
            (DETAIL.replace("Le 106", "Autre salle"), SOURCE),
            (DETAIL.replace("Johnny Mafia", "Annulé Johnny Mafia"), SOURCE),
            (DETAIL, {**SOURCE, "city": "Caen"}),
        ):
            with self.subTest(detail=detail[:25],city=source["city"]):
                with self.assertRaises(ValueError):
                    adapter.candidate(detail, card["url"], card, source, TODAY)

    def test_limit_and_unknown_first_without_using_time_or_publish(self):
        card = adapter.agenda_cards(CARD, today=TODAY)[0]
        other = adapter.agenda_cards(PUNK, today=TODAY)[0]
        known = {("officialUrl", other["url"])}
        chosen = adapter.selected_cards([card, other], known, TODAY, limit=1)
        self.assertEqual([x["url"] for x in chosen], [card["url"]])
        chosen = adapter.selected_cards([card, other], known, TODAY, limit=2)
        self.assertEqual({x["url"] for x in chosen}, {card["url"], other["url"]})

    def test_config_daily_p1_no_approval(self):
        doc = json.loads((ROOT / "sources.json").read_text(encoding="utf-8"))
        config = next(x for x in doc["venues"] if x["id"] == "existing-new-76-le-106")
        self.assertEqual(config["adapter"], "le106_official_agenda_review")
        self.assertEqual(config["priority"], "P1")
        self.assertEqual(config["url"], adapter.AGENDA)
        self.assertFalse(config["publish_automatically"])
        self.assertFalse(config["publicationAllowed"])
        self.assertLessEqual(config["maxDetailPagesPerRun"], 8)
        self.assertLessEqual(config["maxAgendaPagesPerRun"], 3)


if __name__ == "__main__":
    unittest.main()
