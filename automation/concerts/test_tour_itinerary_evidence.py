"""An official tour-wide calendar is only a non-authoritative source clue."""
from __future__ import annotations

import unittest
import tour_itinerary_evidence as probe

SITE_HTML = """<html><main>
<p><strong>Touring metal festival 2027</strong>: 39 shows and no days off.
Obscura, Pestilence, Cryptic Shift, Thus and DVRK.</p>
<p>From January 20th to February 27th, 2027 — European tour.</p>
<p>
1/20 🇩🇪 Aschaffenburg – Colos-Saal<br/>
2/3 🇫🇷 Grenoble – L’Ilyade<br/>
2/4 🇫🇷 Montpellier – Victoire 2<br/>
2/11 🇫🇷 Toulouse – Le Rex<br/>
2/12 🇫🇷 Limoges – CCO John Lennon<br/>
2/13 🇫🇷 Angers – Le Chabada<br/>
2/14 🇫🇷 Paris – Petit Bain<br/>
2/22 🇫🇷 Nancy – L’Autre Canal<br/>
2/23 🇳🇱 Leeuwarden – Neushoorn
</p>
</main></html>"""

SCHEDULES = [
    ("2027-02-03", "Seyssinet-Pariset (Grenoble)",
     "L’Ilyade, Seyssinet-Pariset (Grenoble)"),
    ("2027-02-04", "Saint-Jean-de-Védas (Montpellier)",
     "Victoire 2, 2 rue Théophraste-Renaudot, 34430 Saint-Jean-de-Védas"),
    ("2027-02-11", "Toulouse", "Le Rex, 15 avenue Honoré-Serres, Toulouse"),
    ("2027-02-12", "Limoges",
     "Centre culturel municipal John-Lennon, 41 ter rue de Feytiat, Limoges"),
    ("2027-02-13", "Angers", "Le Chabada, 56 boulevard du Doyenné"),
    ("2027-02-14", "Paris", "Petit Bain, 7 port de la Gare, Paris"),
    ("2027-02-22", "Nancy", "L’Autre Canal, Nancy"),
]


class TourItineraryEvidenceTests(unittest.TestCase):
    def test_seven_general_touring_stops_with_slight_venue_alias(self):
        for day, city, venue in SCHEDULES:
            with self.subTest(day=day, city=city):
                self.assertTrue(probe.matching_tour_stop(
                    SITE_HTML, day, city, venue))

    def test_must_have_correct_day_named_city_and_venue(self):
        for day, city, venue in (
            ("2027-02-05", "Montpellier", "Victoire 2"),
            ("2027-02-04", "Nîmes", "Victoire 2"),
            ("2027-02-04", "Montpellier", "Salle inconnue"),
            ("2027-02-04", "Montpellier", "Le Rex"),
            ("2026-02-04", "Montpellier", "Victoire 2"),
            ("2028-02-04", "Montpellier", "Victoire 2"),
        ):
            with self.subTest(day=day, city=city):
                self.assertFalse(probe.matching_tour_stop(
                    SITE_HTML, day, city, venue))

    def test_unscoped_tour_words_and_year_cannot_prove_a_date(self):
        for body in (
            SITE_HTML.replace("Touring", "Annual").replace(
                "European tour", "European itinerary"),
            SITE_HTML.replace("2027", "2028"),
            SITE_HTML.replace("39 shows", "39 meetings").replace(
                "European tour", "European meetings"),
        ):
            with self.subTest(body=body[:85]):
                self.assertFalse(probe.matching_tour_stop(
                    body, "2027-02-04", "Montpellier", "Victoire 2"))

    def test_hidden_markup_cannot_invent_date_venue(self):
        body = SITE_HTML.replace(
            "2/4 🇫🇷 Montpellier – Victoire 2<br/>",
            '<div hidden>2/4 🇫🇷 Montpellier – Victoire 2</div>')
        self.assertFalse(probe.matching_tour_stop(
            body, "2027-02-04", "Montpellier", "Victoire 2"))
        body = SITE_HTML.replace(
            "2/4 🇫🇷 Montpellier – Victoire 2<br/>",
            '<script>2/4 🇫🇷 Montpellier – Victoire 2</script>')
        self.assertFalse(probe.matching_tour_stop(
            body, "2027-02-04", "Montpellier", "Victoire 2"))
        body = SITE_HTML.replace(
            "2/4 🇫🇷 Montpellier – Victoire 2<br/>",
            '<div class="visually-hidden">'
            '2/4 🇫🇷 Montpellier – Victoire 2</div>')
        self.assertFalse(probe.matching_tour_stop(
            body, "2027-02-04", "Montpellier", "Victoire 2"))

    def test_latest_visible_year_before_itinerary_must_match(self):
        misleading = SITE_HTML.replace(
            "<p>\n1/20 🇩🇪 Aschaffenburg",
            "<p>2026 world tour.</p><p>\n1/20 🇩🇪 Aschaffenburg")
        self.assertFalse(probe.matching_tour_stop(
            misleading, "2027-02-04", "Montpellier", "Victoire 2"))

    def test_ambiguous_numeric_date_order_requires_disambiguation(self):
        body = """<html><p>2027 touring metal festivals, 39 shows across Europe.</p>
<p>2/3 🇫🇷 Grenoble – L’Ilyade<br/>
2/4 🇫🇷 Montpellier – Victoire 2</p></html>"""
        self.assertFalse(probe.matching_tour_stop(
            body, "2027-02-04", "Montpellier", "Victoire 2"))
        # Explicit 20/1 distinguishes European day/month instead.
        body = """<html><p>2027 touring metal festivals, 39 shows across Europe.</p>
<p>20/1 🇩🇪 Aschaffenburg – Colos-Saal<br/>
4/2 🇫🇷 Montpellier – Victoire 2</p></html>"""
        self.assertTrue(probe.matching_tour_stop(
            body, "2027-02-04", "Montpellier", "Victoire 2"))
        body = body.replace("4/2", "2/4")
        self.assertFalse(probe.matching_tour_stop(
            body, "2027-02-04", "Montpellier", "Victoire 2"))

    def test_two_conflicting_venues_on_same_day_are_ambiguous(self):
        body = SITE_HTML.replace(
            "2/4 🇫🇷 Montpellier – Victoire 2<br/>",
            "2/4 🇫🇷 Montpellier – Victoire 2<br/>"
            "2/4 🇫🇷 Montpellier – Une autre salle<br/>")
        self.assertFalse(probe.matching_tour_stop(
            body, "2027-02-04", "Montpellier", "Victoire 2"))

    def test_no_french_marker_no_french_tour_evidence(self):
        body = SITE_HTML.replace(
            "2/4 🇫🇷 Montpellier – Victoire 2",
            "2/4 🇩🇪 Montpellier – Victoire 2")
        self.assertFalse(probe.matching_tour_stop(
            body, "2027-02-04", "Montpellier", "Victoire 2"))

    def test_html_and_date_inputs_are_bounded(self):
        for html in ("", SITE_HTML * 1000, None, 42):
            self.assertFalse(probe.matching_tour_stop(
                html, "2027-02-04", "Montpellier", "Victoire 2"))
        self.assertFalse(probe.matching_tour_stop(
            SITE_HTML, "27-02-04", "Montpellier", "Victoire 2"))
        self.assertFalse(probe.matching_tour_stop(
            SITE_HTML, "2027-02-04", "", "Victoire 2"))
        self.assertFalse(probe.matching_tour_stop(
            SITE_HTML, "2027-02-04", "Montpellier", ""))


if __name__ == "__main__":
    unittest.main()
