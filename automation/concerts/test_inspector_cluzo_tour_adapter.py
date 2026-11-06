"""Tests du collecteur officiel The Inspector Cluzo, sans réseau."""
import datetime as dt
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import inspector_cluzo_tour_adapter as adapter
import artist_tour_discovery as discovery
import intake_archive

DAY = dt.date(2026, 11, 5)
SOURCE = {
    "artistId": "the-inspector-cluzo", "sourceRole": "artist_official",
    "url": "https://theinspectorcluzo.com/en/tour2026/", "enabled": True,
    "adapter": "inspector_cluzo_official_tour",
}
CATALOG = {
    "schemaVersion": 1, "artists": [{"id": "the-inspector-cluzo", "name": "The Inspector Cluzo"}],
    "venues": [{"id": "le-fil-st-etienne", "name": "Le Fil", "city": "Saint-Étienne"}],
    "events": [],
}
PAGE = """<main><table>
<tr><td><b>01-10-2026</b></td><td>FR - PARIS</td><td>La Maroquinerie</td><td>Ticket</td></tr>
<tr><td><b>06-11-2026</b></td><td>FR - ST-JACUT-LES-PINS</td><td>Mots Zik Sous les Pins</td><td>Ticket</td></tr>
<tr><td><b>07-11-2026</b></td><td>FR - LE MANS</td><td>BeBop Festival</td><td>Ticket</td></tr>
<tr><td><b>13-11-2026</b></td><td>FR - TOURS</td><td>Le Bateau Ivre</td><td>Ticket</td></tr>
<tr><td><b>13-11-2026</b></td></tr><tr><td>FR - TOURS</td></tr><tr><td>Le Bateau Ivre</td></tr>
<tr><td><b>14-11-2026</b></td><td>FR - PARTENAY</td><td>Diff'Art</td><td>Ticket</td></tr>
<tr><td><b>20-11-2026</b></td><td>FR - ST ETIENNE</td><td>Le Fil</td><td>Ticket</td></tr>
<tr><td><b>20-11-2026</b></td><td>US - CHICAGO,IL</td><td>The Aquarium</td><td>Ticket</td></tr>
<tr><td><b>04-12-2026</b></td><td>FR - TARBES</td><td>La Gespe</td><td>Ticket</td></tr>
<tr><td><b>16-02-2027</b></td><td>JP - TOKYO</td><td>WWW</td><td>Ticket</td></tr>
</table></main>"""


class InspectorTourTests(unittest.TestCase):
    def test_fr_uniquement_dates_completes_festivals_exclus(self):
        rows, fest = adapter.future_fr_shows(PAGE, DAY)
        self.assertEqual(fest, 2)
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0], ("2026-11-13", "TOURS", "Le Bateau Ivre"))
        self.assertEqual(rows[-1], ("2026-12-04", "TARBES", "La Gespe"))
        self.assertFalse(any(city == "TOKYO" for _, city, venue in rows))

    def test_refus_de_dates_incompletes(self):
        page = '<table><tr><td>04-12</td><td>FR - TARBES</td><td>La Gespe</td></tr></table>'
        self.assertEqual(adapter.future_fr_shows(page, DAY)[0], [])
        page = '<table><tr><td>31-02-2027</td><td>FR - TARBES</td><td>La Gespe</td></tr></table>'
        self.assertEqual(adapter.future_fr_shows(page, DAY)[0], [])

    def test_lignes_mobile_non_considerees_des_fiches(self):
        page = '<table><tr><td>14-11-2026</td></tr><tr><td>FR - TOURS</td></tr><tr><td>Le Bateau Ivre</td></tr></table>'
        self.assertEqual(adapter.future_fr_shows(page, DAY)[0], [])

    def test_quarantaine_genre_et_lineup(self):
        rows, festival = adapter.candidates(PAGE, SOURCE, "The Inspector Cluzo", CATALOG, DAY)
        self.assertEqual(festival, 2)
        self.assertEqual(len(rows), 4)
        self.assertTrue(all(not x["publicationAllowed"] and x["reviewRequired"] for x in rows))
        self.assertTrue(all(x["countryCodeFromOfficial"] == "FR" for x in rows))
        self.assertTrue(all(x["lineupToConfirm"] and x["genreToConfirm"] for x in rows))
        self.assertFalse(any("7Weeks" in x["name"] for x in rows))
        self.assertTrue(all("time" not in x for x in rows))

    def test_source_inappropriee_refusee(self):
        for invalid in (dict(SOURCE, artistId="autre-groupe"),
                        dict(SOURCE, sourceRole="aggregator")):
            with self.assertRaises(ValueError):
                adapter.candidates(PAGE, invalid, "The Inspector Cluzo", CATALOG, DAY)

    def test_integration_cycle_et_registre_prive(self):
        cfg = {"schema": "grossesondes.concert.artist_tour_sources.v1", "sources": [SOURCE]}
        proposals, checks = discovery.scan(
            CATALOG, cfg, DAY, max_sources=4, slot=0,
            fetch=lambda url, **kw: (PAGE, url),
            robots=lambda url, cache: True)
        self.assertEqual(len(proposals), 4)
        self.assertEqual(checks[0]["officialTourEntries"], 4)
        self.assertEqual(checks[0]["festivalListingsExcluded"], 2)
        self.assertEqual(checks[0]["status"], "parsed_tour")
        report = discovery.build_report(CATALOG, cfg, DAY, proposals, checks)
        registry, diff = intake_archive.merge(None, report, "2026-11-05T05:00:00Z")
        self.assertEqual(diff["added"], 4)
        self.assertEqual(registry["total"], 4)


if __name__ == "__main__":
    unittest.main()
