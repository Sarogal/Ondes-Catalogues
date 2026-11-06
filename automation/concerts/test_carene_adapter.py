"""La Carène SPIP official page parser: no external network, no publishing."""
import datetime as dt
import sys
import unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parent))
import carene_adapter as carene
import discover

SOURCE={"name":"La Carène","city":"Brest","department":"29",
        "id":"venue-source-010","url":carene.BASE,
        "adapter":"carene_spip_official_detail","maxDetailPagesPerRun":8,
        "priority":"P1"}
LINK="https://www.lacarene.fr/mary-bell-prisonnier-du-temps.html"

def listing(slug="mary-bell-prisonnier-du-temps.html",
            title="Mary Bell + Prisonnier du temps",day=28,month=11,year=26,
            kind="Concert",extra=""):
    return (
        f'<li class="item evenement"><a href="{slug}" class="rotation">'
        f'<figure><figcaption>{title}</figcaption></figure>'
        '<div class="infos bordure"><div class="dates-evenement">'
        f'<div class="date"><div class="jour">{day}</div>'
        f'<div class="mois">{month:02d}</div><div class="annee">{year}</div>'
        '</div></div></div>'
        f'<div class="genre bordure">{kind}</div>{extra}</a></li>'
    )

def detail(title="Mary Bell + Prisonnier du temps",
           date="samedi 28 novembre",
           room="Club Carène",genres="Punk Rock / Grunge",
           status="",time="Début : <span>21:00</span>",
           venue_title="Venir à La Carène"):
    return (
        '<main><article><h1>'+title+'</h1>'
        '<div class="details-evenement"><ul class="liste-items dates">'
        '<li class="item">'+date+'</li></ul>'
        '<div class="horaires"><div>'+time+'</div>'
        '<div>Fin : <span>23:30</span></div></div>'
        '<div class="infos-evenement"><p>'+room+'</p>'
        '<p>Ouverture des portes à 20h30</p></div></div>'
        '<div class="genre-evenement">'+genres+'</div>'
        '<h2>Mary Bell (Paris)</h2><p>Mary Bell est un cri riot grrrl, '
        'entre énergie punk hardcore grunge.</p><p>'+status+'</p>'
        '<h2>'+venue_title+'</h2><p>Concert suivant Metal, Punk</p>'
        '</article></main>'
    )

def read(card_html=None,event_html=None):
    c=carene.agenda_cards(card_html or listing())[0]
    return carene.candidate(event_html or detail(),LINK,c,SOURCE,"2026-11-02")

class CareneOfficial(unittest.TestCase):
    def test_mary_bell_official_read_only_detail(self):
        c=read()
        self.assertEqual(c["date"],"2026-11-28")
        self.assertEqual(c["name"],"Mary Bell + Prisonnier du temps")
        self.assertEqual(c["localTime"],"21:00")
        self.assertEqual(c["venue"],"La Carène")
        self.assertEqual(c["classification"],["Punk"])
        self.assertFalse(c["publicationAllowed"])
        self.assertTrue(c["reviewRequired"])

    def test_venue_must_be_specific_event_room(self):
        with self.assertRaisesRegex(ValueError,"Physical"):
            read(event_html=detail(room="Salle Watremez"))
        with self.assertRaisesRegex(ValueError,"Cancelled|Physical"):
            read(event_html=detail(room="Brest port (hors les murs)"))

    def test_cards_need_full_date_and_concert_type(self):
        self.assertEqual(carene.agenda_cards(listing(day=31,month=11)),[])
        self.assertEqual(carene.agenda_cards(listing(kind="Atelier")),[])
        self.assertEqual(carene.agenda_cards(listing()+listing()),carene.agenda_cards(listing()))
        self.assertEqual(carene.agenda_cards(listing(extra=(
            '<div class="dates-evenement"><div class="date">'
            '<div class="jour">29</div><div class="mois">11</div>'
            '<div class="annee">26</div></div></div>'))),[])

    def test_festival_and_cancelled_cannot_qualify_as_concert(self):
        for title in ("Metalearth Festival J1 : Seth + Hexecutor",
                      "RECIDIV' FEST", "Festival Invisible #21"):
            with self.subTest(title=title),self.assertRaisesRegex(ValueError,"Festival"):
                c=carene.agenda_cards(listing(title=title))[0]
                carene.candidate(detail(title=title),LINK,c,SOURCE,"2026-11-02")
        with self.assertRaisesRegex(ValueError,"Festival"):
            carene.candidate(detail(),LINK,
                             carene.agenda_cards(listing(extra=(
                             '<span>Annulé</span>')))[0],SOURCE,"2026-11-02")

    def test_day_month_mismatch_and_different_headline(self):
        with self.assertRaisesRegex(ValueError,"date"):
            read(event_html=detail(date="samedi 29 novembre"))
        with self.assertRaisesRegex(ValueError,"headline"):
            read(event_html=detail(title="Other band"))

    def test_subgenre_not_from_generic_future_recommendations(self):
        with self.assertRaisesRegex(ValueError,"subgenre"):
            read(event_html=detail(genres="Rock alternatif",status=(
                "de la musique douce et festive")).replace(
                "entre énergie punk hardcore grunge","entre des mélodies indie rock"))

    def test_door_time_not_misread_as_showtime(self):
        c=read(event_html=detail(time="Portes : 20:30"))
        self.assertIsNone(c["localTime"])

    def test_source_url_must_be_exact_first_party(self):
        for invalid in ("https://evil.example/mary-bell-prisonnier-du-temps.html",
                        "http://www.lacarene.fr/mary-bell-prisonnier-du-temps.html",
                        LINK+"?secret=x","https://www.lacarene.fr/-agenda-.html"):
            self.assertIsNone(carene.official_link(invalid))
        self.assertIsNone(carene.official_link("https://www.lacarene.fr/some-other-page/"))

    def test_integration_discovery_marks_known_duplicate_nonpublishing(self):
        base=carene.BASE
        page2=base+"?debut_agenda=25"
        seen=[]
        def fake_download(url,**kwargs):
            seen.append(url)
            if url==base:return listing(),url
            if url==page2:return "",url
            if url==LINK:return detail(),url
            raise AssertionError(url)
        with mock.patch.object(discover,"robots_allow",return_value=True), \
             mock.patch.object(discover,"download",side_effect=fake_download):
            reports=[]
            data=discover.scan_venues({"venues":[SOURCE]},
                       {("officialUrl",LINK)},dt.date(2026,11,2),reports)
        self.assertEqual(len(data),1)
        self.assertTrue(data[0]["possibleExistingConcert"])
        self.assertFalse(data[0]["publicationAllowed"])
        self.assertEqual(reports[0]["adapterDiagnostic"]["datedGenreLeads"],1)
        self.assertIn(page2,seen)

if __name__=="__main__":unittest.main()
