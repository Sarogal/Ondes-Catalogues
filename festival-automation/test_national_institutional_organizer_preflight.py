"""Offline tests for generic organizer domains derived from official agendas."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from national_institutional_edition_preflight import run as date_run
from national_institutional_organizer_preflight import reprove_organizer_links
from test_national_institutional_edition_preflight import (
    fixture, INDEX, DETAIL, TITLE, INDEX_HTML, DETAIL_HTML,
)

DAY1 = "2026-11-06"
DAY2 = "2026-11-07"
DAY3 = "2026-11-08"
WEBSITE = "https://festival-garrigues-exemple.fr/"
WEB2 = "https://autre-festival-exemple.fr/"


def detail_with_event(url=WEBSITE, title=TITLE, end="2027-06-05"):
    return (DETAIL_HTML + '<script type="application/ld+json">'
            + json.dumps({
                "@context": "https://schema.org", "@type": "MusicEvent",
                "name": title, "startDate": "2027-06-04",
                "endDate": end, "url": url
            }) + "</script>")


def observed_day1(html=None):
    state, queue = fixture(DAY1)
    date_run(state, queue, DAY1,
             fetch=lambda url: INDEX_HTML if url == INDEX else html or detail_with_event())
    return state


def later(prior, today, html=None):
    state, queue = fixture(today)
    state["national_institutional_dates_private"] = deepcopy(
        prior["national_institutional_dates_private"])
    if "national_institutional_organizer_links_private" in prior:
        state["national_institutional_organizer_links_private"] = deepcopy(
            prior["national_institutional_organizer_links_private"])
    date_report = date_run(
        state, queue, today,
        fetch=lambda url: INDEX_HTML if url == INDEX else html or detail_with_event())
    return state, queue, date_report


class GenericOrganizerPreflightTests(unittest.TestCase):
    def test_private_two_day_link_requires_prior_two_day_edition(self):
        state, queue = fixture(DAY1)
        dates = date_run(state, queue, DAY1,
                         fetch=lambda url: INDEX_HTML if url == INDEX else detail_with_event())
        visited = []
        first = reprove_organizer_links(
            state, queue, dates, DAY1, fetch=lambda url: visited.append(url))
        self.assertEqual(visited, [])
        self.assertEqual(first["rows"], [])
        self.assertFalse(first["official_site_authorized"])
        state2, q2, dates2 = later(state, DAY2)
        visited.clear()
        second = reprove_organizer_links(
            state2, q2, dates2, DAY2, fetch=lambda url: (
                visited.append(url) or
                (INDEX_HTML if url == INDEX else detail_with_event())))
        self.assertEqual(visited, [INDEX, DETAIL])
        self.assertEqual(second["two_day_link_count"], 0)
        self.assertEqual(second["rows"][0]["candidate_urls"], [WEBSITE])
        self.assertEqual(second["rows"][0]["status"],
                         "FIRST_DAY_INSTITUTIONAL_ORGANIZER_LINK_PRIVATE")
        self.assertFalse(second["rows"][0]["ownership_proven"])
        self.assertFalse(second["rows"][0]["official_site_authorized"])
        self.assertFalse(second["rows"][0]["publication_authorized"])
        self.assertNotIn("officialSite", json.dumps(second))
        state3, q3, dates3 = later(state2, DAY3)
        third = reprove_organizer_links(
            state3, q3, dates3, DAY3,
            fetch=lambda url: INDEX_HTML if url == INDEX else detail_with_event())
        self.assertEqual(third["two_day_link_count"], 1)
        self.assertEqual(third["rows"][0]["candidate_urls"], [WEBSITE])
        self.assertEqual(third["rows"][0]["status"],
                         "TWO_DAY_INSTITUTIONAL_ORGANIZER_LINK_PRIVATE")
        self.assertEqual(third["publications"], 0)

    def test_changed_link_is_a_new_first_day_never_old_stable_proof(self):
        prior = observed_day1()
        state2, q2, dates2 = later(prior, DAY2)
        reprove_organizer_links(
            state2, q2, dates2, DAY2,
            fetch=lambda u: INDEX_HTML if u == INDEX else detail_with_event())
        state3, q3, dates3 = later(state2, DAY3)
        third = reprove_organizer_links(
            state3, q3, dates3, DAY3,
            fetch=lambda u: INDEX_HTML if u == INDEX else detail_with_event(WEB2))
        self.assertEqual(third["two_day_link_count"], 0)
        self.assertEqual(third["rows"][0]["candidate_urls"], [WEB2])
        self.assertEqual(
            state3["national_institutional_organizer_links_private"][DETAIL]["firstSeen"],
            DAY3)

    def test_private_unsafe_target_never_fetched_or_accepted(self):
        prior = observed_day1()
        state, queue, dates = later(prior, DAY2)
        for target in (
            "https://127.0.0.1/admin", "http://festival-garrigues-exemple.fr/",
            "https://agenda.montpellier.fr/unrelated",
            "https://www.facebook.com/example",
        ):
            visits = []
            review = reprove_organizer_links(
                state, queue, dates, DAY2,
                fetch=lambda url: visits.append(url) or
                    (INDEX_HTML if url == INDEX else detail_with_event(target)))
            self.assertEqual(visits, [INDEX, DETAIL])
            self.assertEqual(review["rows"][0]["candidate_urls"], [])
            self.assertFalse(review["rows"][0]["official_site_authorized"])
            self.assertEqual(review["rows"][0]["status"],
                             "NO_EXACT_EVENT_ORGANIZER_WEBSITE_LINK")

    def test_mismatched_jsonld_event_and_dates_fail_closed(self):
        prior = observed_day1()
        state, queue, dates = later(prior, DAY2)
        for html in (
            detail_with_event(title="Autre Festival 2027"),
            detail_with_event(end="2027-06-06"),
            DETAIL_HTML.replace("4 et 5", "4 et 6") +
                detail_with_event().split("<script", 1)[1].join(["<script", ""]),
        ):
            visits = []
            result = reprove_organizer_links(
                state, queue, dates, DAY2,
                fetch=lambda u: visits.append(u) or
                    (INDEX_HTML if u == INDEX else html))
            self.assertEqual(visits, [INDEX, DETAIL])
            self.assertEqual(result["two_day_link_count"], 0)
            self.assertNotEqual(result["rows"][0]["candidate_urls"], [WEBSITE])

    def test_forged_status_or_state_never_authorizes_new_fetch(self):
        prior = observed_day1()
        state, queue, dates = later(prior, DAY2)
        dates["publication_authorized"] = True
        with self.assertRaises(ValueError):
            reprove_organizer_links(
                state, queue, dates, DAY2,
                fetch=lambda u: self.fail("forged report must not fetch"))
        state, queue, dates = later(prior, DAY2)
        key = next(iter(state["national_institutional_dates_private"]))
        state["national_institutional_dates_private"][key]["digest"] = "0"*64
        visited = []
        result = reprove_organizer_links(
            state, queue, dates, DAY2, fetch=lambda u: visited.append(u))
        self.assertEqual(visited, [])
        self.assertEqual(result["checked_count"], 0)


if __name__ == "__main__":
    unittest.main()
