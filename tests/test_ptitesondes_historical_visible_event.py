from copy import deepcopy
import json
import unittest
from test_ptitesondes_catalogue_geo_correction_preview import EVENT, NODE, DAY, fixture
from ptitesondes_catalogue_geo_correction_preview import preview
from ptitesondes_historical_visible_event import visible_historical_identity

SOURCE = "https://venue.example/contact"
ITEM = dict(EVENT, time="10h00–11h00")
HTML = """<html><article><h1>Les comptines</h1>
<p>Théâtre des enfants — Ville</p>
<p>12 décembre 2026 à 10h00</p></article></html>"""


class HistoricalVisibleTests(unittest.TestCase):
    def test_exact_visible_same_site_and_geo_only(self):
        self.assertTrue(visible_historical_identity(ITEM, HTML, SOURCE))
        doc, state, proof = fixture()
        doc["events"][0]["time"] = ITEM["time"]
        old = deepcopy(doc)
        out, audit = preview(doc, DAY, state, researcher=lambda *_: proof,
                             source_reader=lambda _: HTML)
        self.assertEqual(audit["proposed_count"], 1)
        self.assertEqual(doc, old)
        self.assertEqual(out["events"][1:], old["events"][1:])
        self.assertEqual(out["events"][0]["time"], ITEM["time"])

    def test_no_mixed_page_or_hidden_cues(self):
        for page in (
            HTML.replace("Les comptines", "Autres comptines"),
            HTML.replace("Théâtre des enfants", "Autre théâtre"),
            HTML.replace("12 décembre 2026", "13 décembre 2026"),
            HTML.replace("10h00", "11h00"),
            HTML.replace("12 décembre 2026 à 10h00", "12 décembre 2026</p><p>10h00"),
            HTML.replace("<p>12 décembre", "<p hidden>12 décembre"),
            HTML.replace("</article>", "<p>Événement annulé</p></article>"),
            HTML.replace("</article>", "</article><article><h1>Autre sortie</h1></article>"),
        ):
            self.assertFalse(visible_historical_identity(ITEM, page, SOURCE), page)
        self.assertFalse(visible_historical_identity(ITEM, HTML, "https://other.example/venue"))
        self.assertFalse(visible_historical_identity(dict(ITEM, time="10h00 et 11h00"), HTML, SOURCE))
        self.assertFalse(visible_historical_identity(dict(ITEM, date_end="2026-12-13"), HTML, SOURCE))

    def test_structured_contradiction_cannot_be_bypassed(self):
        for node in (dict(NODE, eventStatus="https://schema.org/EventCancelled"),
                     dict(NODE, location={"name": "Autre salle"})):
            html = HTML + '<script type="application/ld+json">' + json.dumps(node) + '</script>'
            self.assertFalse(visible_historical_identity(ITEM, html, SOURCE))
        self.assertFalse(visible_historical_identity(ITEM,
            HTML + '<script type="application/ld+json">{bad}</script>', SOURCE))


    def test_nested_address_card_is_not_a_second_event(self):
        page = """<html><article><h1>Les comptines</h1>
        <p>Théâtre des enfants</p>
        <ul><li><div><p>Le samedi, <strong>12 décembre 2026</strong>
        de 10:00 à 11:00</p><p>Le samedi, 12 décembre 2026 de 11:15 à 12:00</p>
        </div></li></ul>
        <article><h3>Théâtre des enfants</h3>
        <ul><li>25 rue de la gare<br>12345 Ville</li></ul></article>
        </article></html>"""
        self.assertTrue(visible_historical_identity(ITEM, page, SOURCE))
        for bad in (
            page.replace("<h3>Théâtre des enfants</h3>", "<h3>Autre théâtre</h3>"),
            page.replace("12345 Ville", "12345 Autreville"),
            page.replace("10:00 à 11:00", "10:00 à 10:30"),
            page.replace("12345 Ville", "<span hidden>12345 Ville</span>"),
            page.replace("<h3>Théâtre des enfants</h3>", "<h1>Théâtre des enfants</h1>"),
            page.replace("25 rue de la gare", "13 décembre 2026"),
        ):
            self.assertFalse(visible_historical_identity(ITEM, bad, SOURCE), bad)
