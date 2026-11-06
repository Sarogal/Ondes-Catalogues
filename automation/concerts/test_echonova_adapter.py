"""Tests for strict Echonova first-party discovery and no publishing."""
import datetime as dt
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import echonova_adapter as e
import discover

TODAY = "2026-11-04"
URL = e.BASE + "/evenement/eiffel-premiere-partie/"
OTHER = e.BASE + "/evenement/nova-loves-ya-mac-declos-lacchesi-kersu/"
SOURCE = {"name": "L'Echonova", "city": "Saint-Avé", "department": "56",
          "priority": "P1", "url": e.AGENDA,
          "adapter": "echonova_official_detail_review",
          "maxDetailPagesPerRun": 6}
AGENDA_HTML = ('<main><a href="/evenement/eiffel-premiere-partie/">Eiffel</a>'
               '<a href="/evenement/nova-loves-ya-mac-declos-lacchesi-kersu/">Techno</a>'
               '<a href="https://untrusted.test/evenement/fake/">Fake</a>'
               '<a href="/evenement/eiffel-premiere-partie/?utm=1">tracking</a></main>')
OFFICIAL = """<main><p>Organisé par BASE PRODUCTION</p>
<p>EIFFEL</p><p>Biographie : en 2022, tournée art-rock.</p>
<ul><li>Rock</li><li>Concert</li></ul>
<p>EIFFEL + Première partie</p>
<p><strong>Jeudi 3 décembre 2026 - L'Echonova</strong></p>
<ul><li>Ouverture des portes : 20:00</li>
<li>Début des concerts : 20:30</li></ul>
<article><p>Événement suivant</p><p>Samedi 5 décembre 2026 - L'Echonova</p>
<ul><li>Metal</li><li>Concert</li></ul></article></main>"""
TECHNO = """<main><ul><li>Hardcore</li><li>Techno</li><li>Concert</li></ul>
<p>MAC DECLOS + LACCHESI</p><p>Vendredi 6 novembre 2026 - L'Echonova</p></main>"""


class EchonovaTests(unittest.TestCase):
    def test_index_has_exact_official_links_and_six_max(self):
        self.assertEqual(e.agenda_links(AGENDA_HTML, e.AGENDA), [URL, OTHER])
        self.assertIsNone(e.canonical_detail(URL+"?x=1"))
        self.assertIsNone(e.canonical_detail("http://lechonova.com/evenement/xzy/"))
        self.assertIsNone(e.canonical_detail("https://evil.test/evenement/fake/"))
        self.assertEqual(e.select_urls([URL]*10, set(), TODAY, 6), [URL])

    def test_exact_year_named_event_and_musical_time(self):
        c = e.candidate(OFFICIAL, URL, SOURCE, TODAY)
        self.assertEqual((c["date"], c["localTime"]),
                         ("2026-12-03", "20:30"))
        self.assertEqual(c["leadArtist"], "EIFFEL")
        self.assertEqual(c["classification"], ["rock"])
        self.assertFalse(c["publicationAllowed"])
        self.assertTrue(c["reviewRequired"])

    def test_no_techno_misclassification_or_year_guessing(self):
        scenarios = [TECHNO,
                     OFFICIAL.replace("décembre 2026", "décembre", 1),
                     OFFICIAL.replace("Rock</li>", "Techno</li>"),
                     OFFICIAL.replace(" - L'Echonova", " - Autre salle", 1),
                     OFFICIAL.replace("EIFFEL + Première partie", "Festival EIFFEL")]
        for bad in scenarios:
            with self.assertRaises(ValueError):
                e.candidate(bad, URL, SOURCE, TODAY)
        no_time = OFFICIAL.replace("Début des concerts : 20:30", "Ouverture : 20:30")
        self.assertIsNone(e.candidate(no_time, URL, SOURCE, TODAY)["localTime"])

    def test_discovery_is_private_and_records_holds(self):
        config = json.loads((Path(__file__).parent/"sources.json").read_text())
        source = next(v for v in config["venues"] if v["name"] == "L'Echonova")
        self.assertEqual(source["adapter"], SOURCE["adapter"])
        self.assertFalse(source["publish_automatically"])
        expected = {e.AGENDA: AGENDA_HTML, URL: OFFICIAL, OTHER: TECHNO}
        def download(url, **kwargs):
            if url not in expected:
                raise RuntimeError("Unrecognized extra network request")
            return expected[url], url
        checks = []
        with patch.object(discover, "robots_allow", return_value=True), \
             patch.object(discover, "download", side_effect=download):
            results = discover.scan_venues({"venues": [source]}, set(),
                                           dt.date.fromisoformat(TODAY), checks)
        self.assertEqual(len(results), 1)
        self.assertEqual(checks[0]["adapterDiagnostic"]["datedGenreLeads"], 1)
        self.assertEqual(checks[0]["adapterDiagnostic"]["heldOrIrrelevant"], 1)
        self.assertEqual(checks[0]["adapterDiagnostic"]["heldReasons"],
                         {"No official concert and relevant genre tags": 1})
        self.assertEqual(checks[0]["adapterDiagnostic"]["heldReviewSamples"][0]["url"], OTHER)
        self.assertEqual(len(checks[0]["adapterDiagnostic"]["heldReviewSamples"]), 1)
        self.assertFalse(results[0]["publicationAllowed"])


if __name__ == "__main__":
    unittest.main()
