"""Synthetic offline end-to-end tests: new-domain reads are never source authority."""
from copy import deepcopy
import json
import unittest

from national_institutional_organizer_preflight import reprove_organizer_links
from national_organizer_domain_qualification import qualify_organizer_domains
from test_national_institutional_organizer_preflight import (
    DAY1, DAY2, DAY3, INDEX, INDEX_HTML, DETAIL,
    TITLE, WEBSITE, WEB2, detail_with_event, fixture,
    date_run, later,
)

GOOD_HTML = ('<main><h1>Festival Metal des Garrigues 2027</h1>'
             '<p>Les 4 et 5 juin 2027. Festival metal.</p></main>')


def chain():
    state1, q1 = fixture(DAY1)
    date_run(state1, q1, DAY1,
             fetch=lambda u: INDEX_HTML if u == INDEX else detail_with_event())
    state2, q2, dates2 = later(state1, DAY2)
    link2 = reprove_organizer_links(
        state2, q2, dates2, DAY2,
        fetch=lambda u: INDEX_HTML if u == INDEX else detail_with_event())
    assert link2["two_day_link_count"] == 0
    state3, q3, dates3 = later(state2, DAY3)
    link3 = reprove_organizer_links(
        state3, q3, dates3, DAY3,
        fetch=lambda u: INDEX_HTML if u == INDEX else detail_with_event())
    assert link3["two_day_link_count"] == 1
    return state3, q3, dates3, link3


class UnknownOrganizerDomainQualificationTests(unittest.TestCase):
    def test_full_reproof_then_exact_dates_is_private_only(self):
        state, queue, dates, links = chain()
        visits = []
        sites = []
        result = qualify_organizer_domains(
            state, queue, dates, links, DAY3,
            institution_fetch=lambda url: visits.append(url) or
                (INDEX_HTML if url == INDEX else detail_with_event()),
            site_fetch=lambda url: sites.append(url) or GOOD_HTML)
        self.assertEqual(visits, [INDEX, DETAIL])
        self.assertEqual(sites, [WEBSITE])
        self.assertEqual(result["candidate_links_verified_today"], 1)
        self.assertEqual(result["domains_probed_today"], 1)
        self.assertEqual(result["domain_edition_dates_confirmed_today"], 1)
        row = result["rows"][0]
        self.assertEqual(row["status"],
                         "DOMAIN_CURRENT_EDITION_DATES_RECHECKED_PRIVATE")
        self.assertTrue(row["edition_visible_dates_confirmed"])
        for key in ("publication_authorized", "official_site_authorized",
                    "ownership_proven", "safe_to_publish"):
            self.assertFalse(row[key])
            self.assertFalse(result[key])
        self.assertEqual(result["publications"], 0)
        self.assertNotIn("showOnMap", json.dumps(result))
        self.assertNotIn("lineup", json.dumps(result))

    def test_forged_report_target_is_never_fetched(self):
        state, queue, dates, links = chain()
        forged = deepcopy(links)
        forged["rows"][0]["candidate_urls"] = ["https://evil.org/steal"]
        visited = []
        result = qualify_organizer_domains(
            state, queue, dates, forged, DAY3,
            institution_fetch=lambda u: INDEX_HTML if u == INDEX else detail_with_event(),
            site_fetch=lambda u: visited.append(u))
        self.assertEqual(visited, [])
        self.assertEqual(result["domains_probed_today"], 0)
        self.assertFalse(result["official_site_authorized"])

    def test_no_fetch_if_index_link_disappears_or_detail_changes(self):
        state, queue, dates, links = chain()
        for institutional in (
            "<main>No festival link today</main>",
            detail_with_event(url=WEB2),
            detail_with_event(title="Other Metal Festival 2027"),
        ):
            visited = []
            def recheck(url):
                if url == INDEX:
                    return INDEX_HTML if institutional != "<main>No festival link today</main>" else institutional
                return institutional
            result = qualify_organizer_domains(
                state, queue, dates, links, DAY3,
                institution_fetch=recheck,
                site_fetch=lambda u: visited.append(u))
            self.assertEqual(visited, [])
            self.assertEqual(result["domains_probed_today"], 0)

    def test_invalid_or_cancelled_domain_page_is_not_verified(self):
        state, queue, dates, links = chain()
        bad = (
            "<h1>Festival Metal des Garrigues 2027</h1><p>Dates bientôt.</p>",
            GOOD_HTML.replace("4 et 5", "4 et 6"),
            GOOD_HTML.replace("Festival metal", "Festival annulé"),
            "<script>Festival Metal des Garrigues 2027 4 et 5 juin 2027</script>",
            GOOD_HTML + '<script type="application/ld+json">' +
            '{"@type":"MusicEvent","name":"Festival Metal des Garrigues 2027",'
            '"startDate":"2027-06-04","endDate":"2027-06-06"}</script>',
        )
        for page in bad:
            with self.subTest(page=page[:55]):
                result = qualify_organizer_domains(
                    state, queue, dates, links, DAY3,
                    institution_fetch=lambda u: INDEX_HTML if u == INDEX else detail_with_event(),
                    site_fetch=lambda u: page)
                self.assertEqual(result["domain_edition_dates_confirmed_today"], 0)
                self.assertEqual(result["rows"][0]["status"],
                                 "DOMAIN_EDITION_CLAIMS_NOT_MATCHED")

    def test_link_state_missing_or_nonconsecutive_does_not_authorize_probe(self):
        state, queue, dates, links = chain()
        for record in (
            dict(state["national_institutional_organizer_links_private"][DETAIL],
                 lastSeen=DAY2),
            dict(state["national_institutional_organizer_links_private"][DETAIL],
                 digest="a"*64),
            dict(state["national_institutional_organizer_links_private"][DETAIL],
                 firstSeen=DAY3),
        ):
            with self.subTest(record=record):
                changed = deepcopy(state)
                changed["national_institutional_organizer_links_private"][DETAIL] = record
                visited = []
                result = qualify_organizer_domains(
                    changed, queue, dates, links, DAY3,
                    institution_fetch=lambda u: INDEX_HTML if u == INDEX else detail_with_event(),
                    site_fetch=lambda u: visited.append(u))
                self.assertEqual(visited, [])
                self.assertEqual(result["domains_probed_today"], 0)

    def test_forged_favorable_flags_are_rejected_before_any_network(self):
        state, queue, dates, links = chain()
        for update in (
            {"publication_authorized": True},
            {"ownership_proven": True},
            {"as_of": DAY2},
            {"safe_to_publish": True},
        ):
            with self.subTest(update=update):
                altered = dict(links, **update)
                with self.assertRaises(ValueError):
                    qualify_organizer_domains(
                        state, queue, dates, altered, DAY3,
                        institution_fetch=lambda u: self.fail("forged report fetched institution"),
                        site_fetch=lambda u: self.fail("forged report fetched domain"))

    def test_site_fetch_error_does_not_approve(self):
        state, queue, dates, links = chain()
        def unavailable(url):
            raise OSError("do not log private failure body")
        result = qualify_organizer_domains(
            state, queue, dates, links, DAY3,
            institution_fetch=lambda u: INDEX_HTML if u == INDEX else detail_with_event(),
            site_fetch=unavailable)
        self.assertEqual(result["rows"][0]["status"],
                         "DOMAIN_HTTPS_OR_EVIDENCE_UNAVAILABLE")
        self.assertNotIn("do not log", json.dumps(result))
        self.assertFalse(result["publication_authorized"])


if __name__ == "__main__":
    unittest.main()
