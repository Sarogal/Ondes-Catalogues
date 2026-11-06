"""Offline Antipode Rennes first-party adapter tests; no raw lead publishes."""
import datetime as dt
import json
from pathlib import Path
import unittest
from unittest import mock

import antipode_adapter as a
import discover
import triage

ROOT=Path(__file__).resolve().parent
DAY="2026-11-03"
SOURCE={
    "id":"official-gap-20261103-antipode-rennes",
    "name":"Antipode","city":"Rennes","department":"35",
    "priority":"P1","url":a.AGENDA,"adapter":"antipode_official_detail_review",
    "maxDetailPagesPerRun":8,"maxAgendaPagesPerRun":1,
    "publish_automatically":False,
}
GIRLS="https://antipode-rennes.fr/agenda/girls-hawaii-2026"
PINEAPPLE="https://antipode-rennes.fr/agenda/pineapple-thief-2027"
DIIV="https://antipode-rennes.fr/agenda/diiv-2027"


def card(url,day,headline,genre="Rock",note="",kind="Concert",extra=""):
    return ('<a class="agenda-card" href="'+url+'"><div class="date">'
            +day+'</div><h3>'+headline+'</h3>'
            '<p>'+kind+'</p><span>'+genre+'</span><p>'+note+'</p>'+extra+'</a>')


def detail(title="Girls in Hawaii + Chaton Laveur",day="sam. 12 déc. 2026",
           room="Antipode La Grande Scène",status="",
           doors="Ouverture des portes : 20h00",
           start="Début des concerts : 20h30",
           organizer="Organisé par Antipode"):
    return ('<main><header><p>'+day+'</p><h1>'+title+'</h1>'
            '<p>Rock</p><p>Concert</p><p>'+room+'</p></header>'
            '<article><p>'+organizer+'</p><p>'+doors+'</p><p>'+start+'</p>'
            '<p>'+status+'</p><p>Sur scène ce groupe est excellent.</p>'
            '</article><section><h2>Informations sur les événements</h2>'
            '<p>Antipode Parvis Agnès Varda 75 avenue Jules Maniez Rennes</p>'
            '<h2>Nous vous recommandons également…</h2>'
            '<a href="/agenda/else">Autre spectacle metal complet</a>'
            '</section></main>')


def agenda():
    return (card("/agenda/girls-hawaii-2026","sam. 12 déc. 2026",
                 "Girls in Hawaii + Chaton Laveur",note="Complet")
            +card("/agenda/pineapple-thief-2027","mar. 09 mars 2027",
                  "The Pineapple Thief")
            +card("/agenda/diiv-2027","mer. 02 juin 2027","DIIV",
                  genre="Rock")
            +card("/agenda/KT-2026-11-07-soir","sam. 07 nov. 2026",
                  "La Jungle + Adult DVD",note="Kool Thing",genre="Rock")
            +card("/agenda/atelier-2027","jeu. 05 mars 2027",
                  "Atelier guitare",genre="Metal")
            +card("/agenda/pop-2027","jeu. 18 mars 2027",
                  "Chanteuse pop",genre="Pop")
            +card("/agenda/undated","22 mars","Groupe Rock")
            +card("/agenda/weekend","sam. 09 mai 2027",
                  "Weekend metal",extra="<p>dim. 10 mai 2027</p>")
            +card("/agenda/rap-2027","jeu. 12 mars 2027","Rap",genre="Rap"))


class AntipodeReviewTests(unittest.TestCase):
    def test_exact_first_party_url_and_unverified_pagination_rejected(self):
        self.assertEqual(a.official_link("/agenda/diiv-2027"),DIIV)
        self.assertTrue(a.valid_agenda(a.AGENDA))
        for wrong in ("https://evil.example/agenda/diiv-2027",
                      "https://antipode-rennes.fr.evil.example/agenda/diiv-2027",
                      "http://antipode-rennes.fr/agenda/diiv-2027",
                      "https://antipode-rennes.fr/agenda/archives",
                      "https://antipode-rennes.fr/agenda/diiv-2027?page=2",
                      "https://antipode-rennes.fr/agenda/diiv-2027#main"):
            self.assertIsNone(a.official_link(wrong),wrong)
        for url in (a.AGENDA+"?page=2",a.AGENDA+"#section",
                    "https://other.example/agenda"):
            self.assertFalse(a.valid_agenda(url))

    def test_full_calendar_date_year_required_and_multiple_dates_forbidden(self):
        self.assertEqual(a.full_dates("sam. 12 déc. 2026"),{"2026-12-12"})
        self.assertEqual(a.full_dates("mer. 02 juin 2027"),{"2027-06-02"})
        self.assertEqual(a.full_dates("2027-03-09T20:30:00"),{"2027-03-09"})
        self.assertEqual(a.full_dates("12 déc."),set())
        cards=a.agenda_cards(agenda(),today=DAY)
        self.assertEqual({x["url"] for x in cards},{GIRLS,PINEAPPLE,DIIV})
        self.assertEqual(next(x for x in cards if x["url"]==GIRLS)["statusNotice"],
                         "sold_out")
        self.assertEqual(a.agenda_cards(agenda(),today="2027-06-03"),[])

    def test_named_detail_music_start_is_not_door_time(self):
        row=next(x for x in a.agenda_cards(agenda(),today=DAY) if x["url"]==GIRLS)
        c=a.candidate(detail(),GIRLS,row,SOURCE,DAY)
        self.assertEqual(c["name"],"Girls in Hawaii + Chaton Laveur")
        self.assertEqual(c["leadArtist"],"Girls in Hawaii")
        self.assertEqual(c["candidateId"],"antipode:2026-12-12:girls-hawaii-2026")
        self.assertEqual(c["localTime"],"20:30")
        self.assertEqual(c["doorTime"],"20:00")
        self.assertTrue(c["soldOutNotice"])
        self.assertFalse(c["cancellationNotice"])
        self.assertEqual(c["statusNotice"],"sold_out")
        self.assertEqual(c["venueCatalogueId"],"antipode-rennes")
        self.assertTrue(c["reviewRequired"])
        self.assertFalse(c["publicationAllowed"])
        self.assertTrue(c["officialDetailFound"])

    def test_official_hanry_apero_concert_in_club_held_for_review(self):
        url="https://antipode-rennes.fr/agenda/hanry-2026"
        html=card("/agenda/hanry-2026","mer. 16 déc. 2026",
                  "Apéro-concert avec Hanry",genre="Rock",kind="Apéro-concert")
        rows=a.agenda_cards(html,today=DAY)
        self.assertEqual(len(rows),1)
        event=a.candidate(detail(title="Apéro-concert avec Hanry",
                 day="mer. 16 déc. 2026",room="Antipode - Le Club",
                 doors="Ouverture des portes : 19h00",
                 start="Début des concerts : 19h30"),url,rows[0],SOURCE,DAY)
        self.assertEqual(event["date"],"2026-12-16")
        self.assertEqual(event["leadArtist"],"Hanry")
        self.assertEqual(event["venueHall"],"Le Club")
        self.assertEqual(event["localTime"],"19:30")
        self.assertEqual(event["doorTime"],"19:00")
        self.assertEqual(event["genreEvidenceScope"],"official_event_card")
        review=triage.triage(event,catalogue={})
        self.assertEqual(review["reviewBucket"],"genre_tag_review")
        self.assertFalse(review["publicationAllowed"])
        # A casual description of a Club visit does not prove the room.
        with self.assertRaises(ValueError):
            a.candidate(detail(title="Apéro-concert avec Hanry",
                  day="mer. 16 déc. 2026",
                  room="Visite de l'Antipode puis rendez-vous au Club"),
                  url,rows[0],SOURCE,DAY)

    def test_cancellation_reported_not_published_and_no_time_guess(self):
        row=a.agenda_cards(agenda(),today=DAY)[0]
        cancelled=a.candidate(detail(status="Annulé",start=""),
                              row["url"],row,SOURCE,DAY)
        self.assertEqual(cancelled["statusNotice"],"cancelled")
        self.assertTrue(cancelled["cancellationNotice"])
        self.assertIsNone(cancelled["localTime"])
        self.assertFalse(cancelled["publicationAllowed"])
        not_start=a.candidate(detail(start="Portes : 20h30"),
                              row["url"],row,SOURCE,DAY)
        self.assertIsNone(not_start["localTime"])
        self.assertEqual(not_start["doorTime"],"20:00")

    def test_reject_transplanted_title_room_date_and_biography(self):
        row=next(x for x in a.agenda_cards(agenda(),today=DAY) if x["url"]==GIRLS)
        for html,src in (
            (detail(room="Le Liberté Rennes"),SOURCE),
            (detail(title="Invented Act"),SOURCE),
            (detail(day="sam. 13 déc. 2026"),SOURCE),
            (detail().replace("Antipode La Grande Scène",
                              "Salle hors les murs à Rennes"),SOURCE),
            (detail(),{**SOURCE,"city":"Nantes"}),
        ):
            with self.subTest(variant=str(html)[:30]):
                with self.assertRaises(ValueError):
                    a.candidate(html,GIRLS,row,src,DAY)
        missing_heading=detail().replace("<h1>","<h4>").replace("</h1>","</h4>")
        with self.assertRaises(ValueError):
            a.candidate(missing_heading,GIRLS,row,SOURCE,DAY)

    def test_existing_revisited_and_unseen_first(self):
        cards=a.agenda_cards(agenda(),today=DAY)
        known={("officialUrl",GIRLS),("officialUrl",PINEAPPLE)}
        s=a.selected_cards(cards,known,DAY,limit=3)
        self.assertIn(DIIV,[c["url"] for c in s])
        self.assertTrue(set([GIRLS,PINEAPPLE]).intersection(
            {x["url"] for x in s}))
        self.assertEqual(len(a.selected_cards(cards,known,DAY,limit=1)),1)

    def test_live_discovery_is_read_only_and_dedupes_by_official_link(self):
        pages={
            a.AGENDA:agenda(),
            GIRLS:detail(),
            PINEAPPLE:detail(title="The Pineapple Thief",
                             day="mar. 09 mars 2027",organizer="Organisé par Garmonbozia"),
            DIIV:detail(title="DIIV",day="mer. 02 juin 2027",
                        organizer="Organisé par Antipode"),
        }
        seen=[]
        def fetch(url,**kw):
            seen.append(url)
            if url in pages:return pages[url],url
            raise AssertionError("Unexpected network or pagination "+url)
        checks=[]
        with mock.patch.object(discover,"download",side_effect=fetch),\
             mock.patch.object(discover,"robots_allow",return_value=True):
            result=discover.scan_venues({"venues":[SOURCE]},
                {("officialUrl",GIRLS),("officialUrl",PINEAPPLE)},
                dt.date.fromisoformat(DAY),checks)
        self.assertEqual(len(result),3)
        self.assertEqual(sum(not x["possibleExistingConcert"] for x in result),1)
        self.assertEqual({x["sourceUrl"] for x in result},{GIRLS,PINEAPPLE,DIIV})
        self.assertTrue(all(x["reviewRequired"] and not x["publicationAllowed"]
                            for x in result))
        self.assertEqual(checks[0]["adapterDiagnostic"]["datedGenreLeads"],3)
        self.assertEqual(checks[0]["adapterDiagnostic"]["alreadyLikelyPublished"],2)
        self.assertEqual(checks[0]["adapterDiagnostic"]["soldOutReviewNotices"],1)
        self.assertNotIn(a.AGENDA+"?page=1",seen)
        self.assertEqual(len(seen),4)

    def test_source_is_enabled_in_private_daily_veille_not_publication(self):
        cfg=json.loads((ROOT/"sources.json").read_text(encoding="utf-8"))
        rows=[s for s in cfg["venues"] if s["name"]=="Antipode"]
        self.assertEqual(len(rows),1)
        row=rows[0]
        self.assertEqual(row["priority"],"P1")
        self.assertEqual(row["adapter"],"antipode_official_detail_review")
        self.assertFalse(row["publish_automatically"])
        self.assertFalse(row["publicationAllowed"])
        self.assertEqual(row["maxAgendaPagesPerRun"],1)
        self.assertLessEqual(row["maxDetailPagesPerRun"],10)


if __name__=="__main__":
    unittest.main()
