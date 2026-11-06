"""La Laiterie: dates officielles, page rotation et horaire des portes refuse."""
import datetime as dt
import unittest
from unittest.mock import patch

import discover
import laiterie_adapter as laiterie

AGENDA="https://www.artefact.org/la-laiterie/programmation/"
DETAIL="https://www.artefact.org/la-laiterie/evenements/igorrr-secret-chiefs-3-fange/"
SOURCE={"name":"La Laiterie","city":"Strasbourg","department":"67","url":AGENDA,
        "priority":"P1","adapter":"laiterie_official_detail_review",
        "maxDetailPagesPerRun":8,"publish_automatically":False}
LISTING="""<html><body><main>
    <a href="/la-laiterie/evenements/igorrr-secret-chiefs-3-fange/">IGORRR</a>
    <a href="/la-laiterie/programmation/page/2/">2</a>
    <a href="/la-laiterie/programmation/page/5/">5</a>
    <a href="https://other.example/la-laiterie/evenements/evil/">Evil</a>
</main></body></html>"""
DETAIL_HTML="""<html><main><section>
<p>Dimanche 4 avril 2027</p><p>Ouverture des portes à 17h30</p>
<p>EUROPEAN TOUR 2027</p>
<h1>IGORRR</h1><h2>+ SECRET CHIEFS 3 + FANGE</h2>
<p>Lieu</p><p>Laiterie, Grande Salle</p>
<p>Présentés par</p><p>Artefact PRL</p>
<p>Genre</p><p>#Extrem Métal Breakcore Baroque Experimental</p>
<p>Tarif prévente</p><p>31,5 €</p>
</section><section><h2>Artistes</h2></section></main></html>"""

class LaiterieAdapterTests(unittest.TestCase):
    def test_programme_limits_first_party_event_urls_and_pagination(self):
        self.assertEqual(laiterie.links(LISTING,AGENDA),[DETAIL])
        self.assertEqual(laiterie.max_agenda_page(LISTING,AGENDA),5)
        with self.assertRaises(ValueError):
            laiterie.links(LISTING,"https://other.example/foo")

    def test_full_dated_lineup_never_door_time_or_approval(self):
        x=laiterie.details(DETAIL_HTML,DETAIL,SOURCE,"2026-11-03")
        self.assertEqual(x["date"],"2027-04-04")
        self.assertEqual(x["name"],"IGORRR + SECRET CHIEFS 3 + FANGE")
        self.assertEqual(x["leadArtist"],"IGORRR")
        self.assertEqual(x["classification"],["Extrem Métal Breakcore Baroque Experimental"])
        self.assertIsNone(x["localTime"])
        self.assertFalse(x["publicationAllowed"])
        self.assertTrue(x["reviewRequired"])

    def test_ambiguity_wrong_genre_and_wrong_venue_are_held(self):
        cases=[
            ("no year",DETAIL_HTML.replace("Dimanche 4 avril 2027","Dimanche 4 avril")),
            ("wrong venue",DETAIL_HTML.replace("Laiterie, Grande Salle","Lieu externe")),
            ("wrong genre",DETAIL_HTML.replace("#Extrem Métal Breakcore Baroque Experimental","#Chanson")),
            ("cancelled",DETAIL_HTML.replace("EUROPEAN TOUR 2027","Concert ANNULÉ")),
            ("two dates",DETAIL_HTML.replace("EUROPEAN TOUR 2027","Vendredi 9 avril 2027")),
            ("no h1",DETAIL_HTML.replace("<h1>IGORRR</h1>","")),
        ]
        for label,body in cases:
            with self.subTest(label=label), self.assertRaises(ValueError):
                laiterie.details(body,DETAIL,SOURCE,"2026-11-03")
        with self.assertRaises(ValueError):
            laiterie.details(DETAIL_HTML,DETAIL.replace("artefact.org","example.org"),SOURCE,"2026-11-03")
        with self.assertRaises(ValueError):
            laiterie.details(DETAIL_HTML,DETAIL,{**SOURCE,"name":"La Cabane"},"2026-11-03")

    def test_venue_discovery_holds_known_event_and_disallows_publish(self):
        fakepages={AGENDA:LISTING,DETAIL:DETAIL_HTML}
        # The only indexed last page is deliberately sparse on this fixture.
        for n in range(2,6):
            fakepages[f"https://www.artefact.org/la-laiterie/programmation/page/{n}/"]="<html><main></main></html>"
        def download(url,**_kw):
            if url not in fakepages: raise ValueError("Unexpected external URL")
            return fakepages[url],url
        results=[]
        with patch.object(discover,"download",side_effect=download), \
             patch.object(discover,"robots_allow",return_value=True), \
             patch.object(discover.feeds,"feed_links",return_value={"ics":[],"rss":[]}):
            rows=discover.scan_venues({"venues":[SOURCE]},{("officialUrl",DETAIL)},
                                       dt.date(2026,11,3),results)
        self.assertEqual(len(rows),1)
        self.assertTrue(rows[0]["possibleExistingConcert"])
        self.assertFalse(rows[0]["publicationAllowed"])
        self.assertIsNone(rows[0]["localTime"])
        self.assertEqual(results[0]["adapterDiagnostic"]["datedGenreLeads"],1)
        self.assertEqual(results[0]["adapterDiagnostic"]["alreadyKnownUrls"],1)

if __name__=="__main__":
    unittest.main()
