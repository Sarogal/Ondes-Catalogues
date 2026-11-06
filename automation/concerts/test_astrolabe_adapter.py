"""Astrolabe official metadata, archive rejection and review-only integration."""
import datetime as dt
import unittest
from unittest.mock import patch

import astrolabe_adapter as astro
import discover

HOME = "https://www.lastrolabe.org/"
DETAIL = "https://www.lastrolabe.org/agenda/alcest-agriculture/"
SOURCE = {
    "name": "L'Astrolabe", "city": "Orléans", "department": "45",
    "url": HOME, "priority": "P1", "adapter": "astrolabe_official_detail_review",
    "publish_automatically": False, "maxDetailPagesPerRun": 8,
}
LIST = """<html><main>
    <a href="/agenda/alcest-agriculture/">ALCEST</a>
    <a href="/agenda/alcest-agriculture/">ALCEST duplicate</a>
    <a href="https://example.org/agenda/faux/">False</a>
    <a href="/agenda/">Past archive</a>
</main></html>"""
EVENT = """<html><main>
    <p>Black metal</p><h1>ALCEST + AGRICULTURE</h1>
    <p>14.03.2027 - 17H00 - GRANDE SALLE</p>
    <p>OUVERTURE DES PORTES À 17H, DÉBUT À 17H30</p>
    <p>ALCEST ( BLACK METAL)</p>
</main></html>"""


class AstrolabeTests(unittest.TestCase):
    def test_only_homepage_and_official_details_not_historical_archive(self):
        self.assertEqual(astro.detail_urls(LIST, HOME), [DETAIL])
        for invalid in ("https://www.lastrolabe.org/agenda/",
                        "https://evil.example/",
                        "http://www.lastrolabe.org/"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                astro.detail_urls(LIST, invalid)
        self.assertIsNone(astro.valid_detail(DETAIL + "?token=secret"))
        self.assertIsNone(astro.valid_detail("https://other.example/agenda/alcest-agriculture/"))
        self.assertIsNone(astro.valid_detail("https://www.lastrolabe.org/agenda/"))

    def test_official_event_has_no_autopublish_or_inferred_start(self):
        candidate = astro.detail_candidate(EVENT, DETAIL, SOURCE, "2026-11-03")
        self.assertEqual(candidate["name"], "ALCEST + AGRICULTURE")
        self.assertEqual(candidate["date"], "2027-03-14")
        self.assertEqual(candidate["classification"], ["Black metal"])
        self.assertIsNone(candidate["localTime"])
        self.assertFalse(candidate["publicationAllowed"])
        self.assertTrue(candidate["reviewRequired"])
        self.assertTrue(candidate["officialDetailFound"])

    def test_le_club_official_room_is_valid_but_not_published(self):
        body = EVENT.replace("Black metal", "Noise").replace(
            "ALCEST + AGRICULTURE", "LA JUNGLE + SODOM & SAGESSE"
        ).replace("14.03.2027 - 17H00 - GRANDE SALLE",
                  "21.01.2027 - 20H00 - LE CLUB")
        url = "https://www.lastrolabe.org/agenda/la-jungle-sodom-sagesse/"
        candidate = astro.detail_candidate(body, url, SOURCE, "2026-11-03")
        self.assertEqual(candidate["date"], "2027-01-21")
        self.assertEqual(candidate["venue"], "L'Astrolabe")
        self.assertEqual(candidate["classification"], ["Noise"])
        self.assertEqual(candidate["name"], "LA JUNGLE + SODOM & SAGESSE")
        self.assertIsNone(candidate["localTime"])
        self.assertTrue(candidate["reviewRequired"])
        self.assertFalse(candidate["publicationAllowed"])
        with self.assertRaises(ValueError):
            astro.detail_candidate(body.replace("LE CLUB", "La Salle voisine"),
                                   url, SOURCE, "2026-11-03")

    def test_wrong_date_venue_genre_cancellation_and_source_are_held(self):
        cases = [
            EVENT.replace("14.03.2027", "14.03.2024"),
            EVENT.replace("14.03.2027", "31.02.2027"),
            EVENT.replace("GRANDE SALLE", "Salle inconnue"),
            EVENT.replace("Black metal</p>", "Pop</p>"),
            EVENT.replace("ALCEST + AGRICULTURE</h1>",
                          "ALCEST + AGRICULTURE ANNULÉ</h1>"),
            EVENT.replace("<main>", "<section>").replace("</main>", "</section>"),
            EVENT.replace("ALCEST + AGRICULTURE", ""),
        ]
        for i, body in enumerate(cases):
            with self.subTest(i=i), self.assertRaises(ValueError):
                astro.detail_candidate(body, DETAIL, SOURCE, "2026-11-03")
        with self.assertRaises(ValueError):
            astro.detail_candidate(EVENT, DETAIL, {**SOURCE, "city": "Paris"},
                                   "2026-11-03")

    def test_daily_rotation_respects_budget_and_known_urls(self):
        urls = [DETAIL, "https://www.lastrolabe.org/agenda/la-jungle-sodom-sagesse/",
                "https://www.lastrolabe.org/agenda/orpheum-black-le-dernier-acte/"]
        chosen = astro.selected_urls(urls, {("officialUrl", DETAIL)},
                                     "2026-11-03", limit=2)
        self.assertEqual(len(chosen), 2)
        self.assertNotIn(DETAIL, chosen)

    def test_scan_integration_does_not_publish(self):
        def download(url, **_kwargs):
            if url == HOME:
                return LIST, HOME
            if url == DETAIL:
                return EVENT, DETAIL
            raise ValueError("Unlisted URL")
        checks = []
        with patch.object(discover, "download", side_effect=download), \
             patch.object(discover, "robots_allow", return_value=True), \
             patch.object(discover.feeds, "feed_links",
                          return_value={"ics": [], "rss": []}):
            rows = discover.scan_venues({"venues": [SOURCE]}, set(),
                                        dt.date(2026, 11, 3), checks)
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["publicationAllowed"])
        self.assertEqual(checks[0]["adapterDiagnostic"]["datedGenreLeads"], 1)
        self.assertEqual(checks[0]["adapterDiagnostic"]["eventLinksFound"], 1)


if __name__ == "__main__":
    unittest.main()
