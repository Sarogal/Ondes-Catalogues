"""Tests sans réseau des dates françaises officielles de Marillion."""
import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import marillion_tour_adapter as adapter
import artist_tour_discovery as discovery
import intake_archive

DAY = dt.date(2026, 11, 5)
SOURCE = {
    "artistId": "marillion", "sourceRole": "artist_official",
    "url": "https://www.marillion.com/tour/", "enabled": True,
    "adapter": "marillion_official_tour",
}
CONFIG = {"schema": "grossesondes.concert.artist_tour_sources.v1",
          "sources": [SOURCE]}
CATALOGUE = {
    "schemaVersion": 1,
    "artists": [{"id": "marillion", "name": "Marillion"}],
    "venues": [{"id": "la-laiterie-strasbourg",
                "name": "La Laiterie", "city": "Strasbourg"}],
    "events": [{"id": "already-published", "date": "2026-11-22",
                "venueId": "la-laiterie-strasbourg",
                "artistIds": ["marillion"], "title": "Marillion + Lazuli"}],
}
PAGE = """<html><head><script>const fake = "Monday 1 January 2029";</script></head>
<body><h1>TOUR DATES</h1><h2>MARILLION SHOWS 2026</h2>
<p>Wednesday 18 November 2026<br>Le Mem<br>Rennes<br>France<br>TICKETS</p>
<p>Sunday 22 November 2026<br>La Laiterie<br>Strasbourg<br>France<br>SOLD OUT</p>
<p>Friday 27 November 2026<br>Opera Garnier<br>Monte Carlo<br>Monaco</p>
<p>Sunday 29 November 2026<br>Radiant-Bellevue<br>Lyon<br>France</p>
<h2>MARILLION SHOWS 2027</h2>
<p>Saturday 15 May 2027<br>Le Silo<br>Marseille<br>France</p>
<p>Sunday 16 May 2027<br>Le Silo<br>Marseille<br>France</p>
<p>Monday 17 May 2027<br>Another venue<br>Paris<br>Germany</p>
<p>Sunday 18 November 2026<br>Invented<br>Nice<br>France</p>
</body></html>"""


class MarillionOfficialTourTests(unittest.TestCase):
    def test_date_et_jour_semaine_obligatoires(self):
        self.assertEqual(
            adapter.parse_weekday_date("Wednesday 18 November 2026"),
            dt.date(2026, 11, 18))
        for bogus in ("18 November 2026", "Wednesday 18 November",
                      "Sunday 18 November 2026", "Sunday 31 February 2027",
                      "Friday 27 November 2027", "18/11/26"):
            self.assertIsNone(adapter.parse_weekday_date(bogus), msg=bogus)

    def test_date_complete_et_pays_france_sans_inference(self):
        self.assertEqual(adapter.french_dates(PAGE, DAY), [
            ("2026-11-18", "Le Mem", "Rennes"),
            ("2026-11-22", "La Laiterie", "Strasbourg"),
            ("2026-11-29", "Radiant-Bellevue", "Lyon"),
            ("2027-05-15", "Le Silo", "Marseille"),
            ("2027-05-16", "Le Silo", "Marseille"),
        ])

    def test_page_non_tour_ou_pays_inconnu_est_rejetee(self):
        self.assertEqual(adapter.french_dates(
            "<p>Wednesday 18 November 2026<br>Le Mem<br>Rennes<br>France</p>",
            DAY), [])
        self.assertEqual(adapter.french_dates(
            "<h2>TOUR DATES</h2><p>Wednesday 18 November 2026"
            "<br>Le Mem<br>Rennes<br>France</p>", DAY), [])

    def test_revue_privee_sans_artiste_ou_horaire_suppose(self):
        rows = adapter.candidates(PAGE, SOURCE, "Marillion", CATALOGUE, DAY)
        self.assertEqual(len(rows), 5)
        old = next(x for x in rows if x["date"] == "2026-11-22")
        self.assertEqual(old["venueIdIfKnown"], "la-laiterie-strasbourg")
        self.assertFalse(old["newVenueToReview"])
        self.assertTrue(old["reviewRequired"])
        self.assertFalse(old["publicationAllowed"])
        self.assertTrue(old["lineupToConfirm"])
        self.assertTrue(old["countryVerifiedFromOfficialListing"])
        self.assertNotIn("time", str(rows))
        self.assertNotIn("Lazuli", str(rows))
        classified, _, _ = discovery.triage.classify(rows, CATALOGUE)
        self.assertEqual(
            next(x for x in classified if x["date"] == "2026-11-22")[
                "reviewBucket"], "already_catalogued")
        report = discovery.build_report(CATALOGUE, CONFIG, DAY, rows, [])
        registry, stats = intake_archive.merge(None, report, "2026-11-05T06:00:00Z")
        self.assertEqual(registry["total"], 5)
        self.assertEqual(stats["added"], 5)

    def test_source_differente_non_admise(self):
        for source in (dict(SOURCE, artistId="other"),
                       dict(SOURCE, sourceRole="aggregator"),
                       dict(SOURCE, adapter="different")):
            with self.assertRaises(ValueError):
                adapter.candidates(PAGE, source, "Marillion", CATALOGUE, DAY)

    def test_scan_integre_adaptateur_sans_publier(self):
        def fake_fetch(url, **kwargs):
            self.assertEqual(url, SOURCE["url"])
            return PAGE, url
        rows, checks = discovery.scan(CATALOGUE, CONFIG, DAY, max_sources=2,
                                      fetch=fake_fetch,
                                      robots=lambda url, cache: True)
        self.assertEqual(len(rows), 5)
        self.assertEqual(checks[0]["officialTourEntries"], 5)
        self.assertEqual(checks[0]["candidateCount"], 5)
        self.assertEqual(checks[0]["status"], "parsed_tour")


if __name__ == "__main__":
    unittest.main()
