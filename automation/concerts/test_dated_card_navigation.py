"""Navigation from dated first-party HTML event cards without schema.org."""
from __future__ import annotations

import datetime as dt
import unittest

import discover

DAY = dt.date(2026, 11, 20)
AGENDA = "https://venue-officielle.example/agenda/"
DETAIL = "https://venue-officielle.example/groupes-inconnus-sur-la-place-2027/"


def card(url=DETAIL, date="2027-06-18", title="Deux groupes inconnus + Guest surprise"):
    return (
        f'<a href="{url}"><time datetime="{date}">18 juin</time>'
        f'<strong>{title}</strong></a>'
    )


class FirstPartyDatedCardNavigationTests(unittest.TestCase):
    def test_no_jsonld_no_url_keyword_new_artists_are_navigable(self):
        doc = "<h1>Programmation</h1>" + card()
        self.assertFalse(discover.EVENT_URL.search(
            "/groupes-inconnus-sur-la-place-2027/"))
        self.assertEqual(
            discover.linked_first_party_event_urls(doc, AGENDA, DAY), [])
        self.assertEqual(
            discover.linked_first_party_dated_card_urls(doc, AGENDA, DAY),
            [DETAIL])

    def test_relative_links_are_normalized_only_within_first_party_host(self):
        doc = card("/groupes-inconnus-sur-la-place-2027/")
        self.assertEqual(
            discover.linked_first_party_dated_card_urls(doc, AGENDA, DAY),
            [DETAIL])
        self.assertEqual(discover.linked_first_party_dated_card_urls(
            card("https://venue-officielle.example/programme/autre-groupe/"),
            AGENDA, DAY),
            ["https://venue-officielle.example/programme/autre-groupe/"])

    def test_no_tracking_credentials_external_or_unsafe_protocols(self):
        bad = [
            "https://tickets.example/events/show/",
            "http://venue-officielle.example/2027-musique/",
            "https://venue-officielle.example/2027-musique/?tracking=1",
            "https://venue-officielle.example/2027-musique/#section",
            "https://evil.example@venue-officielle.example/2027-musique/",
            "javascript:alert(1)",
            "//foreign.example/concert/",
            "/agenda/",
        ]
        for url in bad:
            with self.subTest(url=url):
                self.assertEqual(
                    discover.linked_first_party_dated_card_urls(
                        card(url), AGENDA, DAY), [])

    def test_cancelled_expired_unlabelled_and_conflicting_dates_are_held(self):
        samples = [
            card(date="2025-11-20"),
            card(title="Concert annulé"),
            '<a href="' + DETAIL + '"><time datetime="2027-06-18">'
            'Juin</time><time datetime="2027-06-19">Juin</time> Groupe</a>',
            '<a href="' + DETAIL + '"><time datetime="2027-06-18">'
            '18</time></a>',
            '<a href="' + DETAIL + '">Groupe sans date</a>',
        ]
        for sample in samples:
            with self.subTest(sample=sample[:70]):
                self.assertEqual(
                    discover.linked_first_party_dated_card_urls(
                        sample, AGENDA, DAY), [])

    def test_hidden_and_script_links_never_qualify(self):
        doc = (
            '<a hidden href="' + DETAIL + '">'
            '<time datetime="2027-06-18"></time> Groupe</a>'
            '<a aria-hidden="true" href="' + DETAIL + '">'
            '<time datetime="2027-06-18"></time> Groupe</a>'
            '<a style="display:none" href="' + DETAIL + '">'
            '<time datetime="2027-06-18"></time> Groupe</a>'
            '<script><a href="' + DETAIL + '">'
            '<time datetime="2027-06-18"></time> Groupe</a></script>'
        )
        self.assertEqual(
            discover.linked_first_party_dated_card_urls(doc, AGENDA, DAY), [])

    def test_duplicate_cards_and_daily_rotation_do_not_raise_request_limit(self):
        urls = [
            f"https://venue-officielle.example/metal-nouveau-{i:02d}-2027/"
            for i in range(17)
        ]
        doc = "".join(card(url, title=f"Groupe inconnu {i}")
                      for i, url in enumerate(urls))
        found = discover.linked_first_party_dated_card_urls(
            doc + card(urls[0], title="Groupe inconnu 0"), AGENDA, DAY)
        self.assertEqual(found, urls)
        visited = set()
        for delta in (0, 1):
            for slot in range(3):
                chosen = discover.select_generic_official_detail_links(
                    found, DAY + dt.timedelta(days=delta), slot, limit=3)
                self.assertLessEqual(len(chosen), 3)
                visited.update(chosen)
        self.assertEqual(visited, set(urls))

    def test_navigation_is_not_authority_or_a_publisher_approval(self):
        links = discover.linked_first_party_dated_card_urls(
            card(), AGENDA, DAY)
        self.assertEqual(links, [DETAIL])
        self.assertTrue(all(isinstance(link, str) for link in links))
        self.assertEqual(
            discover.linked_first_party_dated_card_urls(
                card(), AGENDA, dt.datetime(2026, 11, 20)), [])
        self.assertEqual(
            discover.linked_first_party_dated_card_urls(
                card(), AGENDA, None), [])


if __name__ == "__main__":
    unittest.main()
