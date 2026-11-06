"""Offline, fail-closed verification of the artist-linked 2026 ticket campaign."""
import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import stranglers_linked_tour_adapter as adapter
import artist_tour_discovery as tour

SOURCE = {"artistId": "the-stranglers", "url": adapter.URL,
          "sourceRole": "artist_official", "enabled": True,
          "adapter": "stranglers_official_ticket_campaign"}
CATALOG = {"artists": [{"id": "the-stranglers", "name": "The Stranglers"}],
           "venues": [{"id": "le-rocher-de-palmer-cenon",
                       "name": "Le Rocher de Palmer", "city": "Cenon"}],
           "events": []}
DATES = [
    "20 Nov SUPERFORME - L'OASIS Le Mans (72) Billets",
    "21 Nov CAP CAVAL Penmarc'h (29) Billets",
    "23 Nov LA CARRIÈRE Saint-Herblain (44) Billets",
    "24 Nov ROCHER DE PALMER Cenon (33) Billets",
    "26 Nov LE BIKINI Toulouse (31) Billets",
    "27 Nov ZINGA ZANGA Béziers (34) Billets",
    "28 Nov 6 MIC Aix-En-Provence (13) Billets",
    "30 Nov LE TRANSBORDEUR Lyon-Villeurbanne (69) Billets",
    "01 Dec ESPACE CROUZY Boisseuil (87) Billets",
    "03 Dec LE FORUM Vauréal (95) Billets",
    "04 Dec Le Zéphyr HEM (59) Billets",
]
HTML = "<div>THE STRANGLERS - France 2026</div><h2>Upcoming shows</h2>" + \
       "".join(f"<p>{r}</p>" for r in DATES)


class LinkedOfficialTourTests(unittest.TestCase):
    def test_eleven_rows_and_read_only_flags(self):
        rows = adapter.candidates(HTML, SOURCE, "The Stranglers", CATALOG,
                                  dt.date(2026, 11, 6))
        self.assertEqual(len(rows), 11)
        self.assertEqual(len({r["candidateId"] for r in rows}), 11)
        self.assertEqual(rows[2]["venue"], "LA CARRIÈRE")
        self.assertEqual(rows[3]["city"], "Cenon")
        self.assertEqual(rows[4]["reportedLocation"], "Toulouse (31)")
        self.assertEqual(rows[7]["city"], "Villeurbanne")
        for row in rows:
            self.assertFalse(row["publicationAllowed"])
            self.assertTrue(row["reviewRequired"])
            self.assertTrue(row["lineupToConfirm"])
            self.assertTrue(row["genreToConfirm"])
            self.assertTrue(row["countryToVerify"])
            self.assertTrue(row["coordinatesToVerify"])
            self.assertNotIn("time", row)
            self.assertNotIn("latitude", row)
        self.assertEqual(len(adapter.official_shows(
            HTML, dt.date(2026, 11, 25))), 7)

    def test_changed_page_or_bad_year_fails_closed(self):
        bad = [
            HTML.replace("France 2026", "France 2027"),
            HTML.replace("Upcoming shows", "Past shows"),
            HTML.replace("Saint-Herblain (44)", "Paris (75)"),
            HTML.replace("24 Nov ROCHER", "25 Nov ROCHER"),
            HTML.replace("01 Dec ESPACE CROUZY", "01 Dec UNKNOWN VENUE"),
            HTML.replace("<p>" + DATES[0] + "</p>", ""),
            HTML + "<p>" + DATES[0] + "</p>",
        ]
        for page in bad:
            with self.subTest(page=page[-55:]):
                self.assertEqual(adapter.official_shows(page, dt.date(2026, 11, 6)), [])

    def test_script_injection_and_untrusted_source_rejected(self):
        injection = HTML.replace("<p>" + DATES[0] + "</p>",
                                 "<script><p>" + DATES[0] + "</p></script>")
        self.assertEqual(adapter.official_shows(injection, dt.date(2026, 11, 6)), [])
        for source in (dict(SOURCE, artistId="invented"),
                       dict(SOURCE, url="https://other.example/show"),
                       dict(SOURCE, sourceRole="aggregator")):
            with self.assertRaises(ValueError):
                adapter.candidates(HTML, source, "The Stranglers", CATALOG,
                                   dt.date(2026, 11, 6))

    def test_integration_and_blocked_robots_do_not_write(self):
        config = {"schema": "grossesondes.concert.artist_tour_sources.v1",
                  "sources": [SOURCE]}
        rows, checks = tour.scan(CATALOG, config, dt.date(2026, 11, 6),
                                 fetch=lambda u, **k: (HTML, u),
                                 robots=lambda u, cache: True)
        self.assertEqual(len(rows), 11)
        self.assertEqual(checks[0]["officialTourEntries"], 11)
        self.assertTrue(all(not row["publicationAllowed"] for row in rows))
        held, report = tour.scan(CATALOG, config, dt.date(2026, 11, 6),
                                 fetch=lambda u, **k: (_ for _ in ()).throw(
                                     AssertionError("Should never fetch")),
                                 robots=lambda u, cache: False)
        self.assertEqual(held, [])
        self.assertEqual(report[0]["status"], "held_source_unavailable")


if __name__ == "__main__":
    unittest.main()
