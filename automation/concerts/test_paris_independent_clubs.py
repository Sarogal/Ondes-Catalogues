"""Conservative read-only Paris independent clubs tests, no network."""
from __future__ import annotations
import datetime as dt
from pathlib import Path
import sys
import unittest
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parent))
import maroquinerie_adapter as m
import boule_noire_adapter as b
import discover

M={"name":"La Maroquinerie","city":"Paris","department":"75",
   "url":"https://www.lamaroquinerie.fr/fr/agenda/",
   "adapter":"maroquinerie_official_detail_review",
   "maxDetailPagesPerRun":8,"priority":"P2"}
B={"name":"La Boule Noire","city":"Paris","department":"75",
   "url":"https://laboule-noire.fr/",
   "adapter":"boule_noire_official_detail_review",
   "maxDetailPagesPerRun":8,"priority":"P2"}
MU="https://www.lamaroquinerie.fr/fr/agenda/view/2212/allt/?of=7"
BU="https://laboule-noire.fr/ice-sealed-eyes/"
MLIST="<a href='/fr/agenda/view/2212/allt/?of=7'>Allt</a><a href='/fr/agenda/view/2142/zebrahead/?of=18'>Zebrahead</a>"
BLIST="<a href='/ice-sealed-eyes/'>Ice Sealed Eyes</a>"
MDOC="""<html><head><title>ALLT - La Maroquinerie - Agenda</title></head>
<body><h1>La Maroquinerie</h1><p>23 rue Boyer, 75020 Paris</p>
<h1>ALLT</h1><h3>10 novembre</h3><p>19:30</p><p>VERYSHOW présente ALLT</p>
<p>Formé en 2020, Allt est un groupe de metalcore progressif.</p>
<p>Retrouvez Allt le 10 novembre 2026 à la Maroquinerie (Paris)
avec Avralize et Bite Down.</p><p>Ouverture des portes à 19h30</p></body></html>"""
BDOC="""<html><head><title>ICE SEALED EYES - La Boule Noire</title></head>
<body><h1>ICE SEALED EYES</h1><time>2026-11-15 19:00:00</time>
<h2>DIMANCHE 15 NOVEMBRE 2026 - 19H00</h2>
<p>ICE SEALED EYES est un groupe de newcore basé à Bruxelles.</p>
<p>Première partie : Eiga, influences metalcore et hardcore.</p>
<p>120 BOULEVARD DE ROCHECHOUART - 75018 PARIS</p></body></html>"""

class ParisOfficialAdapters(unittest.TestCase):
    def test_maroquinerie_links_and_untrusted_query(self):
        self.assertEqual(m.detail_links(MLIST,M["url"])[0],MU)
        for bad in (
            MU+"#fragment",MU+"&url=https://evil.test",MU.replace("?of=7","?evil=1"),
            MU.replace("www.lamaroquinerie.fr","evil.test"),
            "http://www.lamaroquinerie.fr/fr/agenda/view/2212/allt/",
            "https://www.lamaroquinerie.fr/fr/agenda/"):
            self.assertFalse(m.valid_url(bad))
        with self.assertRaises(ValueError):
            m.detail_links(MLIST,"https://evil.test/fr/agenda/")

    def test_maroquinerie_named_full_date_and_no_invented_start(self):
        x=m.detail_candidate(MDOC,MU,M,"2026-11-02")
        self.assertEqual((x["date"],x["leadArtist"]),
                         ("2026-11-10","ALLT"))
        self.assertEqual(x["classification"],[])
        self.assertTrue(x["genreToConfirm"])
        self.assertTrue(x["lineupToConfirm"])
        self.assertIsNone(x["localTime"])
        self.assertFalse(x["publicationAllowed"])
        for bad in (
            MDOC.replace("10 novembre 2026","10 novembre"),
            MDOC.replace("Retrouvez Allt","Retrouvez UneAutreArtiste"),
            MDOC.replace("metalcore","electropop"),
            MDOC.replace("23 rue Boyer","Rue inconnue"),
            MDOC.replace("Retrouvez Allt le 10 novembre 2026",
                         "Retrouvez Allt le 10 novembre 2025"),
            MDOC.replace("VERYSHOW présente ALLT","Concert déplacé à l'Alhambra"),
            MDOC.replace("Ouverture des portes","Concert annulé. Ouverture des portes")
        ):
            with self.subTest(case=bad[-80:]):
                with self.assertRaises(ValueError):
                    m.detail_candidate(bad,MU,M,"2026-11-02")
        with self.assertRaises(ValueError):
            m.detail_candidate(MDOC,MU,dict(M,city="Lyon"),"2026-11-02")

    def test_boule_noire_requires_iso_and_french_date_plus_venue(self):
        x=b.detail_candidate(BDOC,BU,B,"2026-11-02")
        self.assertEqual(x["date"],"2026-11-15")
        self.assertEqual(x["name"],"ICE SEALED EYES")
        self.assertEqual(x["classification"],[])
        self.assertIsNone(x["localTime"])
        self.assertFalse(x["publicationAllowed"])
        for bad in (
            BDOC.replace("2026-11-15","2026-11-14"),
            BDOC.replace("15 NOVEMBRE 2026","16 NOVEMBRE 2026"),
            BDOC.replace("2026-11-15 19:00:00","Ouvre 19h00"),
            BDOC.replace("metalcore et hardcore","pop et electro").replace("newcore","pop"),
            BDOC.replace("ICE SEALED EYES - La Boule Noire","ICE SEALED EYES - La Cigale"),
            BDOC.replace("ICE SEALED EYES est","Concert annulé. ICE SEALED EYES est"),
        ):
            with self.subTest(case=bad[:75]):
                with self.assertRaises(ValueError):
                    b.detail_candidate(bad,BU,B,"2026-11-02")
        with self.assertRaises(ValueError):
            b.detail_candidate(BDOC,BU,B,"2026-12-01")

    def test_boule_noire_links_are_exact_and_not_navigation(self):
        listing=BLIST+"<a href='/ice-sealed-eyes/'>Dupe</a><a href='https://evil.test/ice-sealed-eyes/'>Wrong</a>"
        self.assertEqual(b.detail_links(listing,B["url"]),[BU])
        for bad in ("https://laboule-noire.fr/",
                    "https://evil.test/ice-sealed-eyes/",
                    BU+"?ref=1","http://laboule-noire.fr/ice-sealed-eyes/"):
            self.assertFalse(b.safe(bad))
        with self.assertRaises(ValueError):
            b.detail_links(listing,"https://evil.test/")

    def test_maroquinerie_real_listing_explicit_month_and_year_crosscheck(self):
        listpage="""<html><h1>Agenda</h1>
        <h3>← novembre →</h3><h3>2026</h3><ul>
        <li><a href='/fr/agenda/view/2212/allt/?of=7'>
          <h2>ALLT</h2><h3>10 novembre</h3><p>19:30</p></a></li>
        <li><a href='/fr/agenda/view/2180/horskh/?of=18'>
          <h2>HORSKH</h2><h3>21 novembre</h3><p>Première partie :
          WE ARE MAGONIA</p></a></li>
        <li><a href='/fr/agenda/view/2142/zebrahead/?of=17'>
          <h2>ZEBRAHEAD</h2><h3>20 novembre</h3>
          <p>Le concert est déplacé à l'Alhambra</p></a></li>
        <li><a href='/fr/agenda/view/2243/lost-in-kyiv/?of=47'>
          <h2>LOST IN KYIV</h2><h3>9 janvier</h3></a></li>
        </ul></html>"""
        dates=m.verified_calendar_dates(listpage,M["url"])
        h="https://www.lamaroquinerie.fr/fr/agenda/view/2180/horskh/?of=18"
        self.assertEqual(dates[h],("2026-11-21","horskh"))
        self.assertEqual(dates[MU],("2026-11-10","allt"))
        self.assertEqual(len(dates),2)
        detail="""<html><head><title>HORSKH - La Maroquinerie - Agenda</title></head>
        <body><p>Base Productions présente : HORSKH</p>
        <p>Première partie : WE ARE MAGONIA</p>
        <p>HORSKH est un groupe français de Metal, grunge et electro.</p>
        <p>La Maroquinerie - 23 Rue Boyer, 75020 Paris</p>
        <p>Ouverture des portes à 19h30</p></body></html>"""
        with self.assertRaises(ValueError):
            m.detail_candidate(detail,h,M,"2026-11-02")
        lead=m.detail_candidate(detail,h,M,"2026-11-02",
                                calendar_proof=dates[h])
        self.assertEqual((lead["date"],lead["name"]),("2026-11-21","HORSKH"))
        self.assertTrue(lead["lineupToConfirm"])
        self.assertFalse(lead["publicationAllowed"])
        self.assertNotEqual(dates[h],("2027-11-21","horskh"))
        for bad in (("2026-11-21","other-band"),
                    ("2025-11-21","horskh")):
            with self.subTest(bad=bad),self.assertRaises(ValueError):
                m.detail_candidate(detail,h,M,"2026-11-02",
                                   calendar_proof=bad)
        # An explicit named date on the detail must not disagree with
        # an otherwise matching official calendar row.
        conflicting=detail.replace(
            "Ouverture des portes à 19h30",
            "Retrouvez Horskh le 22 novembre 2026 à la Maroquinerie.")
        with self.assertRaises(ValueError):
            m.detail_candidate(conflicting,h,M,"2026-11-02",
                               calendar_proof=dates[h])

    def test_boule_noire_real_event_without_address_but_verified_title(self):
        real="""<html><head><title>ICE SEALED EYES - La Boule Noire</title></head>
        <body><h1>ICE SEALED EYES</h1>
        <p>En cours</p><p>2026-11-15 19:00:00</p>
        <p>DIMANCHE 15 NOVEMBRE 2026 - 19H00</p>
        <p>BASE PRODUCTIONS</p>
        <p>Ice Sealed Eyes est un groupe de newcore basé à Bruxelles.</p>
        <p>Première partie : <b>Eiga</b></p>
        <p>Eiga joue du metalcore et du hardcore.</p></body></html>"""
        lead=b.detail_candidate(real,BU,B,"2026-11-02")
        self.assertEqual(lead["date"],"2026-11-15")
        self.assertEqual(lead["leadArtist"],"ICE SEALED EYES")
        self.assertIsNone(lead["localTime"])
        self.assertFalse(lead["publicationAllowed"])
        with self.assertRaises(ValueError):
            b.detail_candidate(real.replace(
                "La Boule Noire</title>","La Cigale</title>"),
                BU,B,"2026-11-02")
        with self.assertRaises(ValueError):
            b.detail_candidate(real.replace("En cours","Annulé"),
                               BU,B,"2026-11-02")

    def test_integration_private_candidates_only(self):
        pages={M["url"]:(MLIST,M["url"]),MU:(MDOC,MU),
               B["url"]:(BLIST,B["url"]),BU:(BDOC,BU)}
        with mock.patch.object(discover,"robots_allow",return_value=True),\
             mock.patch.object(discover,"download",side_effect=lambda url,*a,**k:pages[url]):
            report=[]
            # P2 rotation: with 2 sources both are selected.
            rows=discover.scan_venues({"venues":[M,B]},set(),
                dt.date(2026,11,2),report,max_p2=2)
        matches=[x for x in rows if x["source"].startswith("agenda_officiel_") and
                 x["venue"] in ("La Boule Noire","La Maroquinerie")]
        self.assertEqual(len(matches),2)
        self.assertTrue(all(x["reviewRequired"] and not x["publicationAllowed"]
                            for x in matches))
        self.assertEqual([x["adapterDiagnostic"]["datedReviewLeads"] for x in report],
                         [1,1])

if __name__=="__main__":
    unittest.main()
