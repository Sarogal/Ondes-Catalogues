"""Synthetic offline contract tests for institutional date preflight."""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parent))

from national_discovery_queue import build_queue
from national_institutional_edition_preflight import run, _exact_edition

DAY1 = "2026-11-06"
DAY2 = "2026-11-07"
INDEX = "https://agenda.montpellier.fr/"
DETAIL = "https://agenda.montpellier.fr/evenement/metal-des-garrigues-2027"
TITLE = "Festival Metal des Garrigues 2027"
INDEX_HTML = ('<main><a href="/evenement/metal-des-garrigues-2027">'
              'Festival Metal des Garrigues 2027</a></main>')
DETAIL_HTML = ('<main><h1>Festival Metal des Garrigues 2027</h1>'
               '<p>Les 4 et 5 juin 2027 au festival de Montpellier.</p></main>')


def fixture(today):
    state = {
        "schema": "grossesondes.source-watch.v1",
        "regional_festival_candidates_review_only": {
            DETAIL: {
                "candidate_url": DETAIL,
                "title": TITLE, "source_index": INDEX,
                "region": "Occitanie",
                "firstSeen": "2026-11-05", "lastSeen": today,
                "status": "UNVERIFIED_THEME_LINK",
                "discovery_signal": "THEMATIC_NAME_ONLY",
                "historical_name_slug": None,
                "publication_authorized": False,
            },
        },
        "institutional_agenda_candidate_pages": {},
        "secondary_source_candidates_private": {},
    }
    report = {"schema": "grossesondes.source-watch-report.v1",
              "date": today, "source_reference_leads_review_only": []}
    return state, build_queue(state, report, [], today)


def good_fetch(url):
    if url == INDEX:
        return INDEX_HTML
    if url == DETAIL:
        return DETAIL_HTML
    raise AssertionError("Forbidden URL: " + url)


class InstitutionalPreflightTests(unittest.TestCase):
    def test_two_day_observation_not_two_passes_same_day(self):
        state, queue = fixture(DAY1)
        first = run(state, queue, DAY1, fetch=good_fetch)
        self.assertEqual(first["checked_count"], 1)
        self.assertEqual(first["two_day_observations_count"], 0)
        self.assertEqual(first["rows"][0]["start_date_hint"], "2027-06-04")
        self.assertEqual(first["rows"][0]["end_date_hint"], "2027-06-05")
        again = run(state, queue, DAY1, fetch=good_fetch)
        self.assertEqual(again["two_day_observations_count"], 0)
        next_state, next_queue = fixture(DAY2)
        next_state["national_institutional_dates_private"] = deepcopy(
            state["national_institutional_dates_private"])
        result = run(next_state, next_queue, DAY2, fetch=good_fetch)
        self.assertEqual(result["two_day_observations_count"], 1)
        self.assertEqual(result["rows"][0]["status"],
                         "TWO_DAY_INSTITUTIONAL_DATE_RECHECKED_PRIVATE")
        self.assertFalse(result["publication_authorized"])
        self.assertFalse(result["publisher_gate_connected"])
        self.assertNotIn("showOnMap", json.dumps(result))
        self.assertNotIn("lat", json.dumps(result))
        self.assertNotIn("lineup", json.dumps(result))

    def test_unverified_dates_or_disappeared_link_never_pass(self):
        for index, detail in (
            ("<main>Festival 2027 sans lien</main>", DETAIL_HTML),
            (INDEX_HTML, '<h1>Festival Metal des Garrigues 2027</h1>'
                         '<p>Programmation à venir</p>'),
            (INDEX_HTML, DETAIL_HTML.replace("2027", "2026")),
            (INDEX_HTML, DETAIL_HTML.replace("4 et 5", "4 et 6")),
        ):
            with self.subTest(index=index, detail=detail):
                state, queue = fixture(DAY1)
                result = run(state, queue, DAY1,
                             fetch=lambda u: index if u == INDEX else detail)
                self.assertEqual(result["two_day_observations_count"], 0)
                self.assertFalse(result["rows"][0]["publication_authorized"])

    def test_jsonld_contradiction_or_cancellation_rejected(self):
        source = {"title": TITLE, "year": 2027}
        cancelled = DETAIL_HTML.replace(
            "festival de Montpellier", "festival annulé de Montpellier")
        self.assertIsNone(_exact_edition(cancelled, source, DAY1))
        contrary = (DETAIL_HTML +
            '<script type="application/ld+json">'
            '{"@context":"https://schema.org","@type":"MusicEvent",'
            '"name":"Festival Metal des Garrigues 2027",'
            '"startDate":"2027-06-04","endDate":"2027-06-06"}</script>')
        self.assertIsNone(_exact_edition(contrary, source, DAY1))
        self.assertIsNone(_exact_edition(
            '<script>Festival Metal des Garrigues, 4 et 5 juin 2027</script>',
            source, DAY1))

    def test_unknown_or_forged_private_source_never_fetched(self):
        state, queue = fixture(DAY1)
        source = state["regional_festival_candidates_review_only"].pop(DETAIL)
        source["candidate_url"] = "https://evil.example/festival"
        state["regional_festival_candidates_review_only"][source["candidate_url"]] = source
        report = {"schema": "grossesondes.source-watch-report.v1",
                  "date": DAY1, "source_reference_leads_review_only": []}
        queue = build_queue(state, report, [], DAY1)
        visited = []
        result = run(state, queue, DAY1, fetch=lambda url: visited.append(url))
        self.assertEqual(visited, [])
        self.assertEqual(result["checked_count"], 0)
        self.assertFalse(result["publication_authorized"])


if __name__ == "__main__":
    unittest.main()
