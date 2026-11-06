"""Adaptateur salle le Rex : tests de formats réels et rejet hors métal."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import venue_adapters as v

VENUE = {"name":"Le Rex", "city":"Toulouse", "department":"31"}
URL = "https://www.lerextoulouse.com/fr/programmation/rendez-vous/"

HTML = """
<ul>
<li><a href="/fr/programmation/the-browning-et-within-destruction/">billet</a>
ven 6 novembre 2026 - 19H30
The Browning &amp; Within Destruction &amp; Abbie Falls (metal)
<ul><li><strong>28,80 € Prévente</strong></li></ul></li>
<li>jeu 5 novembre 2026 - 19H30
7WEEKS &amp; Guest (rock|stoner)
<ul><li>21 € Prévente</li></ul></li>
<li>sam 7 novembre 2026 - 23H55
Bitch Party (electro|pop)</li>
<li>sam 14 novembre 2026 - 23H55
NIVK All Night Long (hard-techno|techno)</li>
<li>jeu 11 février 2027 - 19H30
Shred Fest : Obscura &amp; Pestilence (death-metal|metal|progressive)</li>
<li>ven 19 mars 2027 - 19H30
HOULE + CÂN BARDD + GALIBOT (black-metal)</li>
</ul>
"""


class VenueAdapterTests(unittest.TestCase):
    def test_rex_metal_and_stoner_only(self):
        rows=v.rex_candidates(HTML,URL,VENUE,"2026-11-01")
        self.assertEqual(len(rows),4)
        self.assertEqual(rows[0]["date"],"2026-11-06")
        self.assertEqual(rows[0]["name"],"The Browning & Within Destruction & Abbie Falls")
        self.assertFalse(rows[0]["publicationAllowed"])
        self.assertTrue(rows[0]["sourceUrl"].startswith("https://www.lerextoulouse.com"))
        self.assertEqual(rows[1]["date"],"2026-11-05")

    def test_genre_filters_techno(self):
        self.assertFalse(v.is_metal_genre("hard-techno|techno"))
        self.assertFalse(v.is_metal_genre("rap|trap"))
        self.assertTrue(v.is_metal_genre("black-metal|experimental"))
        self.assertTrue(v.is_metal_genre("rock|stoner"))

    def test_no_past_date(self):
        self.assertEqual(v.rex_candidates(HTML,URL,VENUE,"2027-04-01"),[])

    def test_bad_date_does_not_crash(self):
        page="<li>lun 99 novembre 2027 - 20H00 Bad (metal)</li>"
        self.assertEqual(v.rex_candidates(page,URL,VENUE,"2026-11-01"),[])

    def test_deduplicated_html(self):
        line="<li>ven 19 mars 2027 - 19H30 HOULE + CÂN BARDD + GALIBOT (black-metal)</li>"
        self.assertEqual(len(v.rex_candidates(line+line,URL,VENUE,"2026-11-01")),1)

if __name__ == "__main__":
    unittest.main()
