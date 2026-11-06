"""Brin de Zinc secondary ticketing source — offline safety tests."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import brin_de_zinc_adapter as b

VENUE = {"name": "Le Brin de Zinc", "city": "Barberaz",
         "department": "73", "url": "https://brindezinc.fr/"}
URL = "https://www.billetweb.fr/multi_event.php?multi=11236"
def card(name, date, location="Le Brin de Zinc, Route de la Peysse, Barberaz, France"):
    return f"<p>{name}<span>More info</span></p><p>{date}</p><p>{location}</p><p>More information Hide description Learn more</p>"
HEADER = "<header>Brin de Zinc</header><p>Learn more</p>"
DATE = "Thu Nov 05, 2026 from 08:30 PM to 12:00 AM"

class BrinTests(unittest.TestCase):
    def test_officially_linked_ticket_lead_only(self):
        html = HEADER + card("NOVERIA x TARCHON FIST x WEDINGOTH (Power Metal Progressif • Italie x France)", DATE)
        leads = b.candidates(html, URL, VENUE, "2026-11-02")
        self.assertEqual(len(leads), 1)
        lead = leads[0]
        self.assertEqual(lead["date"], "2026-11-05")
        self.assertEqual(lead["localTime"], "20:30")
        self.assertEqual(lead["leadArtist"], "NOVERIA")
        self.assertEqual(lead["ticketStatus"], "not_verified")
        self.assertTrue(lead["thirdPartyOnly"])
        self.assertTrue(lead["reviewRequired"])
        self.assertFalse(lead["publicationAllowed"])

    def test_non_metal_non_concert_and_other_venue_rejected(self):
        examples = (
            card("COME (Rock • Grèce)", DATE),
            card("Abonnement Brin de Zinc 2026 (Metal)", DATE),
            card("Atelier chant metal (Metal)", DATE),
            card("Noveria (Power Metal)", DATE, "Autre salle, Barberaz, France"),
            card("Noveria (Power Metal)", "Thu Nov 05 from 08:30 PM to 12:00 AM"),
        )
        for item in examples:
            with self.subTest(item=item):
                self.assertEqual(b.candidates(HEADER + item, URL, VENUE, "2026-11-02"), [])

    def test_sold_out_and_duplicates_stay_review_only(self):
        html = HEADER + card("COMPLET • MOSCOW DEATH BRIGADE (Punk • Rap • Techno)",
                             "Sun Nov 15, 2026 from 07:30 PM to 12:00 AM")
        lead = b.candidates(html+html, URL, VENUE, "2026-11-02")
        self.assertEqual(len(lead), 1)
        self.assertEqual(lead[0]["ticketStatus"], "sold_out")
        self.assertFalse(lead[0]["publicationAllowed"])

    def test_wrong_weekday_date_and_past_rejected(self):
        for d in ("Wed Nov 05, 2026 from 08:30 PM to 12:00 AM",
                  "Thu Nov 05, 2026 from 00:30 PM to 12:00 AM",
                  "Thu Nov 05, 2026 from 08:80 PM to 12:00 AM"):
            with self.subTest(d=d):
                self.assertEqual(b.candidates(HEADER+card("Noveria (Metal)", d),
                                              URL,VENUE,"2026-11-02"), [])
        self.assertEqual(b.candidates(HEADER+card("Noveria (Metal)",DATE), URL,VENUE,"2027-11-02"), [])

    def test_wrong_source_identity_and_missing_heading_blocked(self):
        html = HEADER + card("Noveria (Metal)",DATE)
        for wrong in ("https://evil.example/multi_event.php?multi=11236",
                      "https://www.billetweb.fr/multi_event.php?multi=11237",
                      "http://www.billetweb.fr/multi_event.php?multi=11236"):
            with self.subTest(wrong=wrong), self.assertRaises(ValueError):
                b.candidates(html,wrong,VENUE,"2026-11-02")
        with self.assertRaises(ValueError):
            b.candidates(html,URL,dict(VENUE,city="Nantes"),"2026-11-02")
        with self.assertRaises(ValueError):
            b.candidates(card("Noveria (Metal)",DATE),URL,VENUE,"2026-11-02")

    def test_only_explicit_genre_in_title_counts(self):
        html = HEADER + card("Ancient Settlers (Death-Metal Mélodique • Metalcore)",
                             "Thu Nov 12, 2026 from 08:30 PM to 12:00 AM")
        self.assertEqual(len(b.candidates(html,URL,VENUE,"2026-11-02")),1)

if __name__ == "__main__":
    unittest.main()
