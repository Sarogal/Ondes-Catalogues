"""Offline Echo System source regression tests; no network and no publication."""
import unittest
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import echo_system_adapter as e

VENUE={"name":"Echo System","city":"Scey-sur-Saône-et-Saint-Albin",
       "department":"70","url":"https://echosystem70.fr/agenda/"}
LIST="""<html><div class="evt post-4854 evenement">
<a href="https://echosystem70.fr/evenement/horskh-lila-ehja/">
<div id="jchiff">14</div><div id="mchiff">11</div><div id="horagenda">20H30</div>
<div class="stylevtagenda">Metal</div><h2 class="titevt">Horskh + Lila Ehjä</h2>
</a></div>
<div class="evt post-5037 evenement">
<a href="/evenement/gaulhammer-night-2/">
<div id="jchiff">05</div><div id="mchiff">12</div>
<div id="horagenda">20H30</div><h2 class="titevt">
Gaulhammer Night #2 : <span>Goatvermin + Lunar Tombfields + Hexecutor + Belenos</span>
</h2></a></div>
<a href="/evenement/unrelated-footer/">Footer link outside event card</a>
<div class="evt"><a href="https://evil.example/evenement/unrelated/">Fake</a></div>
</html>"""
HORSKH="""<div id="rightheadevt">
<h1 class="titevt"><span>Horskh + </span><span>Lila Ehjä</span></h1>
<h2 class="sstitevt">Metal</h2>
<div id="ladateevt"><span>sam. 14 novembre 2026</span><span>&gt; 20H30</span></div>
<div id="lelieu"><a href="https://maps.google.com/">ECHO SYSTEM</a></div>
</div>"""
GAULHAMMER="""<div id="rightheadevt">
<h1 class="titevt"><span>Gaulhammer Night #2 : </span>
<span>Goatvermin + Lunar Tombfields + Hexecutor + Belenos</span></h1>
<h1 class="sstitevt">Soirée Black Metal</h1>
<div id="ladateevt"><span>sam. 05 décembre 2026</span><span>&gt; 20H30</span></div>
<div id="lelieu"><a href="https://maps.google.com/">ECHO SYSTEM</a></div>
</div>"""


class EchoTests(unittest.TestCase):
    def test_exact_official_links_only_inside_event_cards(self):
        self.assertEqual(e.official_links(LIST,VENUE["url"]),[
            "https://echosystem70.fr/evenement/horskh-lila-ehja/",
            "https://echosystem70.fr/evenement/gaulhammer-night-2/"
        ])

    def test_official_year_venue_and_genre_create_nonpublishing_lead(self):
        lead=e.detail_candidate(HORSKH,
                "https://echosystem70.fr/evenement/horskh-lila-ehja/",
                VENUE,"2026-11-02")
        self.assertEqual(lead["date"],"2026-11-14")
        self.assertEqual(lead["localTime"],"20:30")
        self.assertEqual(lead["leadArtist"],"Horskh")
        self.assertEqual(lead["venueCatalogueId"],"echo-system-scey")
        self.assertFalse(lead["publicationAllowed"])
        self.assertTrue(lead["reviewRequired"])

    def test_metal_night_not_mistaken_for_festival(self):
        lead=e.detail_candidate(GAULHAMMER,
                "https://echosystem70.fr/evenement/gaulhammer-night-2/",
                VENUE,"2026-11-02")
        self.assertEqual(lead["date"],"2026-12-05")
        self.assertEqual(lead["leadArtist"],"Goatvermin")
        self.assertEqual(lead["classification"],["Soirée Black Metal"])

    def test_missing_year_is_never_guessed_from_agenda_month(self):
        with self.assertRaisesRegex(ValueError,"Année"):
            e.detail_candidate(HORSKH.replace("2026",""),
                "https://echosystem70.fr/evenement/horskh-lila-ehja/",
                VENUE,"2026-11-02")

    def test_concert_in_different_location_is_held(self):
        with self.assertRaisesRegex(ValueError,"autre salle"):
            e.detail_candidate(HORSKH.replace("ECHO SYSTEM","Auditorium de Lure"),
                "https://echosystem70.fr/evenement/horskh-lila-ehja/",
                VENUE,"2026-11-02")

    def test_rock_pop_or_workshop_without_metal_punk_genre_is_held(self):
        for text in ("Folk pop","Percussions industrielles","Masterclass chant metal"):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    e.detail_candidate(HORSKH.replace("Metal</h2>",text+"</h2>"),
                        "https://echosystem70.fr/evenement/horskh-lila-ehja/",
                        VENUE,"2026-11-02")

    def test_past_or_changed_concert_is_held(self):
        with self.assertRaisesRegex(ValueError,"passé"):
            e.detail_candidate(HORSKH,
                "https://echosystem70.fr/evenement/horskh-lila-ehja/",
                VENUE,"2027-11-14")
        with self.assertRaises(ValueError):
            e.detail_candidate(HORSKH.replace("14 novembre 2026","31 novembre 2026"),
                "https://echosystem70.fr/evenement/horskh-lila-ehja/",
                VENUE,"2026-11-02")

    def test_wrong_host_query_and_non_event_url_rejected(self):
        for url in (
            "https://attacker.example/evenement/horskh-lila-ehja/",
            "https://echosystem70.fr/agenda/",
            "https://echosystem70.fr/evenement/horskh-lila-ehja/?utm_source=x",
            "http://echosystem70.fr/evenement/horskh-lila-ehja/"
        ):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    e.detail_candidate(HORSKH,url,VENUE,"2026-11-02")

    def test_duplicate_venue_fields_and_dates_held(self):
        with self.assertRaises(ValueError):
            e.detail_candidate(HORSKH.replace("</div>","</div><div id='ladateevt'>15 novembre 2026</div>",1),
                "https://echosystem70.fr/evenement/horskh-lila-ehja/",
                VENUE,"2026-11-02")
        wrong=dict(VENUE,city="Nantes")
        with self.assertRaises(ValueError):
            e.detail_candidate(HORSKH,"https://echosystem70.fr/evenement/horskh-lila-ehja/",
                               wrong,"2026-11-02")

    def test_other_venue_an_ambiguous_boutique_source_is_held(self):
        for title in ("ONE WAY OUT FEST IV","Masterclass Eva-B", "DJ set metal"):
            with self.subTest(title=title):
                with self.assertRaises(ValueError):
                    e.detail_candidate(HORSKH.replace("Horskh + ","").replace("Lila Ehjä",title),
                        "https://echosystem70.fr/evenement/horskh-lila-ehja/",
                        VENUE,"2026-11-02")


if __name__=="__main__":
    unittest.main()
