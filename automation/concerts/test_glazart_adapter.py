"""Offline primary-source Glazart URL/date/lineup security and integration tests."""
from __future__ import annotations

import datetime as dt
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0,str(Path(__file__).resolve().parent))
import discover as discovery
import glazart_adapter as glazart

SOURCE={
    "name":"Glazart","city":"Paris","department":"75",
    "priority":"P1","url":"https://www.glazart.com/agenda-concerts/portfolio-category/concert/",
    "adapter":"glazart_official_detail_review","maxDetailPagesPerRun":7,
    "publish_automatically":False
}
S_URL="https://www.glazart.com/28-11-26-concert-sunami-missing-link-extinguish/"
P_URL="https://www.glazart.com/24-03-27-concert-party-cannon-x-internal-bleeding/"
L_URL="https://www.glazart.com/06-11-26-concert-lagrimas/"
E_URL="https://www.glazart.com/04-11-26-concert-eyehategod-guest/"
SUNAMI="""<html><head><title>28.11.26 – Concert : SUNAMI + MISSING LINK + EXTINGUISH → GLAZART</title>
<script>annulation générale saison 2033</script></head>
<body><header>Concert metal années 2025/2028</header>
<main><p>SAMEDI 28.11 – CONCERT – Sunami</p><p>Terrorzone75 et Stronger Bookings présentent:</p>
<p>Sunami, Desolated, Missing Link et Extinguish a Paris le 28 Novembre 2026 au Glazart.</p>
<p>Sunami hardcore NYHC, Desolated et Extinguish en concert.</p>
<p>Ouverture des portes a 19h (pas un début de concert confirmé).</p></main></body></html>"""
PARTY="""<html><head><title>24.03.27 – Concert : Party Cannon x Internal bleeding → GLAZART</title></head>
<body><main><p>Mercredi — 24.03.27</p><p>Garmonbozia, en accord avec Echelon, présente :</p>
<p>□ PARTY CANNON (slam/death)<br/>□ INTERNAL BLEEDING (slam/death)
<br/>□ GUTTURAL SLUG (slam/death)</p><p>Paris, Glazart</p>
<p>mercredi 24 mars 2027</p><p>– ouverture 19h</p></main></body></html>"""
LAGRIMAS="""<html><head><title>06.11.26 – Concert : LAGRIMAS → GLAZART</title></head>
<body><main><p>Vendredi 06.11.26</p><p>Lagrimas débarque à Paris pour du screamo et hardcore.</p>
<p>info Glazart</p></main></body></html>"""
EYE="""<html><head><title>04.11.26 – Concert : EYEHATEGOD + GUEST → GLAZART</title></head>
<body><main><p>Mercredi 04.11.26</p><p>Garmonbozia présente Eyehategod.</p>
<p>Paris, Glazart</p><p>mercredi 04 novembre 2026</p></main></body></html>"""


class GlazartAdapterTests(unittest.TestCase):
    def test_links_are_unique_first_party_dated_event_pages_only(self):
        html=("<html><a href='/28-11-26-concert-sunami-missing-link-extinguish/'>Sunami</a>"
              "<a href='/28-11-26-concert-sunami-missing-link-extinguish/'>repeat</a>"
              "<a href='/24-03-27-concert-party-cannon-x-internal-bleeding/'>Party</a>"
              "<a href='https://www.glazart.com/24-03-27-concert-party-cannon-x-internal-bleeding/?redirect=1'>query</a>"
              "<a href='https://evil.test/28-11-26-concert-sunami-missing-link-extinguish/'>external</a>"
              "<a href='/agenda-concerts/'>agenda</a></html>")
        self.assertEqual(glazart.detail_links(html,SOURCE["url"]),[S_URL,P_URL])
        self.assertEqual(glazart.detail_links(html,SOURCE["url"],max_links=1),[S_URL])
        self.assertEqual(glazart.event_date(S_URL),dt.date(2026,11,28))
        self.assertEqual(glazart.event_date(P_URL),dt.date(2027,3,24))
        for bad in ("http://www.glazart.com/28-11-26-concert-test/",
                    "https://evil.test/28-11-26-concert-test/",
                    "https://www.glazart.com/28-11-26-concert-test/?ref=1",
                    "https://www.glazart.com/28-11-26-concert-test/#fragment",
                    "https://www.glazart.com@evil.test/28-11-26-concert-test/",
                    "https://www.glazart.com/99-11-26-concert-test/",
                    "https://www.glazart.com/agenda-concerts/portfolio-category/concert/"):
            with self.subTest(url=bad):
                self.assertIsNone(glazart.event_date(bad))
        with self.assertRaises(ValueError):
            glazart.detail_links(html,"https://fake.test/agenda")

    def test_detailed_venue_page_dates_and_shortened_lineups_become_review_leads(self):
        sunami=glazart.detail_candidate(SUNAMI,S_URL,SOURCE,"2026-11-02")
        self.assertEqual(sunami["date"],"2026-11-28")
        self.assertEqual(sunami["sourceUrl"],S_URL)
        self.assertEqual(sunami["leadArtist"],"SUNAMI")
        self.assertEqual(sunami["artistNamesToVerify"],
                         ["Sunami","Desolated","Missing Link","Extinguish"])
        self.assertEqual(sunami["classification"],[])
        self.assertIsNone(sunami["localTime"])
        self.assertFalse(sunami["publicationAllowed"])
        self.assertTrue(sunami["reviewRequired"])
        self.assertTrue(sunami["lineupToConfirm"])
        party=glazart.detail_candidate(PARTY,P_URL,SOURCE,"2026-11-02")
        self.assertEqual(party["artistNamesToVerify"],
                         ["PARTY CANNON","INTERNAL BLEEDING","GUTTURAL SLUG"])
        self.assertEqual(party["date"],"2027-03-24")
        self.assertTrue(party["genreToConfirm"])
        self.assertTrue(party["lineupToConfirm"])
        lagrimas=glazart.detail_candidate(LAGRIMAS,L_URL,SOURCE,"2026-11-02")
        self.assertEqual(lagrimas["date"],"2026-11-06")
        self.assertEqual(lagrimas["name"],"LAGRIMAS")
        self.assertEqual(lagrimas["artistNamesToVerify"],[])
        eye=glazart.detail_candidate(EYE,E_URL,SOURCE,"2026-11-02")
        self.assertIn("GUEST",eye["name"])
        self.assertTrue(eye["abbreviatedHeadline"])
        self.assertNotIn("GUEST",str(eye["artistNamesToVerify"]))

    def test_reject_only_url_date_nav_year_cancellation_and_source_spoof(self):
        for bad in (
            SUNAMI.replace("28 Novembre 2026","28 Novembre 2027"),
            SUNAMI.replace("28 Novembre 2026","28 Novembre"),
            SUNAMI.replace("Concert : SUNAMI","Concert : ANNULÉ SUNAMI"),
            SUNAMI.replace("28.11.26 – Concert","27.11.26 – Concert"),
            SUNAMI.replace("28.11.26 – Concert :","28.11.26 – FESTIVAL :"),
            SUNAMI.replace("<main>","<main><p>CONCERT ANNULÉ : report de la date.</p>")
        ):
            with self.subTest(case=bad[0:100]):
                with self.assertRaises(ValueError):
                    glazart.detail_candidate(bad,S_URL,SOURCE,"2026-11-02")
        with self.assertRaises(ValueError):
            glazart.detail_candidate(SUNAMI,S_URL,dict(SOURCE,city="Lyon"),"2026-11-02")
        with self.assertRaises(ValueError):
            glazart.detail_candidate(SUNAMI,S_URL,SOURCE,"2026-12-01")

    def test_no_genre_or_time_inferred_from_biography_or_opening_doors(self):
        event=glazart.detail_candidate(PARTY,P_URL,SOURCE,"2026-11-02")
        self.assertEqual(event["classification"],[])
        self.assertIsNone(event["localTime"])
        self.assertTrue(event["genreToConfirm"])
        self.assertFalse(event["publicationAllowed"])

    def test_discovery_integration_and_exact_url_duplicate_match(self):
        listing=("<html><a href='/28-11-26-concert-sunami-missing-link-extinguish/'>Sunami</a>"
                 "<a href='/24-03-27-concert-party-cannon-x-internal-bleeding/'>Party</a></html>")
        docs={SOURCE["url"]:(listing,SOURCE["url"]),
              S_URL:(SUNAMI,S_URL),P_URL:(PARTY,P_URL)}
        catalog={"artists":[{"id":"sunami","name":"Sunami"},
                            {"id":"desolated","name":"Desolated"}],
                 "venues":[{"id":"glazart-paris","name":"Glazart","city":"Paris"}],
                 "events":[{"id":"go-c-20261128-paris-sunami","date":"2026-11-28",
                            "venueId":"glazart-paris","artistIds":["sunami","desolated"],
                            "officialUrl":S_URL}]}
        known=discovery.make_known_keys(catalog)
        self.assertIn(("officialUrl",S_URL),known)
        with mock.patch.object(discovery,"robots_allow",return_value=True), \
             mock.patch.object(discovery,"download",side_effect=lambda url,*a,**k:docs[url]):
            report=[]
            leads=discovery.scan_venues({"venues":[SOURCE]},known,
                                       dt.date(2026,11,2),report,max_p2=0)
        matching=[l for l in leads if l["source"]=="agenda_officiel_glazart_detail"]
        self.assertEqual(len(matching),2)
        by_url={l["sourceUrl"]:l for l in matching}
        self.assertTrue(by_url[S_URL]["possibleExistingConcert"])
        self.assertFalse(by_url[P_URL]["possibleExistingConcert"])
        self.assertTrue(all(x["reviewRequired"] and not x["publicationAllowed"]
                            for x in matching))
        diagnostics=report[0]["adapterDiagnostic"]
        self.assertEqual(diagnostics["eventLinksFound"],2)
        self.assertEqual(diagnostics["datedReviewLeads"],2)
        self.assertEqual(diagnostics["likelyExisting"],1)
        self.assertEqual(diagnostics["lineupHints"],2)
        self.assertEqual(diagnostics["publicationAllowed"],False)


if __name__=="__main__":
    unittest.main()
