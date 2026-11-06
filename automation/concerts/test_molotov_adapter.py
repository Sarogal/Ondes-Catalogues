"""Tests offline du Molotov, y compris salle associée Le Dodu."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import molotov_adapter as m

VENUE={"name":"Le Molotov","city":"Marseille","department":"13"}
SOURCE="https://lemolotov.com/agenda/"

def event(day,month,year,venue,title,genres,time="20:30",link=None):
    name=('<a href="'+link+'">'+title+'</a>') if link else title
    return (
        '<div class="event">'
        f'<h2>{day}</h2><h3>{month}</h3><h3>{year}</h3>'
        f'<h4><b>@ {venue}</b> / {time}</h4>'
        f'<h1>{name}</h1><h2>{genres}</h2>'
        '</div>'
    )

class MolotovTests(unittest.TestCase):
    def test_three_metal_two_other_and_duplicate(self):
        page=(
            event(1,"Nov",2026,"Le Molotov","EYEHATEGOD + Mezcal Wizard",
                  "Doom, Hardcore, Sludge",link="/events/eyehategod-mezcal-wizard/")
            +event(6,"Nov",2026,"Le Dodu","MASTER BOOT RECORD + FULCI",
                   "Death Metal, Metal")
            +event(7,"Nov",2026,"Le Molotov","IANWILL + Perseide + Maze’D",
                   "Alt Metal, Melodic Death Metal, Metalcore")
            +event(12,"Nov",2026,"Le Molotov","RATS DON’T SINK + Vodk47",
                   "Beatdown, Grunge, Punk HxC")
            +event(1,"Nov",2026,"Le Molotov","EYEHATEGOD + Mezcal Wizard",
                   "Doom, Hardcore, Sludge")
            +event(14,"Nov",2026,"Le Molotov","SOIRÉE DE SOUTIEN AUX LYCÉENS",
                   "Electro, Punk, Rap, Reggae")
            +event(20,"Nov",2026,"Le Molotov","DJ TECHNO",
                   "Hard Techno, Techno")
        )
        data=m.molotov_candidates(page,SOURCE,VENUE,"2026-11-01")
        self.assertEqual(len(data),3)
        self.assertEqual(data[0]["date"],"2026-11-01")
        self.assertEqual(data[0]["sourceUrl"],
                         "https://lemolotov.com/events/eyehategod-mezcal-wizard/")
        self.assertTrue(all(x["venue"]=="Le Molotov" for x in data))
        self.assertTrue(all(not x["publicationAllowed"] for x in data))

    def test_le_dodu_depuis_agenda_molotov(self):
        page = (
            event(5,"Nov",2026,"Le Molotov","Groupe M","Metal")
            + event(6,"Nov",2026,"Le Dodu","MASTER BOOT RECORD + FULCI",
                    "Death Metal, Metal")
        )
        dodu = {"name": "Le Dodu", "city": "Marseille", "department": "13"}
        records = m.molotov_candidates(page,SOURCE,dodu,"2026-11-01")
        self.assertEqual(len(records),1)
        self.assertEqual(records[0]["date"],"2026-11-06")
        self.assertEqual(records[0]["venue"],"Le Dodu")
        self.assertFalse(records[0]["publicationAllowed"])

    def test_realistic_article_structure(self):
        sample=(
            "<article><ul><li><p><h2>27</h2><h3>Nov</h3><h3>2026</h3></p>"
            "<p><h4><b> @ Le Molotov</b> / 20:00 </h4></p>"
            "<p><h1>ERADIKAL INSANE + Reign + Vulher</h1>"
            "<h2>Blackened Hardcore, Deathcore</h2></p></li></ul></article>"
        )
        rows=m.molotov_candidates(sample,SOURCE,VENUE,"2026-11-01")
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["localTime"],"20:00")
        self.assertEqual(rows[0]["date"],"2026-11-27")
        self.assertIn("Deathcore",rows[0]["classification"])

    def test_date_and_title_bounds(self):
        sample=(event(31,"Nov",2026,"Le Molotov","Invalid","Metal")
                +event(1,"Dec",2026,"Le Molotov","Valid + guest","Punk")
                +event(30,"Oct",2026,"Le Molotov","Old","Punk"))
        rows=m.molotov_candidates(sample,SOURCE,VENUE,"2026-11-01")
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["date"],"2026-12-01")

    def test_safe_url_same_venue_only(self):
        self.assertIsNone(m.safe_event_url("https://evil.example/a",SOURCE))
        self.assertIsNone(m.safe_event_url("https://lemolotov.com/agenda/",SOURCE))
        self.assertIsNotNone(m.safe_event_url("/events/test/",SOURCE))

    def test_not_hard_techno(self):
        self.assertFalse(m.genre_is_relevant("Hard Techno, Techno"))
        self.assertTrue(m.genre_is_relevant("Punk, Ska, Street Punk"))
        self.assertTrue(m.genre_is_relevant("Blackened Hardcore, Deathcore"))

if __name__=="__main__":
    unittest.main()
