"""Howlin' Jaws : découverte fail-closed via agence officielle, sans réseau."""
import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parent))
import howlin_jaws_tour_adapter as adapter
import artist_tour_discovery as discovery

DAY=dt.date(2026,11,5)
SOURCE={"artistId":"howlin-jaws","sourceRole":"promoter_official",
        "url":"https://radical-production.fr/artistes/howlin-jaws/",
        "adapter":"howlin_jaws_radical_tour","enabled":True}
CATALOG={
    "schemaVersion":1,"mode":"preview-public-unlisted",
    "artists":[{"id":"howlin-jaws","name":"Howlin' Jaws"},
               {"id":"fff","name":"FFF"}],
    "venues":[{"id":"le-mem-rennes","name":"Le MeM","city":"Rennes"},
              {"id":"le-chabada-angers","name":"Le Chabada","city":"Angers"}],
    "events":[{"id":"known-fff-rennes","title":"FFF + Howlin' Jaws",
               "date":"2026-12-10","artistIds":["fff","howlin-jaws"],
               "venueId":"le-mem-rennes"}],
}
HTML="""<main><h1>Howlin’ Jaws</h1><p>2028 unknown fake tour date</p>
<h2>Concerts</h2><h3>Dates à venir</h3>
<p>10\n nov. 2026</p><p>Roubaix</p>Cave aux Poètes
<p>Co-plateau avec Moundrag</p>Réserver
<p>18 nov. 2026</p><p>PARIS</p>Trabendo
<p>Première partie : Théo Charaf</p>Réserver
<p>21 nov. 2026</p><p>LYON</p>Marché Gare Réserver
<p>28 nov. 2026</p><p>Saint-Jacques-De-Compostelle (ES)</p>Outono Códax Festival Réserver
<p>08 déc. 2026</p><p>NANTES</p>Stereolux<p>En première partie de FFF</p>Réserver
<p>09 déc. 2026</p><p>BREST</p>Carène<p>En première partie de FFF</p>Réserver
<p>10 déc. 2026</p><p>Rennes</p>MeM<p>En première partie de FFF</p>Réserver
<p>11 déc. 2026</p><p>ANGERS</p>Chabada<p>En première partie de FFF</p>Réserver
<p>27 févr. 2027</p><p>PENMARC'H</p>Cap Caval<p>En première partie de Komodor</p>Réserver
<p>01 avr. 2027</p><p>SAINT-ÉTIENNE</p>Fil Réserver
<p>02 avr. 2027</p><p>Aix-En-Provence</p>6MIC<p>Première partie : Gloria</p>Réserver
<p>28 avr. 2027</p><p>STRASBOURG</p>Laiterie<p>Co-plateau avec Komodor</p>Réserver
<p>29 avr. 2027</p><p>NANCY</p>Autre Canal<p>Co-plateau avec Komodor</p>Réserver
<h3>Dates passées</h3><p>28 août 2026</p><p>Annulé</p>
<p>Sète</p>Théâtre de la Mer
<script>const bogus="20 nov. 2027 Rennes Fake Hall";</script></main>"""


class HowlinJawsRadicalOfficialTourTests(unittest.TestCase):
    def test_dates_completes_and_country_never_inferred(self):
        expected=[
            ("2026-11-10","Roubaix","Cave aux Poètes"),
            ("2026-11-18","PARIS","Trabendo"),
            ("2026-11-21","LYON","Marché Gare"),
            ("2026-12-08","NANTES","Stereolux"),
            ("2026-12-09","BREST","Carène"),
            ("2026-12-10","Rennes","MeM"),
            ("2026-12-11","ANGERS","Chabada"),
            ("2027-02-27","PENMARC'H","Cap Caval"),
            ("2027-04-01","SAINT-ÉTIENNE","Fil"),
            ("2027-04-02","Aix-En-Provence","6MIC"),
            ("2027-04-28","STRASBOURG","Laiterie"),
            ("2027-04-29","NANCY","Autre Canal"),
        ]
        self.assertEqual(adapter.french_listings(HTML,DAY),expected)

    def test_invalid_dates_foreign_city_or_fake_headers_fail_closed(self):
        for x in ("31 févr. 2027","20 nov.","17 nov. 20a5",
                  "20 marc. 2027","20 nov. 2027 fake"):
            self.assertIsNone(adapter.parse_date(x),msg=x)
        # Une date passée peut être grammaticalement valide, mais ne
        # doit produire aucune piste dans la fenêtre future.
        self.assertEqual(adapter.french_listings(HTML,dt.date(2027,1,1)),
                         [x for x in adapter.french_listings(HTML,DAY)
                          if x[0] >= "2027-01-01"])
        self.assertEqual(adapter.french_listings(
            "<h1>Howlin' Jaws</h1><p>10 nov. 2026 Roubaix Le MeM</p>",DAY),[])
        self.assertEqual(adapter.french_listings(
            HTML.replace("<h1>Howlin’ Jaws</h1>","<h1>Other band</h1>"),DAY),[])
        self.assertEqual(adapter.french_listings(
            HTML.replace("Roubaix","Bruxelles BE"),DAY)[0],
            ("2026-11-18","PARIS","Trabendo"))
        self.assertEqual(adapter.french_listings(
            HTML.replace("Cave aux Poètes","International Festival"),DAY)[0],
            ("2026-11-18","PARIS","Trabendo"))

    def test_review_only_and_known_venue_not_inferred(self):
        rows=adapter.candidates(HTML,SOURCE,"Howlin' Jaws",CATALOG,DAY)
        self.assertEqual(len(rows),12)
        self.assertEqual(len({x["candidateId"] for x in rows}),12)
        self.assertTrue(all(x["reviewRequired"] and
                            not x["publicationAllowed"] for x in rows))
        self.assertTrue(all(x["countryToVerify"] and
                            not x["countryVerifiedFromOfficialListing"]
                            for x in rows))
        self.assertTrue(all("artistIds" not in x and
                            "time" not in x and "latitude" not in x for x in rows))
        ren=next(x for x in rows if x["date"]=="2026-12-10")
        self.assertEqual(ren["city"],"Rennes")
        self.assertEqual(ren["venue"],"MeM")
        self.assertIsNone(ren["venueIdIfKnown"])
        self.assertTrue(ren["newVenueToReview"])

    def test_dates_coupees_par_des_balises_sont_reconstruites(self):
        fragmented = HTML.replace(
            "<p>10\n nov. 2026</p>",
            "<p><span>10</span><span>nov.</span><span>2026</span></p>"
        ).replace(
            "<p>18 nov. 2026</p>",
            "<p><strong>18</strong> <span>nov.</span> 2026</p>"
        ).replace(
            "<p>27 févr. 2027</p>",
            "<p>27 <em>févr.</em> <b>2027</b></p>"
        )
        self.assertNotEqual(fragmented, HTML)
        self.assertEqual(
            adapter.french_listings(fragmented, DAY),
            adapter.french_listings(HTML, DAY))
        self.assertEqual(
            len(adapter.candidates(fragmented, SOURCE, "Howlin' Jaws",
                                   CATALOG, DAY)), 12)

    def test_date_fragmentaire_refusee_sans_annee_et_ville(self):
        bad = """<h1>Howlin' Jaws</h1><h2>Concerts</h2>
        <h3>Dates à venir</h3><p>10 <span>nov.</span></p>
        <p>Roubaix</p><p>Cave aux Poètes</p>
        <p>20 <span>nov.</span> <span>2026</span></p>
        <p>Ville étrangère</p><p>Club X</p>
        <h3>Dates passées</h3>"""
        self.assertEqual(adapter.french_listings(bad, DAY), [])

    def test_page_shape_diagnostics_are_bounded_and_no_html_leaks(self):
        shape = adapter.page_shape(HTML)
        self.assertTrue(shape["artistTitleFound"])
        self.assertTrue(shape["concertsHeadingFound"])
        self.assertTrue(shape["upcomingHeadingFound"])
        self.assertTrue(shape["pastHeadingFound"])
        self.assertEqual(shape["completeDateTokens"], 14)
        self.assertGreater(shape["visibleTokens"], 30)
        self.assertEqual(
            set(shape), {"htmlChars", "visibleTokens", "artistTitleFound",
                         "concertsHeadingFound", "upcomingHeadingFound",
                         "pastHeadingFound", "completeDateTokens"})
        missing = adapter.page_shape("<html><h1>Page inaccessible</h1></html>")
        self.assertFalse(missing["artistTitleFound"])
        self.assertFalse(missing["upcomingHeadingFound"])
        self.assertEqual(missing["completeDateTokens"], 0)

    def test_source_identity_protected(self):
        for changed in (dict(SOURCE, artistId="other"),
                        dict(SOURCE, sourceRole="artist_official"),
                        dict(SOURCE, adapter="fake")):
            with self.assertRaises(ValueError):
                adapter.candidates(HTML,changed,"Howlin' Jaws",CATALOG,DAY)

    def test_scan_uses_adapter_without_approving_any_candidate(self):
        def fake_fetch(url, **kwargs):
            self.assertEqual(url,SOURCE["url"])
            return HTML,url
        config={"schema":"grossesondes.concert.artist_tour_sources.v1",
                "sources":[SOURCE]}
        rows,checks=discovery.scan(CATALOG,config,DAY,max_sources=1,
                                   fetch=fake_fetch,
                                   robots=lambda url, cache:True)
        self.assertEqual(len(rows),12)
        self.assertEqual(checks[0]["status"],"parsed_tour")
        self.assertEqual(checks[0]["candidateCount"],12)
        self.assertEqual(checks[0]["officialTourEntries"],12)
        self.assertTrue(all(not x["publicationAllowed"] for x in rows))


if __name__=="__main__":
    unittest.main()
