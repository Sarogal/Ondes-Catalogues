"""Tests sans réseau : agenda Ferrailleur à événements multiples."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import ferrailleur_adapter as f

VENUE={"name":"Le Ferrailleur","city":"Nantes","department":"44"}
URL="https://www.leferrailleur.fr/agenda"
TEXT="""<html><body><p>
Agenda
Choisir un style
Metal Punk Jazz
novembre
26
jeudi 05 novembre - 20:30
jeudi 05 novembre -
jeudi 05 novembre
Storm Orchestra
Shimmeric
Rock, Metal, Modern Metal
Réservation
vendredi 06 novembre - 20:30
vendredi 06 novembre - 23:30
vendredi 06 novembre
Babe Haven
Latter
Solar Sound System w/ Nutskey
queer punk, riot grrrl, Rock, Noise, Psytrance
Réservation
lundi 09 novembre - 20:30
lundi 09 novembre -
lundi 09 novembre
Poison Ruïn
Precipice
Punk, Punk Hardcore
Réservation
mardi 17 novembre - 19:00
mardi 17 novembre -
mardi 17 novembre
Masterclass de Rise Of The Northstar
Metal
Réservation
vendredi 27 novembre - 20:30
vendredi 27 novembre -
vendredi 27 novembre
Sunami
Desolated
Missing Link
Extinguish
Moral Law
Bind.
Chute Libre
Hardcore, Hardcore, Metalcore
Réservation
decembre
26
samedi 19 decembre - 19:00
samedi 19 decembre -
samedi 19 decembre
Arkona
Seth
The Great Old Ones
Folk, Black Metal, Pagan
Réservation
</p></body></html>"""

class FerrailleurTests(unittest.TestCase):
    def test_novembre_decembre(self):
        rows=f.extract_ferrailleur(TEXT,URL,VENUE,"2026-11-01")
        self.assertEqual(len(rows),3) # Storm, Poison Ruin, Arkona; seven bands ambiguous skip
        self.assertEqual([x["date"] for x in rows],
                         ["2026-11-05","2026-11-09","2026-12-19"])
        self.assertTrue(all(x["publicationAllowed"] is False for x in rows))

    def test_champs_html_separes_artistes_et_annee(self):
        page=(
            '<div><span>novembre</span><span>26</span></div>'
            '<article><p>jeudi 05 novembre</p><span> - 20:30</span>'
            '<p>jeudi 05 novembre -</p><p>jeudi 05 novembre</p>'
            '<span>Storm Orchestra</span><span>Shimmeric</span>'
            '<p>Rock, Metal, Modern Metal</p><p>Réservation</p></article>'
        )
        rows=f.extract_ferrailleur(page,URL,VENUE,"2026-11-01")
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["date"],"2026-11-05")
        self.assertEqual(rows[0]["name"],"Storm Orchestra + Shimmeric")
        self.assertFalse(rows[0]["name"].startswith("-"))

    def test_no_header_no_year_invention(self):
        body="<p>vendredi 27 novembre - 20:30\nBand\nHardcore\nRéservation</p>"
        self.assertEqual(f.extract_ferrailleur(body,URL,VENUE,"2026-11-01"),[])

    def test_reject_masterclass_even_metal_tag(self):
        self.assertNotIn("Masterclass",str(f.extract_ferrailleur(TEXT,URL,VENUE,"2026-11-01")))

    def test_no_genre_techno_only(self):
        self.assertFalse(f.metal_genre_line("hard techno, Techno"))
        self.assertFalse(f.metal_genre_line("doom festif, Electro"))
        self.assertTrue(f.metal_genre_line("Black Metal, Pagan, Heavy Metal"))

    def test_exact_official_event_link_is_selected(self):
        html=TEXT.replace(
            "Poison Ruïn\nPrecipice\nPunk, Punk Hardcore",
            '<a class="card-title" href="/evenement/poison-ruin-precipice/5359">'
            'Poison Ruïn + Precipice</a>\nPunk, Punk Hardcore')
        links=f.official_event_urls(html,URL)
        self.assertEqual(
            links[f.simplify("Poison Ruïn + Precipice")],
            "https://www.leferrailleur.fr/evenement/poison-ruin-precipice/5359")
        rows=f.extract_ferrailleur(html,URL,VENUE,"2026-11-01")
        matching=[x for x in rows if "Poison" in x["name"]]
        self.assertEqual(len(matching),1)
        self.assertTrue(matching[0]["officialDetailFound"])
        self.assertEqual(matching[0]["sourceUrl"],links[f.simplify("Poison Ruïn + Precipice")])

    def test_full_card_with_date_lineup_and_genre_matches(self):
        link = "https://www.leferrailleur.fr/evenement/poison-ruin-precipice/5359"
        cards = {
            f.simplify("lundi 09 novembre - 20:30 lundi 09 novembre Poison Ruïn Precipice Punk, Punk Hardcore"):link,
            f.simplify("mardi 10 novembre - 20:30 mardi 10 novembre Poison Ruïn Precipice Punk"): "https://www.leferrailleur.fr/evenement/other/888"
        }
        self.assertEqual(
            f.choose_official_detail("Poison Ruïn + Precipice","2026-11-09","20:30",cards),
            link)
        self.assertIsNone(
            f.choose_official_detail("Poison Ruïn + Precipice","2026-11-09","19:00",cards))
        self.assertIsNone(
            f.choose_official_detail("Poison Ruïn + Precipice","2026-11-11","20:30",cards))

    def test_multiple_same_date_showings_never_guess_link(self):
        name=f.simplify("Poison Ruïn Precipice")
        cards={
            f.simplify("lundi 09 novembre 20:30 Poison Ruïn Precipice Punk"):
                "https://www.leferrailleur.fr/evenement/poison/5359",
            f.simplify("lundi 09 novembre 20:30 Poison Ruïn Precipice Punk Hardcore"):
                "https://www.leferrailleur.fr/evenement/poison/5360",
        }
        self.assertIsNone(
            f.choose_official_detail("Poison Ruïn + Precipice","2026-11-09","20:30",cards))

    def test_wrong_host_and_guessed_event_links_are_ignored(self):
        links=f.official_event_urls(
            '<a class="card-title" href="https://unsafe.example/evenement/poison/5359">'
            'Poison Ruïn + Precipice</a>'
            '<a class="card-title" href="/evenement/guess-no-id">'
            'Poison Ruïn + Precipice</a>',URL)
        self.assertEqual(links,{})

    def test_ambiguous_title_links_are_not_used(self):
        links=f.official_event_urls(
            '<a class="card-title" href="/evenement/poison/5359">'
            'Poison Ruïn + Precipice</a>'
            '<a class="card-title" href="/evenement/poison/7777">'
            'Poison Ruïn + Precipice</a>',URL)
        self.assertNotIn(f.simplify("Poison Ruïn + Precipice"),links)

    def test_after_window(self):
        self.assertEqual(f.extract_ferrailleur(TEXT,URL,VENUE,"2027-01-01"),[])

if __name__=="__main__":unittest.main()
