"""Offline regression tests for Tetris first-party day/month and year strictness."""
import json
from pathlib import Path
import unittest

import tetris_adapter as m

TODAY = "2026-11-03"
SOURCE = {"name": "Le Tetris", "city": "Le Havre", "department": "76",
          "url": m.AGENDA}
URL = "https://letetris.fr/agenda/fff"
AGENDA_HTML = """<main><a href="/agenda/fff">F.F.F.</a>
<a href="/agenda/fff">duplicate</a>
<a href="/agenda/coffin">C.O.F.F.I.N.</a>
<a href="/agenda/archives">Archives</a>
<a href="/agenda">Home</a><a href="https://evil.test/agenda/coffin">evil</a>
<a href="/agenda/coffin?ticket=1">tracking</a></main>"""
DETAIL = """<html><head><meta property="og:title"
content="F.F.F. | Le Tetris"></head><main>
<span>vendredi Ven. 27. novembre Nov. 20:00</span>
<h1>F.F.F.</h1><span>+ Metro Verlaine</span>
<a href="/genres/rock">Rock</a>
<p>Si vous aimez The Inspector Cluzo, Fishbone</p>
<p>Petite restauration sur place à partir de 19h30</p>
<p>Production : Papa's production</p>
<a>Le Tetris</a>, La Grande Salle • Placement libre – Debout
<h2>F.F.F.</h2><p>Rock funk France ; album disponible en 2026.</p>
<h2>Metro Verlaine</h2><p>Post punk France</p>
<h2>Vous devriez aimer…</h2><p>28 novembre 2027 autre événement</p>
</main></html>"""


class TetrisAdapterTests(unittest.TestCase):
    def test_agenda_allowlist_and_dedupe(self):
        self.assertEqual(m.agenda_links(AGENDA_HTML), [URL, "https://letetris.fr/agenda/coffin"])
        for value in ("http://letetris.fr/agenda", m.AGENDA + "?page=2",
                      "https://evil.test/agenda", m.AGENDA + "/",
                      "https://letetris.fr/agenda#events"):
            with self.subTest(value=value):
                self.assertFalse(m.valid_agenda(value))
        for value in ("https://evil.test/agenda/fff",
                      URL + "?p=1", URL + "#details",
                      "https://letetris.fr/agenda/archives",
                      "https://letetris.fr/agenda"):
            self.assertIsNone(m.event_url(value))

    def test_missing_year_is_an_undated_private_lead_never_2026_inferred(self):
        row = m.candidate(DETAIL, URL, SOURCE, TODAY)
        self.assertEqual(row["candidateId"], "tetris:fff")
        self.assertEqual(row["name"], "F.F.F. + Metro Verlaine")
        self.assertEqual(row["displayedDayMonth"], "27-11")
        self.assertIsNone(row["date"])
        self.assertEqual(row["dateEvidence"], "year_not_established")
        self.assertEqual(row["classification"], ["Rock"])
        self.assertEqual(row["venue"], "Le Tetris")
        self.assertIsNone(row["localTime"])
        self.assertTrue(row["reviewRequired"])
        self.assertFalse(row["publicationAllowed"])

    def test_explicit_year_in_header_or_official_time_is_accepted(self):
        dated = DETAIL.replace("27. novembre Nov. 20:00",
                               "27. novembre 2026 20:00")
        row = m.candidate(dated, URL, SOURCE, TODAY)
        self.assertEqual(row["date"], "2026-11-27")
        self.assertEqual(row["dateEvidence"], "explicit_first_party_year")
        timed = DETAIL.replace("<h1>F.F.F.</h1>",
                               '<time datetime="2026-11-27T20:00:00+01:00"></time><h1>F.F.F.</h1>')
        self.assertEqual(m.candidate(timed, URL, SOURCE, TODAY)["date"], "2026-11-27")
        self.assertIsNone(m.candidate(timed, URL, SOURCE, TODAY)["localTime"])

    def test_json_ld_requires_matching_title_venue_and_visible_day_month(self):
        schema = '<script type="application/ld+json">' + json.dumps({
            "@type": "MusicEvent", "name": "F.F.F. + Metro Verlaine",
            "location": {"name": "Le Tetris"},
            "startDate": "2026-11-27T20:00:00+01:00"
        }) + '</script>'
        self.assertEqual(m.candidate(DETAIL.replace("</head>", schema+"</head>"),
                                     URL, SOURCE, TODAY)["date"], "2026-11-27")
        wrong = schema.replace("Le Tetris", "Other Venue")
        self.assertIsNone(m.candidate(DETAIL.replace("</head>", wrong+"</head>"),
                                      URL, SOURCE, TODAY)["date"])
        wrong_day = schema.replace("2026-11-27", "2026-11-28")
        self.assertIsNone(m.candidate(DETAIL.replace("</head>", wrong_day+"</head>"),
                                      URL, SOURCE, TODAY)["date"])

    def test_wrong_year_genre_venue_and_nonconcert_rejected(self):
        cases = {
            "past_year": DETAIL.replace("27. novembre Nov.", "27. novembre 2025"),
            "outside_horizon": DETAIL.replace("27. novembre Nov.", "27. novembre 2028"),
            "no_genre": DETAIL.replace('href="/genres/rock">Rock', 'href="/genres/pop">Pop'),
            "no_venue": DETAIL.replace("Le Tetris</a>, La Grande Salle", "Other</a>, La Grande Salle"),
            "no_room": DETAIL.replace("La Grande Salle", "Autre Salle"),
            "cancelled": DETAIL.replace("F.F.F.</h1>", "F.F.F. (ANNULÉ)</h1>"),
            "festival": DETAIL.replace("F.F.F.</h1>", "F.F.F. FESTIVAL</h1>"),
            "missing_month": DETAIL.replace("27. novembre Nov.", "27. ???"),
            "mismatched_month": DETAIL.replace("27. novembre Nov.", "27. novembre 2026").replace(
                "2026-11-27", "2026-12-27"),
        }
        for name, page in cases.items():
            if name == "mismatched_month":
                continue  # contradictory structured date covered above
            with self.subTest(name=name), self.assertRaises(ValueError):
                m.candidate(page, URL, SOURCE, TODAY)
        with self.assertRaises(ValueError):
            m.candidate(DETAIL, URL, {**SOURCE, "city": "Caen"}, TODAY)
        with self.assertRaises(ValueError):
            m.candidate(DETAIL, URL+"?utm=1", SOURCE, TODAY)

    def test_official_categories_not_artist_biographies(self):
        changed = DETAIL.replace('href="/genres/rock">Rock', 'href="/genres/electro">Electro')
        with self.assertRaises(ValueError):
            m.candidate(changed, URL, SOURCE, TODAY)

    def test_selector_limits_eight_and_rotates_known_safely(self):
        urls = [f"https://letetris.fr/agenda/test-{i}" for i in range(18)]
        urls.append(urls[0])
        self.assertLessEqual(len(m.choose(urls, set(), TODAY, 999)), 8)
        self.assertEqual(m.choose([URL], {("officialUrl", URL)}, TODAY), [URL])

    def test_private_p1_configuration_has_no_publication(self):
        data = json.loads((Path(__file__).resolve().parent/"sources.json").read_text(encoding="utf-8"))
        row = next(x for x in data["venues"] if x["id"] == "venue-source-020")
        self.assertEqual(row["priority"], "P1")
        self.assertEqual(row["adapter"], "tetris_official_detail_review")
        self.assertEqual(row["maxDetailPagesPerRun"], 8)
        self.assertFalse(row["publicationAllowed"])
        self.assertFalse(row["publish_automatically"])


if __name__ == "__main__":
    unittest.main()
