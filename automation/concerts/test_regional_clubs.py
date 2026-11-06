"""Offline conservative review-only regional concert listing tests."""
import datetime as dt
import sys
import unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parent))
import regional_clubs as rc
import discover as d

ROCK={"name":"Rock n' Eat","city":"Lyon","department":"69",
      "priority":"P1","url":"https://www.rockneat.com/Programmation",
      "adapter":"rockneat_official_listing_review"}
MAISON={"name":"La Maison Bleue","city":"Strasbourg","department":"67",
        "priority":"P1","url":"https://www.lamaisonbleue-stbg.com/agenda/",
        "adapter":"maisonbleue_official_listing_review"}

ROCK_HTML="""<html><script>PROGRAMMATION NOVEMBRE 2026</script><main>
<p>LUNDI 02 NOVEMBRE</p><h1>CARSON + GOATFATHER</h1>
<h1>PROGRAMMATION</h1><h1>NOVEMBRE</h1><h1>2026</h1>
<p>2</p><p>19H00</p><h1>CARSON + GOATFATHER</h1><p>Prix Libre</p>
<p>4</p><p>18H00</p><h1>LAGRIMAS + THE PRESTIGE</h1><p>Réserver</p>
<p>6</p><p>19H00</p><h1>CRYSTALLION+ BÏTZEBÜLLET+ VAIN GLORY</h1>
<p>11</p><p>19H00</p><h1>ATELIER + FORMATION</h1>
<p>12</p><p>18H00</p><h1></h1>
</main></html>"""

MAISON_HTML="""<html><header>Métal 2017</header><main>
<p>Agenda
Wake The Dead + Toxic Shock + Sick Lame &amp; Lazy
11 Nov 2026
Métal
Réserver
Storm Orchestra
12 Nov 2026
Rock
Réserver
Local Heroes
13 Nov 2026
Métal
Réserver
Atelier : initiation à la batterie
15 Nov 2026
Métal
Réserver
Årabrot
04 Déc 2026
Rock
Réserver
Autre événement
11 Nov
Métal
Réserver
</p></main></html>"""


class RegionalListingTests(unittest.TestCase):
    def test_rock_only_calendar_full_month_and_year_with_named_multiple_artists(self):
        rows=rc.rockneat(ROCK_HTML,ROCK["url"],ROCK,"2026-11-02")
        self.assertEqual([r["date"] for r in rows],
                         ["2026-11-02","2026-11-04","2026-11-06"])
        self.assertTrue(all(r["genreToConfirm"] for r in rows))
        self.assertTrue(all(r["classification"]==[] for r in rows))
        self.assertTrue(all(r["localTime"] is None for r in rows))
        self.assertTrue(all(not r["publicationAllowed"] and r["reviewRequired"] for r in rows))
        self.assertEqual(len({r["candidateId"] for r in rows}),3)
        self.assertNotIn("ATELIER",str(rows))

    def test_rock_no_year_invalid_year_or_missing_calendar_blocks(self):
        for page in (ROCK_HTML.replace("<h1>2026</h1>",""),
                     ROCK_HTML.replace("<h1>2026</h1>","<h1>last updated</h1>"),
                     ROCK_HTML.replace("<h1>2026</h1>","<h1>2026</h1><h1>PROGRAMMATION</h1><h1>NOVEMBRE</h1><h1>2026</h1>"),
                     ROCK_HTML.replace("<h1>NOVEMBRE</h1>","<h1>UNKNOWN</h1>")):
            with self.subTest(page=page[-100:]):
                self.assertEqual(rc.rockneat(page,ROCK["url"],ROCK,"2026-11-02"),[])
        self.assertEqual(rc.rockneat(ROCK_HTML,ROCK["url"],ROCK,"2026-12-01"),[])

    def test_maison_explicit_year_genre_and_safeguards(self):
        rows=rc.maison_bleue(MAISON_HTML,MAISON["url"],MAISON,"2026-11-02")
        self.assertEqual([r["name"] for r in rows],
                         ["Wake The Dead + Toxic Shock + Sick Lame & Lazy","Local Heroes"])
        self.assertEqual([r["date"] for r in rows],["2026-11-11","2026-11-13"])
        self.assertTrue(all(r["classification"]==["Métal"] for r in rows))
        self.assertTrue(all(not r["genreToConfirm"] for r in rows))
        self.assertTrue(all(r["localTime"] is None and not r["publicationAllowed"]
                            for r in rows))
        self.assertEqual(rc.maison_bleue(MAISON_HTML,MAISON["url"],MAISON,"2026-12-25"),[])

    def test_untrusted_domains_and_identity_rejected(self):
        for k,url,source,fn in (
            ("rockneat","https://evil.example/Programmation",ROCK,rc.rockneat),
            ("maisonbleue","https://www.lamaisonbleue-stbg.com/agenda/?fake=1",MAISON,rc.maison_bleue)
        ):
            with self.subTest(k=k):
                with self.assertRaises(ValueError):
                    fn(ROCK_HTML if k=="rockneat" else MAISON_HTML,url,source,"2026-11-02")
        altered=dict(ROCK,name="Rock n Eat Fake")
        with self.assertRaises(ValueError):
            rc.rockneat(ROCK_HTML,ROCK["url"],altered,"2026-11-02")

    def test_discovery_integration_uses_only_official_and_does_not_publish(self):
        cases=[(ROCK,ROCK_HTML,3),(MAISON,MAISON_HTML,2)]
        for source,html,n in cases:
            with self.subTest(source=source["name"]):
                with mock.patch.object(d,"robots_allow",return_value=True), \
                     mock.patch.object(d,"download",side_effect=lambda url,*a,**kw:(html,url)):
                    checks=[]
                    found=d.scan_venues({"venues":[source]},set(),dt.date(2026,11,2),
                                        checks,max_p2=0)
                official=[r for r in found if r["source"].startswith("agenda_officiel_")]
                self.assertEqual(len(official),n)
                self.assertTrue(all(r["reviewRequired"] and not r["publicationAllowed"]
                                    for r in official))
                self.assertEqual(checks[0]["adapterDiagnostic"]["leads"],n)

if __name__=="__main__":
    unittest.main()
