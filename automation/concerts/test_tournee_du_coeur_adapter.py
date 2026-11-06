"""La Tournée du Cœur : extraction officielle en quarantaine."""
import datetime as dt
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tournee_du_coeur_adapter as adapter
import artist_tour_discovery as discovery

TODAY = dt.date(2026, 11, 5)
SOURCE = {
    "artistId": "cachemire",
    "url": adapter.URL, "sourceRole": "promoter_official",
    "adapter": "tournee_du_coeur_official_2027", "enabled": True,
}
CATALOG = {
    "schemaVersion": 1,
    "artists": [{"id": "cachemire", "name": "Cachemire"},
                {"id": "tagada-jones", "name": "Tagada Jones"}],
    "venues": [{"id": "le-bateau-ivre-tours",
                "name": "Le Bateau Ivre", "city": "Tours"}],
    "events": [{"id": "existing", "date": "2027-01-28",
                "venueId": "le-bateau-ivre-tours",
                "artistIds": ["cachemire"]}],
}
HTML = """<html><head><title>La Tournée du Cœur III</title>
<script>const date='05/02/2027';</script></head><body>
<header><img alt="Cachemire, La Phaze, Bob's Not Dead"></header>
<section><p>28/01/2027</p><p>Tours (37) - Le Bateau Ivre</p>Ticket
<p>29/01/2027</p><p>À venir</p>DATE À ANNONCER
<p>30/01/2027</p><p>Lons-le-Saunier (39) - Le Bœuf sur le Toit</p>Ticket
<p>06/02/2027</p><p>La Barre-de-Monts (85) - Rock d’Hiver</p>Ticket
<p>11/02/2027</p><p>Morlaix (29) - Le SEW</p>Ticket
<p>19/02/2027</p><p>Saint-Paul-en-Pareds (85) - Les Feux de l’été à La Grange du Charfait</p>
<p>20/02/2027</p><p>Landévant (56) - Recyclage Festif</p>
<p>24/02/2027</p><p>Strasbourg (67) - La Laiterie</p>Ticket
<p>26/02/2027</p><p>À venir</p>DATE À ANNONCER
<p>27/02/2027</p><p>Grenoble (38) - La Belle Électrique</p>Ticket
</section></body></html>"""


class TourneeDuCoeurTests(unittest.TestCase):
    def test_dates_officielles_avec_salle_et_departement(self):
        self.assertEqual(adapter.official_entries(HTML, TODAY), [
            ("2027-01-28", "Tours", "Le Bateau Ivre", "37"),
            ("2027-01-30", "Lons-le-Saunier", "Le Bœuf sur le Toit", "39"),
            ("2027-02-11", "Morlaix", "Le SEW", "29"),
            ("2027-02-24", "Strasbourg", "La Laiterie", "67"),
            ("2027-02-27", "Grenoble", "La Belle Électrique", "38"),
        ])

    def test_refuser_dates_inventees_non_annoncees_et_festivals(self):
        rows = adapter.official_entries(HTML, TODAY)
        self.assertEqual(len(rows), 5)
        self.assertNotIn("À venir", str(rows))
        self.assertNotIn("Rock d’Hiver", str(rows))
        self.assertNotIn("Les Feux", str(rows))
        self.assertNotIn("Recyclage", str(rows))
        self.assertNotIn("05/02/2027", str(rows))
        for invalid in ("31/02/2027", "28/01", "2027-01-28", "28/13/2027"):
            self.assertIsNone(adapter.parse_date(invalid))

    def test_jamais_associer_une_date_a_la_salle_suivante(self):
        page = """<section><p>28/01/2027</p><p>À venir</p>
        <p>29/01/2027</p><p>Paris (75) - L’Olympia</p></section>"""
        self.assertEqual(adapter.official_entries(page, TODAY),
                         [("2027-01-29", "Paris", "L’Olympia", "75")])
        self.assertEqual(adapter.official_entries("<p>2027 à venir</p>", TODAY), [])

    def test_protections_source_inconnue(self):
        for src in (dict(SOURCE, artistId="wrong"),
                    dict(SOURCE, sourceRole="aggregator"),
                    dict(SOURCE, adapter="wrong"),
                    dict(SOURCE, url="https://example.net/")):
            with self.assertRaises(ValueError):
                adapter.candidates(HTML, src, "Cachemire", CATALOG, TODAY)

    def test_aucune_approbation_et_aucun_artiste_invente(self):
        rows = adapter.candidates(HTML, SOURCE, "Cachemire", CATALOG, TODAY)
        self.assertEqual(len(rows), 5)
        self.assertTrue(all(x["publicationAllowed"] is False and
                            x["reviewRequired"] is True for x in rows))
        self.assertTrue(all(x["lineupToConfirm"] and x["countryToVerify"]
                            and x["coordinatesToVerify"] for x in rows))
        self.assertFalse(rows[0]["newVenueToReview"])
        for row in rows:
            self.assertNotIn("time", row)
            self.assertNotIn("latitude", row)
            self.assertNotIn("artistIds", row)

    def test_moteur_scan_et_declaration_sources(self):
        cfg = {"schema": "grossesondes.concert.artist_tour_sources.v1",
               "sources": [SOURCE]}
        rows, checks = discovery.scan(CATALOG, cfg, TODAY,
            fetch=lambda url, **kwargs: (HTML, url),
            robots=lambda url, cache: True)
        self.assertEqual(len(rows), 5)
        self.assertEqual(checks[0]["status"], "parsed_tour")
        self.assertEqual(checks[0]["officialTourEntries"], 5)
        self.assertEqual(checks[0]["candidateCount"], 5)
        self.assertTrue(all(not x["publicationAllowed"] for x in rows))

    def test_tagada_site_explicitement_suspendu_apres_robots_denial(self):
        config = json.loads(discovery.SOURCES.read_text(encoding="utf-8"))
        blocked = next(x for x in config["sources"]
                       if x["artistId"] == "tagada-jones")
        self.assertFalse(blocked["enabled"])
        selected = discovery.source_selection(
            config, [{"artistId":x["artistId"], "recordedDateCount":0}
                     for x in config["sources"]], TODAY, 5)
        self.assertFalse(any(x["artistId"] == "tagada-jones" for x in selected))


if __name__ == "__main__":
    unittest.main()
