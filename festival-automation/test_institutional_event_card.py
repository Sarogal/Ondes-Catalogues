"""Bind a single municipal concert date to its exact named linked card."""
from datetime import date
from unittest import TestCase, main

from institutional_event_card import exact_event_card_day, parse_exact_time

INDEX = "https://sortir.limoges.fr/agenda?keys=festival"
SPEC = {
    "title": "Shred Fest 2027", "year": 2027,
    "index_page": INDEX,
    "url": "https://sortir.limoges.fr/agenda/shred-fest-2027",
}
CARD = ('<main><article><p>Du <time>12 Fév 2027</time></p>'
        '<p>Musique / Concert</p><h2>'
        '<a href="/agenda/shred-fest-2027">Shred Fest 2027</a></h2>'
        '<p>Lieu CCM John-Lennon</p></article></main>')


class MunicipalEventCardTests(TestCase):
    def test_real_french_abbreviated_date_and_exact_link(self):
        self.assertEqual(
            exact_event_card_day(CARD, SPEC), date(2027, 2, 12))
        self.assertEqual(parse_exact_time("\n12\nFév\n2027\n"),
                         date(2027, 2, 12))
        self.assertEqual(parse_exact_time("incorrect", "2027-02-12"),
                         date(2027, 2, 12))

    def test_card_must_link_this_named_detail_on_reviewed_host(self):
        for different in (
            CARD.replace("/agenda/shred-fest-2027",
                         "/agenda/another-event-2027"),
            CARD.replace("Shred Fest 2027</a>", "Unknown Fest 2027</a>"),
            CARD.replace('href="/agenda/shred-fest-2027"',
                         'href="https://evil.example/private"'),
        ):
            with self.subTest(different=different[:100]):
                self.assertIsNone(exact_event_card_day(different, SPEC))

    def test_other_dates_and_multiday_event_card_cannot_supply_a_day(self):
        different = (CARD.replace("12 Fév 2027", "13 Fév 2027")
                      .replace("</article>", "<time>14 Fév 2027</time></article>"))
        self.assertIsNone(exact_event_card_day(different, SPEC))
        ambiguous = CARD.replace("</main>", "") + CARD.replace("<main>", "")
        self.assertIsNone(exact_event_card_day(ambiguous, SPEC))
        bad = CARD.replace("12 Fév 2027", "32 Fév 2027")
        self.assertIsNone(exact_event_card_day(bad, SPEC))

    def test_other_event_links_in_same_card_are_ambiguous(self):
        extra = CARD.replace(
            "</article>", '<a href="/agenda/another-event">Another</a></article>')
        self.assertIsNone(exact_event_card_day(extra, SPEC))
    def test_no_static_date_from_an_unlinked_source(self):
        self.assertIsNone(exact_event_card_day(
            "<main>12 Fév 2027 Shred Fest 2027</main>", SPEC))


if __name__ == "__main__":
    main()
