"""No network. Actual formatting of The Stranglers 2026 official announcement."""
import datetime as dt
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import stranglers_tour_adapter as adapter
import artist_tour_discovery as discovery

SOURCE = {"artistId": "the-stranglers", "sourceRole": "artist_official",
          "url": adapter.OFFICIAL, "enabled": True,
          "adapter": "stranglers_french_2026"}
CATALOGUE = {
    "artists": [{"id": "the-stranglers", "name": "The Stranglers"}],
    "venues": [{"id": "le-bikini-toulouse", "name": "Le Bikini", "city": "Toulouse"}],
    "events": [{"date": "2026-11-26", "artistIds": ["the-stranglers"]}],
}
ROWS = (
    "20 Nov – LE MANS L’Oasis<br/>"
    "21 Nov – PENMARC’H Cap Caval – SOLD OUT!<br/>"
    "23 Nov – SAINT-HERBLAIN (NANTES) Le Carrière<br/>"
    "24 Nov – CENON (BORDEAUX) Rocher De Palmer<br/>"
    "26 Nov – RAMONVILLE SAINT-AGNE (TOULOUSE) Le Bikini – SOLD OUT!<br/>"
    "27 Nov – BEZIERS Zinga Zanga<br/>"
    "28 Nov – AIX-EN-PROVENCE 6mic<br/>"
    "30 Nov – VILLEURBANNE (LYON) Le Transbordeur<br/>"
    "01 Dec – BOISSEUIL Espace Crouzy<br/>"
    "03 Dec – VAUREAL Le Forum – SOLD OUT!<br/>"
    "04 Dec – HEM Le Zephyr SOLD OUT – SOLD OUT!"
)
PAGE = ("<h1>The Stranglers announce French tour 2026!</h1>"
        "<p>We are pleased to announce The Stranglers will return to France "
        "for an extensive headline tour in November and December 2026.</p>"
        "<p>" + ROWS + "</p>")


class StranglersDiscoveryTests(unittest.TestCase):
    def test_eleven_exact_official_dates_and_no_synthetic_fields(self):
        rows = adapter.candidates(PAGE, SOURCE, "The Stranglers", CATALOGUE,
                                  dt.date(2026, 11, 6))
        self.assertEqual(len(rows), 11)
        self.assertEqual(len({r["candidateId"] for r in rows}), 11)
        self.assertEqual(rows[0]["date"], "2026-11-20")
        self.assertEqual(rows[2]["venue"], "Le Carrière")
        self.assertEqual(rows[3]["city"], "Cenon")
        self.assertEqual(rows[4]["city"], "Ramonville-Saint-Agne")
        self.assertIsNone(rows[4]["venueIdIfKnown"])
        for row in rows:
            self.assertFalse(row["publicationAllowed"])
            self.assertTrue(row["reviewRequired"])
            self.assertTrue(row["venueAddressToVerify"])
            self.assertTrue(row["countryToVerify"])
            self.assertTrue(row["genreToConfirm"])
            self.assertTrue(row["lineupToConfirm"])
            self.assertNotIn("time", row)
            self.assertNotIn("latitude", row)
        self.assertEqual(adapter.official_shows(PAGE, dt.date(2026, 11, 25))[0][0],
                         "2026-11-26")

    def test_changed_page_title_year_line_or_location_rejected(self):
        variants = [
            PAGE.replace("tour 2026!", "tour 2027!"),
            PAGE.replace("November and December 2026", "November and December 2027"),
            PAGE.replace("LE MANS L’Oasis", "LE MANS Imaginary"),
            PAGE.replace("03 Dec – VAUREAL", "03 Dec – ANOTHER CITY"),
            PAGE.replace("20 Nov – LE MANS L’Oasis<br/>", ""),
            PAGE.replace("27 Nov – BEZIERS", "27 Dec – BEZIERS"),
            PAGE.replace("04 Dec – HEM", "04 Dec – UNKNOWN"),
            PAGE.replace("<p>" + ROWS + "</p>",
                         "<p>" + ROWS + "<br/>20 Nov – LE MANS L’Oasis</p>"),
        ]
        for page in variants:
            with self.subTest(page=page[:80]):
                self.assertEqual(adapter.official_shows(page, dt.date(2026, 11, 6)), [])

    def test_script_injection_and_wrong_source_rejected(self):
        page = PAGE.replace("<p>" + ROWS + "</p>",
                            "<script><p>" + ROWS + "</p></script>")
        self.assertEqual(adapter.official_shows(page, dt.date(2026, 11, 6)), [])
        for altered in (dict(SOURCE, artistId="wrong"),
                        dict(SOURCE, url="https://fake.example")):
            with self.assertRaises(ValueError):
                adapter.candidates(PAGE, altered, "The Stranglers",
                                   CATALOGUE, dt.date(2026, 11, 6))

    def test_tour_workflow_integration_and_robots_refusal(self):
        cfg = {"schema": "grossesondes.concert.artist_tour_sources.v1",
               "sources": [SOURCE]}
        candidates, checks = discovery.scan(
            CATALOGUE, cfg, dt.date(2026, 11, 6),
            fetch=lambda url, **kw: (PAGE, url),
            robots=lambda url, cache: True)
        self.assertEqual(len(candidates), 11)
        self.assertEqual(checks[0]["officialTourEntries"], 11)
        with mock.patch.object(discovery.discover, "download",
                               side_effect=AssertionError("network forbidden")):
            blocked, statuses = discovery.scan(
                CATALOGUE, cfg, dt.date(2026, 11, 6),
                fetch=discovery.discover.download,
                robots=lambda url, cache: False)
        self.assertEqual(blocked, [])
        self.assertEqual(statuses[0]["status"], "held_source_unavailable")


if __name__ == "__main__":
    unittest.main()
