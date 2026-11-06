"""Offline examples from official first-party Backstage and Forum detail layouts."""
import copy
import datetime as dt
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0,str(Path(__file__).resolve().parent))
import club_pages as c
import discover as d

BACK = {
    "name":"Backstage By The Mill","city":"Paris","department":"75",
    "priority":"P1","adapter":"backstage_individual_details",
    "maxDetailPagesPerRun":6,
    "url":"https://www.backstage-btm.com/agenda/"
}
FORUM = {
    "name":"Le Forum de Vauréal","city":"Vauréal","department":"95",
    "priority":"P1","adapter":"forum_individual_details",
    "maxDetailPagesPerRun":6,
    "url":"https://leforum.cergypontoise.fr/agenda"
}
BACK_URL="https://www.backstage-btm.com/agenda/cage-fight/"
FORUM_URL="https://leforum.cergypontoise.fr/agenda/motocultor-across-europe-tour-2027"
BACK_HTML="""<html><nav><h1>Concerts Paris 2034</h1></nav><main><article>
<h1>CAGE FIGHT</h1><p>metal</p><p>11/11/2026</p>
<p>O’Sullivans By The Mill, 92 bis bd de Clichy - Paris</p>
<p>Album nouvellement annoncé en 2027</p></article></main></html>"""
FORUM_HTML="""<html><nav>Festival metal</nav><main><article>
Agenda HARD ROCK METAL
<h1>MOTOCULTOR FESTIVAL : "ACROSS EUROPE TOUR 2027" RHAPSODY OF FIRE + SERIOUS BLACK</h1>
<p>+ SUBMASK + AEON GODS + ROCK OUT</p>
<p>Production : Le Forum</p>
<p>Le Forum, Grande Salle • Placement libre</p>
<p><b>Début du concert :</b> 19h</p>
<p>Rendez-vous au Forum le 15 janvier 2027 à partir de 19h !</p>
<h2>RHAPSODY OF FIRE</h2><p>Biographie publiée en 2026.</p>
</article></main></html>"""
FORUM_UNDATED="""<main><article>BLACK METAL METAL
<h1>WOLVES IN THE THRONE ROOM</h1><p>+ WORM + FINAL DOSE</p>
<p>Production : Le Forum</p><p>Le Forum, Grande Salle</p>
<p>Wolves in the Throne Room débarquent au Forum samedi 7 novembre à 18h.</p>
<h2>WOLVES IN THE THRONE ROOM</h2>
<p>Nouvel album 2026, concerts en 2027.</p></article></main>"""

class ClubPagesTests(unittest.TestCase):
    def test_backstage_live_header_date_venue_and_genre(self):
        a=c.detail_candidate(BACK_HTML,BACK_URL,BACK,"2026-11-02","backstage")
        self.assertEqual((a["date"],a["name"],a["city"]),
                         ("2026-11-11","CAGE FIGHT","Paris"))
        self.assertEqual(a["localTime"],None)
        self.assertFalse(a["publicationAllowed"])
        self.assertTrue(a["reviewRequired"])
        self.assertFalse(a["genreToConfirm"])
        self.assertEqual(a["sourceUrl"],BACK_URL)

    def test_backstage_cancelled_postponed_and_no_fake_year(self):
        for case in (
            BACK_HTML.replace("<p>Album nouvellement annoncé en 2027</p>",
                              "<p>Annulé</p>"),
            BACK_HTML.replace("11/11/2026","11/11/26"),
            BACK_HTML.replace("11/11/2026","30/02/2027"),
            BACK_HTML.replace("<p>metal</p>","<p>electro pop</p>"),
            BACK_HTML.replace("By The Mill","Autre Salle"),
        ):
            with self.subTest(page=case[:100]):
                with self.assertRaises(ValueError):
                    c.detail_candidate(case,BACK_URL,BACK,"2026-11-02","backstage")

    def test_forum_explicit_event_date_and_genre(self):
        a=c.detail_candidate(FORUM_HTML,FORUM_URL,FORUM,
                             "2026-11-02","forum")
        self.assertEqual(a["date"],"2027-01-15")
        self.assertEqual(a["localTime"],None)
        self.assertEqual(a["city"],"Vauréal")
        self.assertFalse(a["publicationAllowed"])
        self.assertIn("HARD ROCK",a["classification"][0].upper())

    def test_forum_never_infers_year_from_publication_or_bio(self):
        with self.assertRaises(ValueError):
            c.detail_candidate(FORUM_UNDATED,
                "https://leforum.cergypontoise.fr/agenda/wolves-throne-room",
                FORUM,"2026-11-02","forum")
        # The generic category chips live on the page, but the concert year
        # is absent: neither today nor the biography can provide it.
        p=FORUM_HTML.replace("15 janvier 2027","15 janvier")
        with self.assertRaises(ValueError):
            c.detail_candidate(p,FORUM_URL,FORUM,"2026-11-02","forum")
        p=FORUM_HTML.replace("HARD ROCK METAL","RAP ELECTRO")
        with self.assertRaises(ValueError):
            c.detail_candidate(p,FORUM_URL,FORUM,"2026-11-02","forum")

    def test_exact_paths_scheme_domain_query_credentials(self):
        self.assertTrue(c.exact_detail_url(BACK_URL,"backstage"))
        self.assertTrue(c.exact_detail_url(FORUM_URL,"forum"))
        for url in (
            "https://www.backstage-btm.com/agenda/",
            "http://www.backstage-btm.com/agenda/cage-fight/",
            "https://www.backstage-btm.com/agenda/cage-fight/?state=cancelled",
            "https://www.backstage-btm.com/agenda/cage-fight/#foo",
            "https://www.backstage-btm.com.evil.test/agenda/cage-fight/",
            "https://www.backstage-btm.com@evil.test/agenda/cage-fight/",
            "https://www.backstage-btm.com/agenda/cage-fight/and-more/",
        ):
            with self.subTest(url=url):
                self.assertFalse(c.exact_detail_url(url,"backstage"))

    def test_listing_is_only_an_exact_same_host_url_index(self):
        page=("<html><a href='/agenda/cage-fight/'>a</a>"
              "<a href='/agenda/cage-fight/'>duplicate</a>"
              "<a href='https://evil.test/agenda/bad/'>external</a>"
              "<a href='/agenda/'>generic</a>"
              "<a href='/agenda/other-event/?redirect=1'>query</a></html>")
        self.assertEqual(c.detail_urls(page,BACK["url"],"backstage"),[BACK_URL])
        with self.assertRaises(ValueError):
            c.detail_urls(page,"https://fake.test/agenda/","backstage")

    def test_integration_private_discovery_preserves_no_publication(self):
        page="<html><a href='/agenda/cage-fight/'>CAGE FIGHT</a></html>"
        pages={BACK["url"]:(page,BACK["url"]),BACK_URL:(BACK_HTML,BACK_URL)}
        with mock.patch.object(d,"robots_allow",return_value=True), \
             mock.patch.object(d,"download",side_effect=lambda url,*a,**k:pages[url]):
            report=[]
            found=d.scan_venues({"venues":[BACK]},set(),
                                dt.date(2026,11,2),report,max_p2=0)
        leads=[x for x in found if x["source"]=="agenda_officiel_backstage_detail"]
        self.assertEqual(len(leads),1)
        self.assertEqual(report[0]["adapterDiagnostic"]["datedGenreLeads"],1)
        self.assertFalse(leads[0]["publicationAllowed"])
        self.assertTrue(leads[0]["reviewRequired"])

    def test_forum_missing_year_has_zero_dated_leads(self):
        page="<html><a href='/agenda/wolves-throne-room'>Wolves</a></html>"
        url="https://leforum.cergypontoise.fr/agenda/wolves-throne-room"
        pages={FORUM["url"]:(page,FORUM["url"]),url:(FORUM_UNDATED,url)}
        with mock.patch.object(d,"robots_allow",return_value=True), \
             mock.patch.object(d,"download",side_effect=lambda url,*a,**k:pages[url]):
            report=[]
            found=d.scan_venues({"venues":[FORUM]},set(),
                                dt.date(2026,11,2),report,max_p2=0)
        self.assertFalse([x for x in found if x["source"]=="agenda_officiel_forum_detail"])
        self.assertEqual(report[0]["adapterDiagnostic"]["undatedOrNotMetal"],1)

if __name__=="__main__":
    unittest.main()
