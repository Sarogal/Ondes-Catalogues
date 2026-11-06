"""Tests hors réseau de l'adaptateur de tournée Live Nation."""
import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import livenation_tour_adapter as ln
import artist_tour_discovery as tour
import intake_archive

DAY = dt.date(2026, 11, 4)
URL = "https://www.livenation.fr/skip-the-use-tickets-adp498333"
DETAIL = "https://www.livenation.fr/event/skip-the-use-love-and-anxiety-lille-tickets-edp1665819"
SOURCE = {
    "artistId": "skip-the-use", "sourceRole": "promoter_official",
    "url": URL, "enabled": True, "detailPathPrefix": "/event/skip-the-use-",
    "maxDetailPages": 6, "excludedCities": ["Mondorf-les-Bains"],
}
CATALOG = {
    "schemaVersion": 1,
    "artists": [{"id": "skip-the-use", "name": "Skip The Use"}],
    "venues": [],
    "events": [],
}
LISTING = '<html><body><a href="/event/skip-the-use-love-and-anxiety-lille-tickets-edp1665819">Lille</a><a href="https://other.example/event/skip-the-use-abc">extérieur</a><a href="/event/other-artist">autre</a></body></html>'
DETAIL_HTML = ('<html><body><h1>Skip The Use - Love &amp; Anxiety</h1>'
               '<h2>ven., 22 janv. 2027</h2><a href="/venue">Aeronef,</a>'
               '<span>Lille</span><h3>En tête d’affiche</h3>'
               '<p>Skip The Use</p></body></html>')


class LiveNationTourTests(unittest.TestCase):
    def test_seulement_liens_meme_domaine_meme_artiste(self):
        links = ln.event_links(LISTING, URL, "/event/skip-the-use-")
        self.assertEqual(links, [DETAIL])

    def test_date_francaise_avec_annee_complete(self):
        self.assertEqual(ln.date_from_text("ven., 22 janv. 2027"),
                         dt.date(2027, 1, 22))
        self.assertEqual(ln.date_from_text("sam., 06 mars 2027"),
                         dt.date(2027, 3, 6))
        self.assertIsNone(ln.date_from_text("ven., 22 janv."))
        self.assertIsNone(ln.date_from_text("jeu., 31 févr. 2027"))

    def test_detail_hors_catalogue_reste_en_revue(self):
        c = ln.detail_candidate(DETAIL_HTML, DETAIL, SOURCE, "Skip The Use", CATALOG, DAY)
        self.assertEqual(c["date"], "2027-01-22")
        self.assertEqual(c["venue"], "Aeronef")
        self.assertEqual(c["city"], "Lille")
        self.assertTrue(c["newVenueToReview"])
        self.assertTrue(c["countryToVerify"])
        self.assertFalse(c["publicationAllowed"])
        self.assertTrue(c["reviewRequired"])
        self.assertNotIn("time", c)
        self.assertNotIn("latitude", c)

    def test_fiche_incomplete_ou_autre_artiste_rejetee(self):
        self.assertIsNone(ln.detail_candidate(
            DETAIL_HTML.replace("2027", ""), DETAIL, SOURCE, "Skip The Use", CATALOG, DAY))
        self.assertIsNone(ln.detail_candidate(
            DETAIL_HTML.replace("Aeronef,", "Salle sans localisation"),
            DETAIL, SOURCE, "Skip The Use", CATALOG, DAY))
        self.assertIsNone(ln.detail_candidate(
            DETAIL_HTML.replace("Skip The Use", "Autre groupe"), DETAIL,
            SOURCE, "Skip The Use", CATALOG, DAY))

    def test_bikini_deja_connu_avec_ramonville_st_agne(self):
        catalogue = dict(CATALOG, venues=[{
            "id": "le-bikini-toulouse", "name": "Le Bikini",
            "city": "Ramonville-Saint-Agne"}])
        page = DETAIL_HTML.replace("Aeronef,", "Le Bikini,").replace(
            "Lille", "Ramonville St Agne")
        c = ln.detail_candidate(page, DETAIL, SOURCE, "Skip The Use", catalogue, DAY)
        self.assertIsNotNone(c)
        self.assertEqual(c["venueIdIfKnown"], "le-bikini-toulouse")
        self.assertFalse(c["newVenueToReview"])
        self.assertTrue(c["countryToVerify"])
        self.assertFalse(c["publicationAllowed"])

    def test_normalisation_commune_limitee_aux_abreviations(self):
        self.assertEqual(ln.normalized_city("Saint-Étienne"),
                         ln.normalized_city("St Étienne"))
        self.assertEqual(ln.normalized_city("Sainte-Maxime"),
                         ln.normalized_city("Ste Maxime"))
        self.assertNotEqual(ln.normalized_city("Paris"),
                            ln.normalized_city("Lyon"))

    def test_ville_etrangere_explicitement_ecartee(self):
        page = DETAIL_HTML.replace("Lille", "Mondorf-les-Bains")
        self.assertIsNone(ln.detail_candidate(page, DETAIL, SOURCE,
                                               "Skip The Use", CATALOG, DAY))

    def test_cycle_complet_documente_uniquement_des_candidats(self):
        sources = {"schema": "grossesondes.concert.artist_tour_sources.v1",
                   "sources": [SOURCE]}
        def fake_fetch(url, **kwargs):
            if url == URL:
                return LISTING, URL
            if url == DETAIL:
                return DETAIL_HTML, DETAIL
            raise AssertionError("Domaine inconnu")
        candidates, checks = tour.scan(CATALOG, sources, DAY, 4, 0,
                                      fetch=fake_fetch,
                                      robots=lambda url, cache: True)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(checks[0]["detailLinks"], 1)
        self.assertEqual(checks[0]["detailPagesRead"], 1)
        self.assertEqual(checks[0]["status"], "parsed_details")
        report = tour.build_report(CATALOG, sources, DAY, candidates, checks)
        archive, diff = intake_archive.merge(None, report, "2026-11-04T22:00:00Z")
        self.assertEqual(diff["added"], 1)
        self.assertEqual(archive["total"], 1)


if __name__ == "__main__":
    unittest.main()
