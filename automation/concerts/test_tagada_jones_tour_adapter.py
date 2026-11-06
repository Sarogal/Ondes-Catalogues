"""Tagada Jones : découverte privée de dates françaises, sans réseau."""
import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tagada_jones_tour_adapter as adapter
import artist_tour_discovery as discovery

DAY = dt.date(2026, 11, 5)
SOURCE = {
    "artistId": "tagada-jones",
    "sourceRole": "artist_official",
    "adapter": "tagada_jones_official_tour",
    "url": "https://www.tagadajones.com/new/",
    "enabled": True,
}
CATALOG = {
    "schemaVersion": 1, "artists": [{"id": "tagada-jones", "name": "Tagada Jones"}],
    "venues": [{"id": "le-bikini-ramonville-saint-agne",
                "name": "Le Bikini", "city": "Ramonville-Saint-Agne"}],
    "events": [],
}
HTML = """<main><h1>Tagada Jones</h1><h2>Dates 2026–2027</h2>
<article><p>06.11.2026</p><p>VENDREDI NOVEMBRE 2026</p> |
<p>GENEVE (CH) - L’Alhambra - Recluses Fest</p>Ticket</article>
<article><p>07.11.2026</p><p>SAMEDI NOVEMBRE 2026</p> |
<p>ST DIZIER (52) - Les Fuseaux</p>Ticket</article>
<article><p>13.11.2026</p><p>VENDREDI NOVEMBRE 2026</p> |
<p>TOULOUSE (31) - Le Bikini</p>Ticket</article>
<article><p>19.11.2026</p><p>JEUDI NOVEMBRE 2026</p> |
<p>BOULOGNE/MER (62) - Le Carre Sam</p>Ticket</article>
<article><p>20.11.2026</p><p>VENDREDI NOVEMBRE 2026</p> |
<p>PARIS (75) - L’Olympia</p>Ticket</article>
<article><p>06.02.2027</p><p>SAMEDI FÉVRIER 2027</p> |
<p>LUISANT (28) - Festival L’Paille à Sonique</p>Ticket</article>
<article><p>27.03.2027</p><p>SAMEDI MARS 2027</p> |
<p>FONTENAY-LE-COMTE (85) - Ragefest</p>Ticket</article>
<article><p>28.05.2027</p><p>VENDREDI MAI 2027</p> |
<p>ALENÇON (61) - La Luciole</p>Ticket</article>
<script>const spoof="18.12.2027 ROUEN (76) - Fake Hall";</script></main>"""


class TagadaJonesOfficialTourTests(unittest.TestCase):
    def test_only_complete_future_dates_and_department(self):
        self.assertEqual(adapter.official_tour_entries(HTML, DAY), [
            ("2026-11-07", "ST DIZIER", "Les Fuseaux", "52"),
            ("2026-11-13", "TOULOUSE", "Le Bikini", "31"),
            ("2026-11-19", "BOULOGNE/MER", "Le Carre Sam", "62"),
            ("2026-11-20", "PARIS", "L’Olympia", "75"),
            ("2027-05-28", "ALENÇON", "La Luciole", "61"),
        ])

    def test_invalid_country_festivals_dates_and_broken_page(self):
        for value in ("31.02.2027", "07.11", "7.11.2026", "07.13.2026",
                      "07.11.20a6"):
            self.assertIsNone(adapter.parse_date(value))
        self.assertEqual(adapter.official_tour_entries(
            HTML.replace("<h1>Tagada Jones</h1>", "<h1>Autre groupe</h1>"),
            DAY), [])
        self.assertEqual(adapter.official_tour_entries(
            HTML.replace("<h2>Dates 2026–2027</h2>", "<h2>Actualités</h2>"),
            DAY), [])
        self.assertNotIn("GENEVE", str(adapter.official_tour_entries(HTML, DAY)))
        self.assertNotIn("LUISANT", str(adapter.official_tour_entries(HTML, DAY)))

    def test_fragmented_location_and_no_cross_date_pairing(self):
        fragmented = HTML.replace("ST DIZIER (52) - Les Fuseaux",
            "<span>ST DIZIER</span><span>(52)</span><span> - Les Fuseaux</span>")
        self.assertEqual(adapter.official_tour_entries(fragmented, DAY),
                         adapter.official_tour_entries(HTML, DAY))
        incomplete = """<h1>Tagada Jones</h1><h2>Dates 2026–2027</h2>
        <p>20.12.2026</p><p>SOISSONS (02)</p>
        <p>21.12.2026</p><p>LAON (02) - La Salle</p>"""
        self.assertEqual(adapter.official_tour_entries(incomplete, DAY),
                         [("2026-12-21", "LAON", "La Salle", "02")])

    def test_review_only_and_strict_source_identity(self):
        rows = adapter.candidates(HTML, SOURCE, "Tagada Jones", CATALOG, DAY)
        self.assertEqual(len(rows), 5)
        self.assertEqual(len({x["candidateId"] for x in rows}), 5)
        self.assertTrue(all(x["reviewRequired"] and
                            not x["publicationAllowed"] for x in rows))
        self.assertTrue(all(x["countryToVerify"] and x["cityToVerify"] and
                            x["venueAddressToVerify"] and
                            x["coordinatesToVerify"] for x in rows))
        self.assertTrue(all("time" not in x and "latitude" not in x and
                            "artistIds" not in x for x in rows))
        for wrong in (dict(SOURCE, artistId="other"),
                      dict(SOURCE, sourceRole="aggregator"),
                      dict(SOURCE, adapter="wrong"),
                      dict(SOURCE, url="https://other.example/")):
            with self.assertRaises(ValueError):
                adapter.candidates(HTML, wrong, "Tagada Jones", CATALOG, DAY)

    def test_scan_is_discovery_only(self):
        config = {"schema": "grossesondes.concert.artist_tour_sources.v1",
                  "sources": [SOURCE]}
        rows, checks = discovery.scan(CATALOG, config, DAY, max_sources=1,
            fetch=lambda url, **kw: (HTML, url),
            robots=lambda url, cache: True)
        self.assertEqual(len(rows), 5)
        self.assertEqual(checks[0]["status"], "parsed_tour")
        self.assertEqual(checks[0]["candidateCount"], 5)
        self.assertEqual(checks[0]["officialTourEntries"], 5)
        self.assertTrue(all(not x["publicationAllowed"] for x in rows))


if __name__ == "__main__":
    unittest.main()
