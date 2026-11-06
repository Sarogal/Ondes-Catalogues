"""No-network regression tests for Bonjour Minuit daily discovery (read-only)."""
import datetime as dt
import json
from pathlib import Path
import unittest
from unittest import mock

import bonjour_minuit_adapter as bm
import discover
import triage

ROOT = Path(__file__).resolve().parent
DAY = "2026-11-03"
MAGMA = "https://bonjour-minuit.fr/evenement/magma-02dec26/"
SBRBS = "https://bonjour-minuit.fr/evenement/sbrbs-30janv27/"
PR2B = "https://bonjour-minuit.fr/evenement/pr2b-07nov26/"
RADIO = "https://bonjour-minuit.fr/evenement/sessionliveradioactiv-05nov26/"
EVENTS = [MAGMA, SBRBS, PR2B, RADIO]
SOURCE = {"id": "venue-source-012", "name": "Bonjour Minuit",
          "city": "Saint-Brieuc", "department": "22", "priority": "P1",
          "url": bm.AGENDA, "adapter": "bonjour_minuit_official_detail_review",
          "maxAgendaPagesPerRun": 1, "maxDetailPagesPerRun": 8,
          "publish_automatically": False, "publicationAllowed": False}


def agenda():
    return ('<main><h1>Agenda</h1><p>Les horaires annoncés sont ceux '
            "de l'ouverture des portes.</p>"
            + "".join(f'<a href="{url}">Concert et événement</a>'
                      for url in EVENTS)
            + '<a href="/agenda/archives/">Archives</a>'
            + '<a href="https://evil.example/evenement/fake-2027/">Fake</a>'
            + '<a href="/evenement/foo/?page=2">Unknown query</a>'
            + '<a href="https://bonjour-minuit.fr.evil.example/evenement/fake/">Fake</a>'
            + '</main>')


def event(title="Magma", date="mercredi 02 décembre 2026",
          room="Grande Salle • 20h00", artist="Magma",
          label="rock progressifFRA", pre="", bio="Magma invente un univers",
          after="", status="", extra_head=""):
    return (
        "<html><main><article><h1>" + title + "</h1>"
        "<p>" + date + "</p><p>" + room + "</p>"
        "<p>Déroulé :</p>"
        "<p>20h00 : ouverture des portes</p>"
        "<p>20h30 : " + artist + "</p>"
        "<p>Ces horaires sont donnés à titre indicatif "
        "et peuvent être modifiés en cas de besoin.</p>"
        + (f"<p>{status}</p>" if status else "")
        + pre + extra_head
        + "<h2>" + artist + "</h2><p>" + label + "</p>"
        "<p>" + bio + "</p>" + after
        + "</article></main></html>")


def sbrbs():
    return event(title="SBRBS release party Atoem Sarakiniko DJ Cup of Tea",
                 date="samedi 30 janvier 2027",
                 room="Grande Salle • 20h30",
                 artist="SBRBS release party",
                 label="rock indéSaint-Brieuc",
                 pre="<p>Début : 30 minutes après l'ouverture</p>",
                 bio="Le duo joue du rock.", after="<h2>Atoem</h2>"
                 "<p>electroFR</p><p>DJ</p>").replace(
                     "<p>20h00 : ouverture des portes</p>", "")


class BonjourMinuitTests(unittest.TestCase):
    def test_first_party_url_allowlist_no_unverified_query_or_redirect(self):
        self.assertEqual(bm.detail_url("/evenement/magma-02dec26/"), MAGMA)
        self.assertTrue(bm.valid_agenda(bm.AGENDA))
        for u in (
            "http://bonjour-minuit.fr/evenement/magma-02dec26/",
            "https://bonjour-minuit.fr.evil.example/evenement/fake/",
            "https://evil.example/evenement/fake/",
            "https://bonjour-minuit.fr/evenement/magma-02dec26/?page=2",
            "https://bonjour-minuit.fr/evenement/magma-02dec26/#x",
            "https://bonjour-minuit.fr/evenement/archives/",
            "https://bonjour-minuit.fr/agenda/",
            "https://bonjour-minuit.fr/evenement/magma-02dec26",
        ):
            with self.subTest(u=u):
                self.assertIsNone(bm.detail_url(u))
        for u in (bm.AGENDA+"?page=2",bm.AGENDA+"#fake",
                  "https://wrong.example/agenda/"):
            self.assertFalse(bm.valid_agenda(u))
        self.assertEqual(bm.agenda_links(agenda()), EVENTS)
        with self.assertRaises(ValueError):
            bm.agenda_links(agenda(),bm.AGENDA+"?page=2")

    def test_first_party_magma_title_date_hall_and_door_only(self):
        c = bm.candidate(event(), MAGMA, SOURCE, DAY)
        self.assertEqual((c["date"],c["leadArtist"],c["venueHall"]),
                         ("2026-12-02","Magma","La Grande Salle"))
        self.assertIn("Rock",c["classification"])
        self.assertEqual(c["doorTime"],"20:00")
        self.assertIsNone(c["localTime"])
        self.assertEqual(c["timeMeaning"],"unverified_music_start")
        self.assertTrue(c["officialDetailFound"])
        self.assertFalse(c["publicationAllowed"])
        self.assertTrue(c["reviewRequired"])
        self.assertEqual(c["genreEvidenceScope"],
                         "official_artist_in_event_detail")
        review=triage.triage(c,catalogue={})
        self.assertEqual(review["reviewBucket"],"genre_tag_review")
        self.assertFalse(review["publicationAllowed"])

    def test_sbrbs_multi_artist_indie_rock_but_no_guessed_stage_clock(self):
        c=bm.candidate(sbrbs(),SBRBS,SOURCE,DAY)
        self.assertEqual(c["date"],"2027-01-30")
        self.assertEqual(c["leadArtist"],"SBRBS")
        self.assertEqual(c["doorTime"],"20:30")
        self.assertIsNone(c["localTime"])
        self.assertEqual(c["venueHall"],"La Grande Salle")
        self.assertEqual(triage.triage(c,catalogue={})["reviewBucket"],
                         "genre_tag_review")

    def test_real_div_span_date_room_and_artist_badge(self):
        # Based on the first real GitHub Actions probe: H1 -> event DIV/SPAN
        # -> H2 -> style DIV/SPAN -> first paragraph is already biography.
        # None of the event header/style fields are <p> elements.
        page=(
            '<article><h1>Magma</h1>'
            '<div class="show-date"><span>mercredi</span><span>02</span>'
            '<span>décembre</span><span>2026</span></div>'
            '<div class="show-room"><span>Grande Salle</span>'
            '<span>20h00</span></div>'
            '<div>Déroulé : 20h00 : ouverture des portes</div>'
            '<div>Ces horaires sont donnés à titre indicatif.</div>'
            '<h2>Magma</h2>'
            '<div class="artist-genre"><span>rock progressif</span>'
            '<span>FRA</span></div>'
            '<p>L’énergie brute du groupe évoque 30 années de musique.</p>'
            '</article><footer><p>Cookies et politique de confidentialité.'
            ' Le menu du lieu comprend Rock et Metal.</p></footer>'
        )
        c=bm.candidate(page,MAGMA,SOURCE,DAY)
        self.assertEqual(c["date"],"2026-12-02")
        self.assertEqual(c["venueHall"],"La Grande Salle")
        self.assertEqual(c["leadArtist"],"Magma")
        self.assertEqual(c["doorTime"],"20:00")
        self.assertIsNone(c["localTime"])
        self.assertFalse(c["publicationAllowed"])
        no_badge=page.replace('rock progressif','chanson')
        with self.assertRaises(ValueError):
            bm.candidate(no_badge,MAGMA,SOURCE,DAY)
        no_year=page.replace('<span>2026</span>','<span></span>')
        with self.assertRaises(ValueError):
            bm.candidate(no_year,MAGMA,SOURCE,DAY)

    def test_radio_chanson_bio_punk_unapproved_without_explicit_artist_tag(self):
        radio=event(title="Session live Radio Activ' Mémoires Rebelles",
                    date="jeudi 05 novembre 2026",room="Club • 18h30",
                    artist="Mémoires Rebelles",label="protest songsCôtes d'Armor",
                    bio="Le rock, le punk et le metal sont une influence.")
        chanson=event(title="P.R2B Iris2000",date="samedi 07 novembre 2026",
                      artist="P.R2B",label="chanson electroFRA",
                      bio="Une façon presque punk de voir la vie !")
        for html,url in ((radio,RADIO),(chanson,PR2B)):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    bm.candidate(html,url,SOURCE,DAY)

    def test_forged_date_room_and_unrelated_bio_or_footer_are_held(self):
        cases=(
            event(date="mercredi 02 décembre"),   # No invented year from URL.
            event(date="mercredi 02 décembre 2026 et jeudi 03 décembre 2026"),
            event(date="mercredi 32 décembre 2026"),
            event(date="mercredi 02 décembre 2025"),
            event(room="Salle municipale • 20h00"),
            event(room="Grande Salle, Club • 20h00"),
            event(artist="Invented band",label="metalFRA"),
            event(label="chansonFRA",bio="Le projet se réclame du rock progressif."),
            event(title="Festival Magma"),
            event(title="Rencontre avec Magma"),
            event(title="Magma",label="electroFRA",
                  after="<h2>Un groupe rock</h2><p>rock indéFRA</p>"),
        )
        for html in cases:
            with self.subTest(case=html[:150]):
                with self.assertRaises(ValueError):
                    bm.candidate(html,MAGMA,SOURCE,DAY)
        with self.assertRaises(ValueError):
            bm.candidate(event(),MAGMA,{**SOURCE,"department":"29"},DAY)
        with self.assertRaises(ValueError):
            bm.candidate(event(),MAGMA+"?source=other",SOURCE,DAY)

    def test_soldout_and_postponed_alert_only_early_not_biography(self):
        for note,status in (("Concert complet !","sold_out"),
                            ("Événement annulé","cancelled"),
                            ("Concert reporté","postponed")):
            c=bm.candidate(event(status=note),MAGMA,SOURCE,DAY)
            self.assertEqual(c["statusNotice"],status)
            self.assertFalse(c["publicationAllowed"])
        c=bm.candidate(event(bio="Un album annulé et une tournée reportée."),
                       MAGMA,SOURCE,DAY)
        self.assertEqual(c["statusNotice"],"confirmed_unchecked")

    def test_rotation_never_fetches_more_than_bound_and_revisits(self):
        known={("officialUrl",MAGMA)}
        self.assertEqual(len(bm.choose(EVENTS,known,DAY,limit=2)),2)
        self.assertIn(MAGMA,bm.choose(EVENTS,known,DAY,limit=2))
        self.assertLessEqual(len(bm.choose(EVENTS*6,known,DAY,limit=100)),10)
        self.assertEqual(len(bm.choose([MAGMA],known,DAY,limit=8)),1)

    def test_daily_discovery_archives_only_relevant_named_official_pages(self):
        pages={bm.AGENDA:agenda(),MAGMA:event(),SBRBS:sbrbs(),
               PR2B:event(title="P.R2B Iris2000",
                          date="samedi 07 novembre 2026",
                          artist="P.R2B",label="chanson electroFRA"),
               RADIO:event(title="Session live Radio Activ' Mémoires Rebelles",
                           date="jeudi 05 novembre 2026",
                           room="Club • 18h30",artist="Mémoires Rebelles",
                           label="protest songsFRA")}
        seen=[]
        def fetch(url,**kw):
            seen.append(url)
            if url in pages:
                return pages[url],url
            raise AssertionError("Unexpected URL: "+url)
        checks=[]
        with mock.patch.object(discover,"download",side_effect=fetch), \
             mock.patch.object(discover,"robots_allow",return_value=True):
            rows=discover.scan_venues({"venues":[SOURCE]},
                  {("officialUrl",MAGMA)},dt.date.fromisoformat(DAY),checks)
        self.assertEqual(len(rows),2)
        self.assertEqual({r["sourceUrl"] for r in rows},{MAGMA,SBRBS})
        self.assertEqual(sum(r["possibleExistingConcert"] for r in rows),1)
        self.assertEqual(len(seen),5)
        self.assertTrue(all(not r["publicationAllowed"] for r in rows))
        d=checks[0]["adapterDiagnostic"]
        self.assertEqual(d["agendaPagesRead"],1)
        self.assertEqual(d["detailPagesRead"],4)
        self.assertEqual(d["datedGenreLeads"],2)
        self.assertEqual(d["heldOrIrrelevant"],2)
        self.assertEqual(d["alreadyLikelyPublished"],1)

    def test_robots_or_redirect_failure_cannot_result_in_publication(self):
        seen=[]
        def fetch(url,**kw):
            seen.append(url)
            if url==bm.AGENDA:return agenda(),url
            return event(),bm.AGENDA  # redirected detail: never valid
        checks=[]
        with mock.patch.object(discover,"download",side_effect=fetch), \
             mock.patch.object(discover,"robots_allow",
                  side_effect=lambda url,cache:url != SBRBS):
            rows=discover.scan_venues({"venues":[SOURCE]},set(),
                   dt.date.fromisoformat(DAY),checks)
        self.assertEqual(rows,[])
        self.assertGreaterEqual(checks[0]["adapterDiagnostic"]["detailErrors"],2)
        self.assertFalse(checks[0]["adapterDiagnostic"]["publicationAllowed"])

    def test_source_configured_p1_daily_and_no_unreviewed_publication(self):
        j=json.loads((ROOT/"sources.json").read_text(encoding="utf-8"))
        rows=[r for r in j["venues"] if r["name"]=="Bonjour Minuit"]
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["priority"],"P1")
        self.assertEqual(rows[0]["adapter"],
                         "bonjour_minuit_official_detail_review")
        self.assertEqual(rows[0]["maxAgendaPagesPerRun"],1)
        self.assertLessEqual(rows[0]["maxDetailPagesPerRun"],8)
        self.assertFalse(rows[0]["publish_automatically"])
        self.assertFalse(rows[0]["publicationAllowed"])

if __name__=="__main__":
    unittest.main()
