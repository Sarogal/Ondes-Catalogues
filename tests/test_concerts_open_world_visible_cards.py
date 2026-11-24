"""Universal HTML-card fixtures: real-world shapes, never venue-specific code."""
import datetime as dt
import unittest

from automation.concerts import open_world_visible_cards as cards

DAY = dt.date(2026, 11, 24)


def page(label, genre, date, room="Trabendo", city="Paris", pre="", after=""):
    return (
        "<html><body><h1>" + room + "</h1>" +
        "<h2>Concerts de la saison</h2>" + pre +
        "<p>" + date + "</p><p>" + label + "</p>" +
        "<p>concert ― " + genre + "</p>" +
        "<p>→ " + room + " - Salle de concert</p>" +
        "<p>Ouverture des portes 19:00</p>" + after +
        "<section>Parc de la Villette 75019 " + city +
        "</section></body></html>")


class OpenWorldVisibleCardTests(unittest.TestCase):
    def test_official_html_paragraphs_with_full_date_named_act_and_genre(self):
        html = page("Klone", "Metal", "22 ― avril 2027")
        events = cards.extract(html, "Le Trabendo", "Paris", DAY)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["artists"], ["Klone"])
        self.assertEqual(events[0]["date"], "2027-04-22")
        self.assertEqual(events[0]["genre"], "Metal")
        self.assertNotIn("time", events[0])

    def test_recommendation_panel_is_not_joined_to_main_concert(self):
        rec = ('<section><p>Vous devriez aimer</p>'
               '<h2>03 ― février 2027</h2><h5>Metalcore</h5>'
               '<h3>Whitechapel</h3></section>')
        text = page("Wage War", "Metalcore", "22 ― janvier 2027", after=rec)
        events = cards.extract(text, "Trabendo", "Paris", DAY)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["artists"], ["Wage War"])
        self.assertEqual(events[0]["date"], "2027-01-22")

    def test_generic_other_room_multiple_artists_without_inherited_genres(self):
        artists = " + ".join("Metal Band " + str(i) for i in range(1, 9))
        html = page(artists, "Death Metal", "12 ― mars 2027",
                    room="Nouvelle Scène", city="Nantes")
        events = cards.extract(html, "La Nouvelle Scène", "Nantes", DAY)
        self.assertEqual(len(events), 1)
        self.assertEqual(len(events[0]["artists"]), 8)
        self.assertEqual(events[0]["genre"], "Death Metal")
        self.assertNotIn("artistGenres", events[0])

    def test_wrong_room_or_absent_city_yields_no_card(self):
        html = page("Klone", "Metal", "22 ― avril 2027")
        self.assertEqual(cards.extract(html, "Autre Salle", "Paris", DAY), [])
        self.assertEqual(cards.extract(html, "Trabendo", "Lyon", DAY), [])

    def test_expired_ambiguous_cancelled_or_unqualified_genre_held(self):
        past = page("Klone", "Metal", "22 ― avril 2025")
        self.assertEqual(cards.extract(past, "Trabendo", "Paris", DAY), [])
        ambiguous = page("Klone", "Metal",
                         "22 ― avril 2027 et 23 avril 2027")
        self.assertEqual(cards.extract(ambiguous, "Trabendo", "Paris", DAY), [])
        cancelled = page("Klone", "Metal", "22 ― avril 2027",
                         pre="<p>Concert annulé</p>")
        self.assertEqual(cards.extract(cancelled, "Trabendo", "Paris", DAY), [])
        unrelated = page("Klone", "Pop", "22 ― avril 2027")
        self.assertEqual(cards.extract(unrelated, "Trabendo", "Paris", DAY), [])

    def test_primary_detail_is_not_a_listing(self):
        listing = page("Klone", "Metal", "22 ― avril 2027")
        detail = listing.replace("<h1>Trabendo</h1>", "<h1>Klone</h1>")
        self.assertIsNone(cards.verified_detail(listing, "Trabendo", "Paris", "2027-04-22"))
        self.assertEqual(cards.verified_detail(detail, "Le Trabendo", "Paris", "2027-04-22"),
                         (["Klone"], ["Metal"]))
        for variant in (
            detail.replace("Paris", "Lyon"),
            detail.replace("22 ― avril", "23 ― avril"),
            detail.replace("concert ― Metal", "concert ― Pop"),
            detail.replace("<p>Klone</p>", "<p>Autre Groupe</p>"),
            detail.replace("→ Trabendo", "→ Autre Salle"),
            detail.replace("<p>Ouverture", "<p>Concert annulé</p><p>Ouverture"),
        ):
            self.assertIsNone(cards.verified_detail(variant, "Trabendo", "Paris", "2027-04-22"))

    def test_strict_input_bounds(self):
        html = page("Klone", "Metal", "22 ― avril 2027")
        self.assertEqual(cards.extract(html, "Trabendo", "Paris",
                                       dt.datetime(2026, 11, 24)), [])
        self.assertEqual(cards.extract("X" * 1_000_001,
                                        "Trabendo", "Paris", DAY), [])


if __name__ == "__main__":
    unittest.main()
