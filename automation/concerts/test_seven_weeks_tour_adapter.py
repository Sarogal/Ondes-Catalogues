"""Tests sans réseau de la tournée officielle 7WEEKS."""
import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import seven_weeks_tour_adapter as adapter
import artist_tour_discovery as discovery
import intake_archive

DAY = dt.date(2026, 11, 5)
SOURCE = {
    "artistId": "7weeks", "sourceRole": "artist_official",
    "url": "https://7weeks.fr/concerts/", "enabled": True,
    "adapter": "seven_weeks_official_tour",
}
CONFIG = {"schema": "grossesondes.concert.artist_tour_sources.v1",
          "sources": [SOURCE]}
CATALOG = {
    "schemaVersion": 1,
    "artists": [{"id": "7weeks", "name": "7Weeks"}],
    "venues": [{"id": "le-ferrailleur-nantes", "name": "Le Ferrailleur", "city": "Nantes"}],
    "events": [{
        "id": "already-present",
        "date": "2026-11-07", "venueId": "le-ferrailleur-nantes",
        "artistIds": ["7weeks"], "title": "7Weeks + Dirty Deep"}],
}
PAGE = """<html><head><script>const data="09/12/27";</script></head><body>
<h2>TOUR</h2>
<section><p>04/11/26</p><h5>LYON – ROCK N EAT</h5>Tickets</section>
<section><p>05/11/26</p><h5>TOULOUSE – LE REX</h5>Tickets</section>
<section><p>06/11/26</p><h5>LIMOGES – CCM JOHN LENNON</h5>+ Dirty Deep + Earth Inc</section>
<section><p>07/11/26</p><h5>NANTES – LE FERRAILLEUR</h5>+ Dirty Deep</section>
<section><p>26/11/26</p><h5>PERPIGNAN – EL MEDIATOR</h5>Invité de The Inspector Cluzo</section>
<section><p>05/12/26</p><h5>CHALON SUR SAÔNE – LAPÉNICHE</h5>Tickets</section>
<section><p>22/01/27</p><h5>PARIS – LA MAROQUINERIE</h5>Tickets</section>
</body></html>"""


class SevenWeeksTourTests(unittest.TestCase):
    def test_france_date_exacte_avec_annee(self):
        self.assertEqual(adapter.parse_date("22/01/27"), dt.date(2027, 1, 22))
        self.assertEqual(adapter.parse_date("06/11/26"), dt.date(2026, 11, 6))
        for value in ("22/01", "janvier 2027", "01/22/27", "31/02/27",
                      "06/11/2026", "6/11/26"):
            self.assertIsNone(adapter.parse_date(value), msg=value)

    def test_obligation_page_tour_et_lieu_adjacent(self):
        self.assertEqual(adapter.official_tour_entries("<p>05/11/26</p><h5>PARIS – SALLE</h5>", DAY), [])
        self.assertEqual(adapter.official_tour_entries("<h2>TOUR</h2><p>05/11/26</p><h5>Billets</h5>", DAY), [])
        page = "<h2>TOUR</h2><p>06/11/26</p><p>07/11/26</p><h5>NANTES – LE FERRAILLEUR</h5>"
        self.assertEqual(adapter.official_tour_entries(page, DAY),
                         [("2026-11-07", "NANTES", "LE FERRAILLEUR")])

    def test_annonces_passees_et_scripts_exclus(self):
        dates = adapter.official_tour_entries(PAGE, DAY)
        self.assertEqual(len(dates), 6)
        self.assertNotIn("2027-12-09", [d for d, _, _ in dates])
        self.assertNotIn("2026-11-04", [d for d, _, _ in dates])
        self.assertEqual(dates[-1], ("2027-01-22", "PARIS", "LA MAROQUINERIE"))

    def test_candidats_quarantaine_sans_invention_du_plateau(self):
        candidates = adapter.candidates(PAGE, SOURCE, "7Weeks", CATALOG, DAY)
        self.assertEqual(len(candidates), 6)
        nantes = next(x for x in candidates if x["city"] == "NANTES")
        self.assertFalse(nantes["newVenueToReview"])
        self.assertEqual(nantes["venueIdIfKnown"], "le-ferrailleur-nantes")
        self.assertEqual(nantes["name"], "7Weeks")
        self.assertTrue(nantes["countryToVerify"])
        self.assertTrue(nantes["lineupToConfirm"])
        self.assertFalse(nantes["publicationAllowed"])
        self.assertTrue(nantes["reviewRequired"])
        self.assertNotIn("time", nantes)
        self.assertNotIn("latitude", nantes)
        self.assertNotIn("Dirty Deep", str(nantes))

    def test_refus_source_aggregateur_ou_autre_artiste(self):
        for source in (dict(SOURCE, artistId="not-7weeks"),
                       dict(SOURCE, sourceRole="aggregator")):
            with self.assertRaises(ValueError):
                adapter.candidates(PAGE, source, "7Weeks", CATALOG, DAY)

    def test_doublon_evenement_est_conserve_mais_signale(self):
        candidates = adapter.candidates(PAGE, SOURCE, "7Weeks", CATALOG, DAY)
        report = discovery.build_report(CATALOG, CONFIG, DAY, candidates, [])
        already = [x for x in report["candidates"]
                   if x["reviewBucket"] == "already_catalogued"]
        self.assertEqual(len(already), 1)
        self.assertEqual(already[0]["city"], "NANTES")
        self.assertEqual(already[0]["catalogueMatches"], ["already-present"])
        self.assertFalse(already[0]["publicationAllowed"])
        archive, stats = intake_archive.merge(None, report, "2026-11-05T04:00:00Z")
        self.assertEqual(stats["added"], 6)
        self.assertEqual(archive["total"], 6)

    def test_scan_par_rotation_court_une_seule_source(self):
        def fake_fetch(url, **kwargs):
            self.assertEqual(url, SOURCE["url"])
            return PAGE, url
        rows, checks = discovery.scan(
            CATALOG, CONFIG, DAY, max_sources=4, slot=0,
            fetch=fake_fetch, robots=lambda url, cache: True)
        self.assertEqual(len(rows), 6)
        self.assertEqual(checks[0]["officialTourEntries"], 6)
        self.assertEqual(checks[0]["candidateCount"], 6)
        self.assertEqual(checks[0]["status"], "parsed_tour")


if __name__ == "__main__":
    unittest.main()
