"""Official Hydrophone SPIP / festival / date-year invariants, no network."""
import datetime as dt
import sys
import unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parent))
import hydrophone_adapter as h
import discover

SOURCE={"id":"venue-source-011","name":"Hydrophone","city":"Lorient",
        "department":"56","priority":"P1","url":"https://hydrophone.fr/",
        "adapter":"hydrophone_spip_review","maxDetailPagesPerRun":9}
EVENT="https://hydrophone.fr/REVNOIR-ICE-SEALED-EYES.html"
MERYL="https://hydrophone.fr/MERYL-STREEK-CHEST-LIBRARY-CARD.html"

def card(name="REVNOIR + ICE SEALED EYES",href="REVNOIR-ICE-SEALED-EYES.html",
         day="mer. 10 févr. / 20h",kind="Concert",badges=""):
    return (f'<div class="agenda-item col-md-6 col-lg-4"><a href="{href}">'
        '<div class="divImg"><img src="x.jpg"></div>'
        '<div class="divTexte d-flex"><div><h3>'+day+'</h3><h3>'+kind+'</h3></div>'
        '<div class="item-container"><button>'+badges+'</button>'
        '<div class="agenda-item-nom"><div><H3>'+name+'</H3></div></div></div>'
        '</div></a></div>')

def detail(title="REVNOIR + ICE SEALED EYES",day="mer. 10 févr.",
           time="20h00",room="Hydrophone - Grande salle",genre="metalcore"):
    return ('<html><body><section><h1>'+title+'</h1>'
        '<p><strong>REVNOIR</strong> Un groupe de '+genre+' et metal moderne.</p>'
        '<div><h3>Concert</h3><h2>'+day+'</h2><h4>'+time+'</h4>'
        '<h4>'+room+'</h4></div><h4>Infos</h4>En voir plus</section></body></html>')

class HydrophoneTests(unittest.TestCase):
    def test_official_card_and_proven_date(self):
        cards=h.agenda_cards(card())
        self.assertEqual(len(cards),1)
        self.assertEqual(cards[0]["clock"],"20:00")
        x=h.candidate(detail(),EVENT,cards[0],SOURCE,"2026-11-02")
        self.assertEqual(x["date"],"2027-02-10")
        self.assertEqual(x["localTime"],"20:00")
        self.assertEqual(x["venueCatalogueId"],"hydrophone-lorient")
        self.assertFalse(x["publicationAllowed"])
        self.assertTrue(x["yearEvidence"].startswith("https://www.fnacspectacles.com"))

    def test_no_auto_year_from_day_month(self):
        c=h.agenda_cards(card(name="MERYL STREEK + CHEST. + LIBRARY CARD",
                      href="MERYL-STREEK-CHEST-LIBRARY-CARD.html",
                      day="ven. 06 nov. / 20h30"))[0]
        with self.assertRaisesRegex(ValueError,"year"):
            h.candidate(detail(title="MERYL STREEK + CHEST. + LIBRARY CARD",
                    day="ven. 06 nov.",time="20h30"),MERYL,c,SOURCE,"2026-11-02")

    def test_festival_context_excluded_even_if_punk(self):
        c=h.agenda_cards(card(name="MERYL STREEK + CHEST. + LIBRARY CARD",
                        href="MERYL-STREEK-CHEST-LIBRARY-CARD.html",
                        day="ven. 06 nov. / 20h30",
                        badges="Les Indisciplinées"))[0]
        self.assertTrue(c["festivalContext"])
        with self.assertRaisesRegex(ValueError,"Festival"):
            h.candidate(detail(title="MERYL STREEK + CHEST. + LIBRARY CARD",
                    day="ven. 06 nov.",time="20h30"),MERYL,c,SOURCE,"2026-11-02")

    def test_nonconcert_and_school_shows_rejected(self):
        self.assertEqual(h.agenda_cards(card(kind="Projection")),[])
        c=h.agenda_cards(card(kind="Concert scolaire"))[0]
        self.assertTrue(c["blocked"])
        self.assertTrue(h.agenda_cards(card(name="REVNOIR Festival"))[0]["festivalContext"])

    def test_no_date_or_bad_weekday(self):
        self.assertEqual(h.agenda_cards(card(day="Demain à 20h")),[])
        c=h.agenda_cards(card(day="sam. 10 févr. / 20h"))[0]
        with self.assertRaisesRegex(ValueError,"contradicts"):
            h.candidate(detail(day="sam. 10 févr."),EVENT,c,SOURCE,"2026-11-02")
        c=h.agenda_cards(card())[0]
        with self.assertRaisesRegex(ValueError,"individual page"):
            h.candidate(detail(day="jeu. 10 févr."),EVENT,c,SOURCE,"2026-11-02")

    def test_no_faked_room_or_start_time(self):
        c=h.agenda_cards(card())[0]
        with self.assertRaisesRegex(ValueError,"room"):
            h.candidate(detail(room="Grande scène Lorient"),EVENT,c,SOURCE,"2026-11-02")
        with self.assertRaisesRegex(ValueError,"Clock"):
            h.candidate(detail(time="21h30"),EVENT,c,SOURCE,"2026-11-02")

    def test_exact_domain_and_query_restriction(self):
        for url in ("http://hydrophone.fr/REVNOIR-ICE-SEALED-EYES.html",
                    "https://evil.example/REVNOIR-ICE-SEALED-EYES.html",
                    "https://hydrophone.fr/REVNOIR-ICE-SEALED-EYES.html?secret=1",
                    "https://hydrophone.fr/-Agenda-.html"):
            self.assertIsNone(h.official_url(url))
        self.assertEqual(h.official_url(
            "https://www.hydrophone.fr/REVNOIR-ICE-SEALED-EYES.html"),EVENT)

    def test_duplicate_unchanged_and_no_publication(self):
        c=h.agenda_cards(card())[0]
        x=h.candidate(detail(),EVENT,c,SOURCE,"2026-11-02")
        discover.mark_match(x,{("officialUrl",EVENT)})
        self.assertTrue(x["possibleExistingConcert"])
        self.assertFalse(x["publicationAllowed"])

    def test_integration_hydrate_verified_but_not_festival(self):
        page=card()+card(name="MERYL STREEK + CHEST. + LIBRARY CARD",
                        href="MERYL-STREEK-CHEST-LIBRARY-CARD.html",
                        day="ven. 06 nov. / 20h30",badges="Les Indisciplinées")
        def fetch(url,**kwargs):
            if url==SOURCE["url"]:return page,url
            if url==EVENT:return detail(),url
            if url==MERYL:return detail(title="MERYL STREEK + CHEST. + LIBRARY CARD",
                              day="ven. 06 nov.",time="20h30"),url
            raise AssertionError(url)
        with mock.patch.object(discover,"robots_allow",return_value=True), \
             mock.patch.object(discover,"download",side_effect=fetch):
            report=[]
            rows=discover.scan_venues({"venues":[SOURCE]},set(),
                                       dt.date(2026,11,2),report)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["date"],"2027-02-10")
        diag=report[0]["adapterDiagnostic"]
        self.assertEqual(diag["festivalAndNonconcertFiltered"],1)
        self.assertEqual(diag["datedGenreLeads"],1)
        self.assertFalse(diag["publicationAllowed"])

if __name__=="__main__":unittest.main()
