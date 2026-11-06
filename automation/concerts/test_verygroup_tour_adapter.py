"""Tests sans réseau des tournées Verygroup, jamais de publication."""
import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import verygroup_tour_adapter as adapter
import artist_tour_discovery as tour
import intake_archive

DAY = dt.date(2026, 11, 6)
MASS = {
    "artistId": "mass-hysteria", "sourceRole": "promoter_official",
    "adapter": "verygroup_official_tour",
    "url": "https://verygroup.fr/verycords/artists/mass-hysteria/",
    "enabled": True,
}
PSYKUP = {
    "artistId": "psykup", "sourceRole": "promoter_official",
    "adapter": "verygroup_official_tour",
    "url": "https://verygroup.fr/veryshow/artists/psykup/",
    "enabled": True,
}
CATALOG = {
    "schemaVersion": 1,
    "artists": [{"id": "mass-hysteria", "name": "Mass Hysteria"},
                {"id": "psykup", "name": "Psykup"}],
    "venues": [
        {"id": "rockstore-montpellier", "name": "Rockstore", "city": "Montpellier"},
        {"id": "le-cargo-caen", "name": "Le Cargö", "city": "Caen"},
    ],
    "events": [],
}
MASS_HTML = """<h1>MASS HYSTERIA</h1>
<h2>Sorties</h2><p>14/11/2025</p>
<h2>En tournée</h2>
<ul><li>MASS HYSTERIA</li></ul><p>Jeu. 5</p><p>Nov. 2026</p><p>RENNES (35)<br>Le Liberté</p>
<ul><li>MASS HYSTERIA</li></ul><p>Sam. 7</p><p>Nov. 2026</p><p>MORLAIX (29)<br>Sew</p><p>Réserver</p>
<ul><li>MASS HYSTERIA</li></ul><p>Jeu. 19</p><p>Nov. 2026</p><p>MONTPELLIER<br>Rockstore</p>
<ul><li>MASS HYSTERIA</li></ul><p>Ven. 20</p><p>Nov. 2026</p><p>AMSTERDAM (NL)<br>Paradiso</p>
<ul><li>MASS HYSTERIA</li></ul><p>Sam. 21</p><p>Nov. 2026</p><p>LILLE (59)<br>Metal Festival</p>
<h2>Vidéos</h2><p>Ven. 23</p><p>Dec. 2026</p><p>PARIS (75)<br>Le Trianon</p>"""
PSYKUP_HTML = """<h1>PSYKUP</h1><h2>En tournée</h2>
<ul><li>PSYKUP</li></ul><p>Ven.</p><p>13</p><p>Nov.</p><p>2026</p>
<p>CAEN (14)<br>Le Cargö</p><p>Réserver</p>
<ul><li>PSYKUP</li></ul><p>Jeu. 19</p><p>Nov. 2026</p>
<p>BÉTHUNE (62)<br>Le Poche</p><p>+7WEEKS</p>
<ul><li>PSYKUP</li></ul><p>Sam. 12</p><p>Déc. 2026</p>
<p>TOULOUSE (31)<br>Le Metronum</p>
<h2>Vidéos</h2>"""


class VerygroupTourTests(unittest.TestCase):
    def test_mass_tour_only_future_french_non_festival_dates(self):
        rows = adapter.listings(MASS_HTML, "Mass Hysteria", DAY)
        self.assertEqual(rows, [
            ("2026-11-07", "MORLAIX", "Sew"),
            ("2026-11-19", "MONTPELLIER", "Rockstore"),
        ])
        self.assertEqual(adapter.listings(MASS_HTML, "Psykup", DAY), [])

    def test_psykup_split_date_and_support_not_presumed(self):
        rows = adapter.candidates(PSYKUP_HTML, PSYKUP, "Psykup", CATALOG, DAY)
        self.assertEqual([r["date"] for r in rows], ["2026-11-13", "2026-11-19", "2026-12-12"])
        caen = rows[0]
        self.assertEqual(caen["venueIdIfKnown"], "le-cargo-caen")
        self.assertFalse(caen["newVenueToReview"])
        self.assertTrue(all(r["countryToVerify"] and r["lineupToConfirm"] for r in rows))
        self.assertFalse(any(r["publicationAllowed"] for r in rows))
        self.assertTrue(all(r["reviewRequired"] for r in rows))
        self.assertNotIn("7WEEKS", repr(rows))
        self.assertNotIn("time", caen)
        self.assertNotIn("latitude", caen)

    def test_deterministic_and_read_only_archive(self):
        first = adapter.candidates(MASS_HTML, MASS, "Mass Hysteria", CATALOG, DAY)
        second = adapter.candidates(MASS_HTML, MASS, "Mass Hysteria", CATALOG, DAY)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 2)
        report = tour.build_report(CATALOG, {
            "schema": "grossesondes.concert.artist_tour_sources.v1", "sources": [MASS],
        }, DAY, first, [])
        archive, stats = intake_archive.merge(None, report, "2026-11-06T20:00:00Z")
        self.assertEqual(stats["added"], 2)
        self.assertEqual(archive["total"], 2)
        self.assertFalse(report["publicationAllowed"])

    def test_refuse_wrong_source_or_artist(self):
        for source, artist in [
            (dict(MASS, url="https://untrusted.invalid"), "Mass Hysteria"),
            (dict(MASS, sourceRole="aggregator"), "Mass Hysteria"),
            (dict(MASS, artistId="psykup"), "Mass Hysteria"),
            (MASS, "Psykup"),
        ]:
            with self.subTest(source=source, artist=artist), self.assertRaises(ValueError):
                adapter.candidates(MASS_HTML, source, artist, CATALOG, DAY)

    def test_invalid_dates_missing_country_and_foreign_are_held(self):
        html = """<h1>PSYKUP</h1><h2>En tournée</h2>
        <p>Ven. 32</p><p>Nov. 2026</p><p>CAEN (14)<br>Le Cargö</p>
        <p>Ven. 13</p><p>Nov. 2026</p><p>BRUXELLES (BE)<br>Botanique</p>
        <p>Ven. 20</p><p>Nov. 2026</p><p>VILLE INCONNUE<br>Nouvelle salle</p>
        <h2>Vidéos</h2>"""
        self.assertEqual(adapter.listings(html, "Psykup", DAY), [])

    def test_scan_uses_robots_and_never_signs_candidates(self):
        config = {"schema": "grossesondes.concert.artist_tour_sources.v1",
                  "sources": [PSYKUP]}
        rows, checks = tour.scan(
            CATALOG, config, DAY, max_sources=1, slot=0,
            fetch=lambda url, **kwargs: (PSYKUP_HTML, url),
            robots=lambda url, cache: True)
        self.assertEqual(len(rows), 3)
        self.assertEqual(checks[0]["officialTourEntries"], 3)
        self.assertEqual(checks[0]["status"], "parsed_tour")
        rows_blocked, checks_blocked = tour.scan(
            CATALOG, config, DAY, max_sources=1, slot=0,
            fetch=lambda url, **kwargs: (_ for _ in ()).throw(AssertionError("fetch forbidden")),
            robots=lambda url, cache: False)
        self.assertEqual(rows_blocked, [])
        self.assertEqual(checks_blocked[0]["status"], "held_source_unavailable")


if __name__ == "__main__":
    unittest.main()
