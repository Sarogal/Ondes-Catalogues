"""Atabal official first-party concert collector safety regression tests."""
import datetime as dt
import sys
import unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parent))
import atabal_adapter as a
import discover

BASE="https://www.atabal-biarritz.fr/agenda/concerts/"
ANESTESIA=BASE+"anestesia-erantzun-30-urte-horzdun-vendredi-11-decembre-2026/"
BURNING=BASE+"burning-heads-not-scientists-dead-krazukies-vendredi-14-mai-2027/"
FOREIGN=BASE+"bertrand-belin-gare-du-midi-vendredi-13-novembre-2026/"
SOURCE={"id":"venue-source-026","name":"Atabal","department":"64","city":"Biarritz",
        "priority":"P1","url":BASE,"adapter":"atabal_official_detail",
        "maxDetailPagesPerRun":12}

def agenda(*urls):
    return '<article>'+''.join(f'<a href="{u}"><h3>Official</h3></a>'
                               for u in urls)+'</article>'

def detail(date="11 décembre 2026",name="ANESTESIA",
           follow="Horzdun",genre="H-CORE",extra="",time="20H30"):
    return (
        '<article><section><picture></picture><p>'+date+' '+time+'</p>'
        '<p><h1>'+name+'</h1><h2>'+follow+'</h2></p></section>'
        '<p>'+extra+'</p><h2>'+name+'</h2>'
        '<p>Concert hardcore basque, guitares lourdes et riffs.</p>'
        '<h5>'+genre+'</h5>'
        '<h4>Vous devriez aimer:</h4>'
        '<ul><h3>SLIFT</h3><h5>01.02.27</h5></ul></article>'
    )

def burn():
    return detail(date="14 mai 2027",name="BURNING HEADS",
                  follow="NOT SCIENTISTS The Dead Krazukies",
                  genre="PUNK ROCK",
                  extra="Groupe phare du punk français et hardcore mélodique.")

class AtabalOfficial(unittest.TestCase):
    def test_links_are_exact_domain_dated_individual_no_generic(self):
        h=agenda(ANESTESIA,ANESTESIA,BURNING,
                 "https://evils.example/agenda/concerts/anestesia-vendredi-11-decembre-2026/",
                 BASE+"not-an-event/")
        self.assertEqual(len(a.cards(h)),2)
        for href in (ANESTESIA+"?auth=1",ANESTESIA.replace("https:","http:"),
                     "https://www.atabal-biarritz.fr/agenda/concerts/"):
            self.assertIsNone(a.link_ok(href))

    def test_reprogrammed_11_dec_is_current_without_old_oct_date(self):
        body=detail(extra="En raison d’un changement de planning, la date "
                          "initialement prévue le samedi 24 octobre, "
                          "est repoussée au vendredi 11 décembre.")
        row=a.candidate(body,ANESTESIA,a.cards(agenda(ANESTESIA))[0],
                        SOURCE,"2026-11-02")
        self.assertEqual(row["date"],"2026-12-11")
        self.assertEqual(row["name"],"ANESTESIA")
        self.assertEqual(row["classification"],["Hardcore"])
        self.assertIsNone(row["localTime"])
        self.assertFalse(row["publicationAllowed"])
        self.assertTrue(row["reviewRequired"])

    def test_future_burning_heads_punk_lead(self):
        row=a.candidate(burn(),BURNING,a.cards(agenda(BURNING))[0],
                        SOURCE,"2026-11-02")
        self.assertEqual(row["classification"],["Punk Rock"])
        self.assertEqual(row["date"],"2027-05-14")
        self.assertIn("burning-heads",row["sourceUrl"])

    def test_date_mismatch_excluded(self):
        card=a.cards(agenda(ANESTESIA))[0]
        with self.assertRaisesRegex(ValueError,"date"):
            a.candidate(detail(date="24 octobre 2026"),ANESTESIA,card,
                        SOURCE,"2026-11-02")
        with self.assertRaisesRegex(ValueError,"date"):
            a.candidate(detail(date="aucune date"),ANESTESIA,card,
                        SOURCE,"2026-11-02")

    def test_other_venue_and_cancelled_rejected(self):
        self.assertEqual(a.cards(agenda(BASE+"bertrand-belin-olivier-daguerre-vendredi-13-novembre-2026-gare-du-midi/")),[])
        row=a.cards(agenda(FOREIGN))[0]
        with self.assertRaisesRegex(ValueError,"Offsite"):
            a.candidate(detail(date="13 novembre 2026",
                               name="BERTRAND BELIN",extra="Gare du Midi, Biarritz"),
                        FOREIGN,row,SOURCE,"2026-11-02")
        with self.assertRaisesRegex(ValueError,"Cancelled"):
            a.candidate(detail(extra="Concert annulé."),ANESTESIA,
                        a.cards(agenda(ANESTESIA))[0],SOURCE,"2026-11-02")

    def test_unknown_genre_rejected_without_recommendation_leak(self):
        row=a.cards(agenda(ANESTESIA))[0]
        body=detail(genre="INDIE POP").replace(
            "Concert hardcore basque, guitares lourdes et riffs.",
            "Concert de musique électronique au pays basque.")
        with self.assertRaisesRegex(ValueError,"Genre"):
            a.candidate(body,ANESTESIA,row,SOURCE,"2026-11-02")

    def test_current_date_artist_title_and_no_doors_as_start(self):
        row=a.cards(agenda(ANESTESIA))[0]
        evt=a.candidate(detail(time="20H30, ouverture des portes 19H30"),
                        ANESTESIA,row,SOURCE,"2026-11-02")
        self.assertEqual(evt["name"],"ANESTESIA")
        self.assertIsNone(evt["localTime"])

    def test_scan_integrates_private_and_detects_existing_event(self):
        urls=(ANESTESIA,BURNING)
        def fake(url,**opts):
            if url==BASE:return agenda(*urls),url
            if url==ANESTESIA:return detail(),url
            if url==BURNING:return burn(),url
            raise AssertionError(url)
        with mock.patch.object(discover,"robots_allow",return_value=True),\
             mock.patch.object(discover,"download",side_effect=fake):
            diagnostics=[]
            found=discover.scan_venues({"venues":[SOURCE]},
                       {("officialUrl",BURNING)},dt.date(2026,11,2),diagnostics)
        self.assertEqual(len(found),2)
        self.assertTrue(next(r for r in found if r["sourceUrl"]==BURNING)[
            "possibleExistingConcert"])
        self.assertFalse(next(r for r in found if r["sourceUrl"]==ANESTESIA)[
            "possibleExistingConcert"])
        self.assertEqual(diagnostics[0]["adapterDiagnostic"]["datedGenreLeads"],2)
        self.assertTrue(all(r["publicationAllowed"] is False for r in found))

if __name__=="__main__":
    unittest.main()
