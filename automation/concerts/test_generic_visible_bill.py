"""Realistic offline first-party HTML bill discovery regression tests.

Uses synthetic HTML reflecting official La Rayonne markup, including the
artist headings for multiple future shows. No network, no private approvals,
no addition to VERIFIER_SPECS, no production writes.
"""
from __future__ import annotations

import datetime as dt
import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import discover
import generic_visible_bill as html_bill
import official_recheck
import triage
from verifier_contract import VERIFIER_SPECS

TODAY = dt.date(2026, 11, 19)
SOURCE = {
    "name": "La Rayonne", "city": "Villeurbanne", "department": "69",
    "url": "https://larayonne.org/", "priority": "P1"
}
URL = "https://larayonne.org/evenement/one-evening-show-2027/"


def page(names=("EISBRECHER",), genre="Metal Indus",
         when="samedi 18 septembre 2027", venue="La Rayonne",
         city="Villeurbanne", cancel="", after="", guest=None):
    heading = " + ".join([*names, *([guest] if guest else [])])
    performers = "".join(
        "<h4><strong>► " + name + " – " + genre + " – FRANCE</strong></h4>"
        "<p>" + name + " sur scène</p>"
        for name in names
    )
    return (
        '<html><head><title>Un autre site métal</title></head><body>'
        '<nav><h4>► UNTRUSTED – Death Metal –</h4></nav>'
        '<h1>' + heading + '</h1>'
        '<strong>' + when + '</strong>'
        '<p>à partir de 19h</p>'
        + venue + '<p>7 rue Henri Legay</p><p>69100 ' + city + '</p>'
        + cancel + '<h3>Production officielle présente :</h3>'
        + performers + '<h4>▼ INFOS PRATIQUES</h4>'
        '<p>Ouverture des portes : 18H</p>'
        '<p>Début des concerts : TBA</p>'
        + after + '</body></html>'
    )


def extract(body=None, source=None, url=URL, today=TODAY):
    return html_bill.extract_candidate(
        page() if body is None else body, url,
        SOURCE if source is None else source, today, set())


class FirstPartyVisibleBillDiscoveryTests(unittest.TestCase):
    def test_realistic_single_named_official_event_is_private_only(self):
        row = extract()
        self.assertEqual(row["name"], "EISBRECHER")
        self.assertEqual(row["leadArtist"], "EISBRECHER")
        self.assertEqual(row["classification"], ["Metal Indus"])
        self.assertEqual(row["date"], "2027-09-18")
        self.assertEqual(row["verifiedVenueIdHint"], "la-rayonne")
        self.assertEqual(row["source"], "agenda_officiel_visible_bill")
        self.assertFalse(row["publicationAllowed"])
        self.assertTrue(row["reviewRequired"])
        self.assertTrue(row["officialDetailFound"])
        self.assertEqual(triage.triage(row)["reviewBucket"], "genre_tag_review")
        self.assertEqual(VERIFIER_SPECS["agenda_officiel_visible_bill"].module,
                         "generic_visible_bill")
        with self.assertRaises(ValueError):
            official_recheck.verify(
                triage.triage(row), page(),
                {"events": [], "venues": [], "artists": []}, TODAY)

    def test_reusable_one_two_eight_twenty_and_fifty_two_acts(self):
        for count in (1, 2, 8, 20, 52):
            names = ["ACT %03d" % i for i in range(count)]
            with self.subTest(count=count):
                result = extract(page(tuple(names), genre="Death Metal"))
                self.assertIsNotNone(result)
                self.assertEqual(result["leadArtist"], " + ".join(names))
                self.assertEqual(result["classification"], ["Death Metal"])
                self.assertEqual(result["name"], " + ".join(names))
                self.assertFalse(result["publicationAllowed"])

    def test_many_distinct_official_concerts_without_event_specific_logic(self):
        for title, genre, date in (
            ("EISBRECHER", "Metal Indus", "samedi 18 septembre 2027"),
            ("ZEBRAHEAD", "Punk Rock", "samedi 21 novembre 2026"),
            ("REVOCATION", "Death Metal technique", "dimanche 25 avril 2027"),
        ):
            with self.subTest(title=title):
                item = extract(page((title,), genre=genre, when=date))
                self.assertEqual(item["leadArtist"], title)
                self.assertIn(genre, item["classification"])

    def test_surprise_guest_remains_unknown_not_a_new_band(self):
        item = extract(page(("ZEBRAHEAD",), genre="Punk Rock",
                            guest="Guest surprise"))
        self.assertEqual(item["leadArtist"], "ZEBRAHEAD")
        self.assertEqual(item["unannouncedSupportLabel"], "Guest surprise")
        self.assertNotIn("Guest surprise", item["leadArtist"])

    def test_explicit_page_cancellation_is_not_sold_out(self):
        self.assertIsNone(extract(page(cancel="<p>Concert annulé</p>")))
        self.assertIsNone(extract(page(cancel="<p>Date reportée</p>")))
        self.assertIsNotNone(extract(page(cancel="<p>Complet, sold out</p>")))

    def test_no_genre_from_bio_recommendations_or_navigation(self):
        for test_page in (
            page(genre="Rock"),
            page().replace(
                "<h4><strong>► EISBRECHER – Metal Indus – FRANCE</strong></h4>",
                "<p>EISBRECHER est connu pour son Metal Indus</p>"),
            page().replace(
                "<h4><strong>► EISBRECHER – Metal Indus – FRANCE</strong></h4>",
                "<h2>Vous aimerez aussi</h2>"
                "<h4><strong>► EISBRECHER – Metal Indus – FRANCE</strong></h4>"),
        ):
            with self.subTest(html=test_page[-140:]):
                self.assertIsNone(extract(test_page))

    def test_invalid_domain_page_url_room_and_city_are_quarantined(self):
        self.assertIsNone(extract(url="https://evil.example/evenement/one-evening-show-2027/"))
        self.assertIsNone(extract(url="https://larayonne.org/agenda/"))
        self.assertIsNone(extract(url=URL + "?tracking=1"))
        self.assertIsNone(extract(source={**SOURCE, "city": "Paris"}))
        self.assertIsNone(extract(page(venue="Autre Salle")))
        self.assertIsNone(extract(page(city="Lyon")))
        self.assertIsNone(extract(source={**SOURCE, "name": "Faux Concert Hall"}))

    def test_date_must_be_first_visible_show_day_not_sale_day(self):
        self.assertIsNone(extract(page(when="samedi 18 septembre")))
        self.assertIsNone(extract(page(when="samedi 18 septembre 2025")))
        self.assertIsNone(extract(page(when="samedi 18 septembre 2027").replace(
            "<strong>samedi 18 septembre 2027</strong>",
            "<strong>mercredi 19 mai 2027</strong>"
            "<strong>samedi 18 septembre 2027</strong>")))
        self.assertIsNone(extract(page().replace(
            "<h1>EISBRECHER</h1>", "<h1>EISBRECHER</h1><h1>Un autre concert</h1>")))

    def test_partial_missing_or_extra_bill_fails_closed(self):
        two = page(("ACT ONE", "ACT TWO"), genre="Death Metal")
        self.assertIsNotNone(extract(two))
        missing = two.replace(
            "<h4><strong>► ACT TWO – Death Metal – FRANCE</strong></h4>", "")
        self.assertIsNone(extract(missing))
        extra = two.replace(
            "<h4>▼ INFOS PRATIQUES</h4>",
            "<h4>► ACT THREE – Death Metal – FRANCE</h4>"
            "<h4>▼ INFOS PRATIQUES</h4>")
        self.assertIsNone(extract(extra))
        self.assertIsNone(extract(page(("ACT ONE", "ACT ONE"))))

    def test_no_future_event_can_be_added_by_fake_performer_organization(self):
        misleading = page().replace(
            "<h4><strong>► EISBRECHER – Metal Indus – FRANCE</strong></h4>",
            "<script type='application/ld+json'>"
            '{"@type":"Organization","name":"Organization"}'
            "</script>")
        self.assertIsNone(extract(misleading))

    def test_reviewed_venue_skips_agenda_and_filter_pages_before_finite_probes(self):
        # These listing links all match the old broad EVENT_URL regexp, but
        # cannot satisfy the independently approved individual-event path.
        homepage = (
            '<a href="https://larayonne.org/agenda/">Agenda</a>'
            '<a href="https://larayonne.org/agenda/?type=metal">Metal</a>'
            '<a href="https://larayonne.org/programmation/">Programme</a>'
            '<a href="' + URL + '">Official concert</a>'
        )
        requested = []
        def fetch(url, *args, **kwargs):
            requested.append(url)
            if url == SOURCE["url"]:
                return homepage, url
            if url == URL:
                return page(), url
            raise AssertionError("Generic listing wasted a detail read: " + str(url))

        report = []
        with mock.patch.object(discover, "download", side_effect=fetch), \
             mock.patch.object(discover, "robots_allow", return_value=True), \
             mock.patch.object(discover.feeds, "feed_links",
                               return_value={"rss": [], "ics": []}):
            rows = discover.scan_venues(
                {"venues": [SOURCE]}, set(), TODAY, report, scan_slot=2)
        self.assertEqual(requested, [SOURCE["url"], URL])
        self.assertEqual(report[0]["eventDetailLinksFound"], 1)
        self.assertEqual(report[0]["eventDetailPagesFetched"], 1)
        self.assertEqual(report[0]["htmlVisibleBillLeads"], 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source"], "agenda_officiel_visible_bill")

    def test_unreviewed_sources_cannot_use_generic_event_trust(self):
        unknown = {**SOURCE, "name": "Unreviewed Hall",
                   "url": "https://unreviewed.example/"}
        self.assertIsNone(extract(source=unknown))

    def test_integration_uses_same_three_preexisting_official_http_reads(self):
        # The official homepage lists a genuine first-party event. The
        # previously fetched individual page is reused, with NO extra fetch.
        homepage = '<a href="' + URL + '">Official show</a>'
        requested = []
        def fetch(url, *args, **kwargs):
            requested.append(url)
            if url == SOURCE["url"]:
                return homepage, url
            if url == URL:
                return page(), url
            raise AssertionError("Unexpected network request: " + str(url))
        report = []
        with mock.patch.object(discover, "download", side_effect=fetch), \
             mock.patch.object(discover, "robots_allow", return_value=True), \
             mock.patch.object(discover.feeds, "feed_links",
                               return_value={"rss": [], "ics": []}):
            rows = discover.scan_venues(
                {"venues": [SOURCE]}, set(), TODAY, report, scan_slot=0)
        self.assertEqual(requested, [SOURCE["url"], URL])
        self.assertEqual(report[0]["htmlVisibleBillLeads"], 1)
        self.assertEqual(report[0]["candidatesDetected"], 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source"], "agenda_officiel_visible_bill")


if __name__ == "__main__":
    unittest.main()
