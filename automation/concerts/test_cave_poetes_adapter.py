"""No-network tests for the official Cave aux Poètes adapter and safety rules."""
import datetime as dt
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0,str(Path(__file__).resolve().parent))
import cave_poetes_adapter as c
import discover as d

SOURCE={"id":"venue-source-017","name":"La Cave aux Poètes",
        "city":"Roubaix","department":"59","priority":"P1",
        "url":"https://caveauxpoetes.com/agenda/",
        "adapter":"cave_poetes_first_party_detail",
        "maxDetailPagesPerRun":3}
DETAIL="https://caveauxpoetes.com/evenement/joobieseaz/"


def card(url=DETAIL,date="mer. 16 décembre 2026",venue="La Cave aux Poètes",
         artists=("Joobieseaz","Belljars"),status=""):
    names="".join(f'<span class="titartprog">{n}</span>' for n in artists)
    return (
        f'<a class="unevt" href="{url}"><img src="image.jpg">'
        f'<div id="contevt"><div id="legenreevt"><span>Indie</span>'
        f'<span>Rock</span></div><div class="titevtprog">{names}</div>'
        f'<div id="ladateevtprog">{date}</div>'
        f'<div class="lelieuevtprog">{venue}</div>'
        f'<div class="infosbill">{status}</div></div>'
        '<div class="typevt">Rock / Métal / Punk</div></a>'
    )


def detail(date="mer. 16 décembre 2026",venue="La Cave aux Poètes",
           bio="Joobieseaz est un groupe de post-punk et de shoegaze.",
           kind="Concert couche-tôt",artists=("Joobieseaz","Belljars"),
           clock="OUVERTURE DES PORTES : 18H30 / CONCERTS : 19h"):
    names="".join(f'<span class="artistehome">{n}</span>' for n in artists)
    return (
        '<article class="post evenement type-evenement">'
        '<header class="entry-header"><div id="leftevt">'
        f'<div id="nomsoiree">{kind}</div>'
        f'<div id="nomprog">{names}</div>'
        '<div class="type"><span class="typeevt">Rock / Métal / Punk</span></div>'
        f'<div id="date">{date}</div>'
        f'<div id="horaire">{clock}</div>'
        f'<div class="lelieu"><a href="https://www.google.com/maps">{venue}</a></div>'
        '</div></header><div class="entry-content"><div id="lesartistes">'
        '<div class="unartiste"><div id="artdesc"><p>'
        f'{bio}</p></div></div></div></div>'
        '</article><div id="relatedpost"><a class="unevt" href="'
        'https://caveauxpoetes.com/evenement/metal-in-other-venue/">'
        '<span class="artistehome">Other Metal</span></a></div>'
    )


class CaveOfficialTests(unittest.TestCase):
    def test_valid_first_party_postpunk_event_never_published(self):
        row=c.candidate(detail(),DETAIL,c.cards(card())[0],SOURCE,"2026-11-02")
        self.assertEqual(row["date"],"2026-12-16")
        self.assertEqual(row["localTime"],"19:00")
        self.assertEqual(row["name"],"Joobieseaz + Belljars")
        self.assertEqual(row["classification"],["Post Punk"])
        self.assertEqual(row["venueCatalogueId"],"la-cave-aux-poetes-roubaix")
        self.assertFalse(row["publicationAllowed"])
        self.assertTrue(row["reviewRequired"])

    def test_generic_rock_metal_punk_heading_not_enough(self):
        with self.assertRaisesRegex(ValueError,"Subgenre"):
            c.candidate(detail(bio="Musique indé, rock alternatif."),
                        DETAIL,c.cards(card())[0],SOURCE,"2026-11-02")

    def test_other_room_never_assigned_cave_coordinates(self):
        with self.assertRaisesRegex(ValueError,"Outside"):
            c.candidate(detail(venue="Salle Watremez"),DETAIL,
                        c.cards(card(venue="Salle Watremez"))[0],SOURCE,"2026-11-02")

    def test_festival_and_cancellation_blocked(self):
        for status,kind in [("ANNULÉ !","Concert"),("","Festival Haute-fréquence")]:
            with self.subTest(status=status,kind=kind),self.assertRaisesRegex(ValueError,"Festival"):
                c.candidate(detail(kind=kind),DETAIL,c.cards(card(status=status))[0],
                            SOURCE,"2026-11-02")

    def test_date_and_artist_mismatch_fail_closed(self):
        for page in [detail(date="jeu. 17 décembre 2026"),
                     detail(artists=("Joobieseaz","Different Artist"))]:
            with self.assertRaises(ValueError):
                c.candidate(page,DETAIL,c.cards(card())[0],SOURCE,"2026-11-02")
        with self.assertRaisesRegex(ValueError,"date"):
            c.candidate(detail(),DETAIL,c.cards(card())[0],SOURCE,"2027-01-01")

    def test_time_never_guessed_from_opening_doors(self):
        row=c.candidate(detail(clock="OUVERTURE DES PORTES : 18H30"),
                        DETAIL,c.cards(card())[0],SOURCE,"2026-11-02")
        self.assertIsNone(row["localTime"])

    def test_url_restrictions_and_no_footer_with_missing_date(self):
        for value in ("https://bad.example/evenement/joobieseaz/",
                      "http://caveauxpoetes.com/evenement/joobieseaz/",
                      DETAIL+"?auth=secret","https://caveauxpoetes.com/agenda/"):
            self.assertIsNone(c.url_ok(value))
        self.assertEqual(len(c.cards(card()+card())),1)
        self.assertEqual(c.cards(card(date="date sans année")),[])

    def test_discovery_integration_dedupes_known_published_url(self):
        with mock.patch.object(d,"robots_allow",return_value=True), \
             mock.patch.object(d,"download",side_effect=lambda url,**kw:
                 (card(),url) if url==SOURCE["url"] else (detail(),url)):
            report=[]
            known={("officialUrl",DETAIL)}
            found=d.scan_venues({"venues":[SOURCE]},known,
                               dt.date(2026,11,2),report)
        matches=[x for x in found if x.get("source")=="agenda_officiel_cave_poetes_detail"]
        self.assertEqual(len(matches),1)
        self.assertTrue(matches[0]["possibleExistingConcert"])
        self.assertFalse(matches[0]["publicationAllowed"])
        self.assertEqual(report[0]["adapterDiagnostic"]["datedGenreLeads"],1)


if __name__=="__main__":unittest.main()
