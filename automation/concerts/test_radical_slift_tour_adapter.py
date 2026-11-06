"""SLIFT / Radical Production : tests hors réseau et sans publication."""
import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import radical_slift_tour_adapter as adapter
import artist_tour_discovery as discovery
import intake_archive

TODAY = dt.date(2026, 11, 6)
SOURCE = {"artistId": "slift", "url": adapter.SOURCE_URL,
          "sourceRole": "promoter_official",
          "adapter": "radical_slift_official_tour", "enabled": True}
CATALOG = {"artists": [{"id": "slift", "name": "Slift"}],
           "events": [], "venues": [
               {"id": "antipode-rennes", "name": "Antipode", "city": "Rennes"}]}
HTML = """<h1>SLIFT</h1><h2>Concerts</h2><h3>Dates à venir</h3>
<p>05 nov. 2026</p><p>PARIS</p>La Maroquinerie
<p>17 nov. 2026</p><p>TOULOUSE</p>Bikini
<p>Première partie : Heeka</p><p>Réserver</p>
<p>18 nov. 2026</p><p>LA ROCHELLE</p>Sirène
<p>19 nov. 2026</p><p>NANTES</p>Stereolux
<p>20 nov. 2026</p><p>RENNES</p>Antipode
<p>23 nov. 2026</p><p>AMSTERDAM (NL)</p>Paradiso
<p>25 nov. 2026</p><p>Berlin (DE)</p>Lido
<p>02 déc. 2026</p><p>LYON</p>Transbordeur
<p>12 mars 2027</p><p>Le Mans</p>Festival Indé*rama
<h3>Dates passées</h3><p>16 nov. 2026</p><p>PARIS</p>Le Trianon"""


class RadicalSliftTests(unittest.TestCase):
    def test_future_french_non_festival_only(self):
        rows = adapter.upcoming(HTML, TODAY)
        self.assertEqual(rows, [
            ("2026-11-17", "TOULOUSE", "Bikini"),
            ("2026-11-18", "LA ROCHELLE", "Sirène"),
            ("2026-11-19", "NANTES", "Stereolux"),
            ("2026-11-20", "RENNES", "Antipode"),
            ("2026-12-02", "LYON", "Transbordeur"),
        ])

    def test_known_venue_and_no_support_claim(self):
        candidates = adapter.candidates(HTML, SOURCE, "Slift", CATALOG, TODAY)
        self.assertEqual(len(candidates), 5)
        rennes = next(x for x in candidates if x["city"] == "RENNES")
        self.assertEqual(rennes["venueIdIfKnown"], "antipode-rennes")
        self.assertFalse(rennes["newVenueToReview"])
        self.assertFalse(any(x["publicationAllowed"] for x in candidates))
        self.assertTrue(all(x["countryToVerify"] and x["lineupToConfirm"]
                            and x["genreToConfirm"] for x in candidates))
        self.assertNotIn("Heeka", str(candidates))
        self.assertNotIn("time", rennes)
        self.assertNotIn("latitude", rennes)

    def test_date_and_heading_and_country_guard(self):
        self.assertIsNone(adapter.parse_date("31 févr. 2027"))
        self.assertIsNone(adapter.parse_date("20 nov."))
        self.assertIsNone(adapter.parse_date("20/11/2026"))
        self.assertEqual(adapter.parse_date("01 févr. 2027"),
                         dt.date(2027, 2, 1))
        self.assertEqual(adapter.upcoming(
            "<h1>SLIFT</h1><p>17 nov. 2026</p><p>PARIS</p>Trianon", TODAY), [])
        self.assertEqual(adapter.upcoming(HTML.replace("<h1>SLIFT</h1>",
                            "<h1>OTHER BAND</h1>"), TODAY), [])

    def test_source_identity_and_duplicate_determinism(self):
        first = adapter.candidates(HTML, SOURCE, "Slift", CATALOG, TODAY)
        self.assertEqual(first, adapter.candidates(HTML, SOURCE, "Slift", CATALOG, TODAY))
        for source in (dict(SOURCE, url="https://fake.invalid/"),
                       dict(SOURCE, sourceRole="aggregator"),
                       dict(SOURCE, artistId="other")):
            with self.subTest(source=source), self.assertRaises(ValueError):
                adapter.candidates(HTML, source, "Slift", CATALOG, TODAY)

    def test_engine_respects_robots_and_preserves_private_triage(self):
        config = {"schema": "grossesondes.concert.artist_tour_sources.v1",
                  "sources": [SOURCE]}
        rows, checks = discovery.scan(
            CATALOG, config, TODAY, max_sources=1, slot=0,
            fetch=lambda u, **kwargs: (HTML, u),
            robots=lambda u, cache: True)
        self.assertEqual(len(rows), 5)
        self.assertEqual(checks[0]["officialTourEntries"], 5)
        self.assertEqual(checks[0]["status"], "parsed_tour")
        report = discovery.build_report(CATALOG, config, TODAY, rows, checks)
        self.assertFalse(report["publicationAllowed"])
        archive, counts = intake_archive.merge(None, report, "2026-11-06T23:15:00Z")
        self.assertEqual(counts["added"], 5)
        self.assertEqual(archive["total"], 5)
        withheld, checks = discovery.scan(
            CATALOG, config, TODAY, max_sources=1, slot=0,
            fetch=lambda u, **kwargs: (_ for _ in ()).throw(AssertionError("forbidden")),
            robots=lambda u, cache: False)
        self.assertEqual(withheld, [])
        self.assertEqual(checks[0]["status"], "held_source_unavailable")


if __name__ == "__main__":
    unittest.main()
