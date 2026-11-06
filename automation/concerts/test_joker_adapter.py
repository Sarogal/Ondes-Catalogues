"""Tests hors réseau du Joker : dates fiables, liens et détails."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import joker_adapter as j

VENUE={"name":"Le Joker's Pub","city":"Angers","department":"49"}
HOME="https://www.jokerspubangers.com/"
PAGE='''<section><ul>
<li><p>VIOLENT SADIE MODE</p><p>VEN 20 NOV 202620H30</p>
<a href="/jokers-concert-programmation-violent-sadie-mode-1705.html">En savoir plus</a></li>
<li><p>MOONDINE DJ SET</p><p>VEN 20 NOV 202623H00</p>
<a href="/jokers-concert-programmation-moondine-1728.html">En savoir plus</a></li>
<li><p>AURORE + BRUTALISTE</p><p>VEN 11 DEC 202620H00</p>
<a href="/jokers-concert-programmation-aurore-brutaliste-1899.html">En savoir plus</a></li>
<li><span title="Annulé"></span><p>COWBOYY</p><p>VEN 18 DEC 202620H30</p>
<a href="/jokers-concert-programmation-cowboyy-1701.html">En savoir plus</a></li>
<li><p>NO DATE</p><p>VEN 18 DEC 18H00</p>
<a href="/jokers-concert-programmation-no-date-1701.html">En savoir plus</a></li>
<li><p>PUNK BAND</p><p>MAR 99 NOV 202620H30</p>
<a href="/jokers-concert-programmation-punk-1701.html">En savoir plus</a></li>
</ul></section>'''

class JokerTests(unittest.TestCase):
    def test_homepage_dates_et_dj_exclus(self):
        rows=j.listing_candidates(PAGE,HOME,VENUE,"2026-11-01")
        self.assertEqual([x["name"] for x in rows],
                         ["VIOLENT SADIE MODE","AURORE + BRUTALISTE","COWBOYY"])
        self.assertEqual(rows[0]["date"],"2026-11-20")
        self.assertEqual(rows[1]["localTime"],"20:00")
        self.assertTrue(rows[2]["cancellationNotice"])
        self.assertTrue(all(x["publicationAllowed"] is False for x in rows))

    def test_detail_genre_sur_titre_identique(self):
        row=j.listing_candidates(PAGE,HOME,VENUE,"2026-11-01")[0]
        page="<html><h1>Violent Sadie Mode</h1><h2>Punk HxC - Festival Les Femmes S'en Mêlent</h2></html>"
        result=j.with_details(row,page)
        self.assertEqual(result["detailStatus"],"title_matched")
        self.assertTrue(result["festivalContext"])
        self.assertEqual(result["classification"],["Punk HxC - Festival Les Femmes S'en Mêlent"])
        self.assertFalse(result["publicationAllowed"])

    def test_wrong_details_do_not_confirm(self):
        row=j.listing_candidates(PAGE,HOME,VENUE,"2026-11-01")[0]
        result=j.with_details(row,"<h1>Blind Test</h1><h2>Metal</h2>")
        self.assertEqual(result["detailStatus"],"mismatch_or_missing_title")
        self.assertTrue(result["genreToConfirm"])

    def test_no_year_is_rejected(self):
        data='<li><p>Punk band</p><p>VEN 11 DEC 20h00</p><a href="/jokers-concert-programmation-band-123.html">Event</a></li>'
        self.assertEqual(j.listing_candidates(data,HOME,VENUE,"2026-11-01"),[])

    def test_no_foreign_event_url(self):
        data='<li><p>Band</p><p>VEN 11 DEC 202620H00</p><a href="https://evil.com/jokers-concert-programmation-test-2.html">Event</a></li>'
        self.assertEqual(j.listing_candidates(data,HOME,VENUE,"2026-11-01"),[])

    def test_only_future_events(self):
        self.assertEqual(j.listing_candidates(PAGE,HOME,VENUE,"2028-01-01"),[])


    def test_real_slider_markup_and_date_time_span(self):
        html = """<html><ul>
        <li class="slide13"><div class="slide__inner">
          <div class="slide__content slide__content_concert" id="concert">
            <div class="slide__content__inner">
              <p class="h1">VIOLENT SADIE MODE</p>
              <div class="slide__date">VEN 20 NOV 2026<span>20H30</span></div>
              <a href="https://www.jokerspubangers.com/jokers-concert-programmation-violent-sadie-mode-1705.html">En savoir plus</a>
            </div></div></div></li>
        <li><div class="slide__content" id="soireedj">
              <p class="h1">MOONDINE DJ SET</p>
              <div class="slide__date">VEN 20 NOV 2026<span>23H00</span></div>
              <a href="/jokers-concert-programmation-moondine-1728.html">En savoir plus</a>
        </div></li>
        <li><div class="slide__content" id="concert">
             <p class="h1">AURORE + BRUTALISTE</p>
             <div class="slide__date">VEN 11 DEC 2026<span>20H00</span></div>
             <a href="/jokers-concert-programmation-aurore-+-brutaliste-1668.html">En savoir plus</a>
        </div></li>
        <li><div class="slide__content" id="concert">
             <p class="h1">BODY HORROR</p>
             <div class="slide__date">DIM 31 JANV 2026<span>18h00</span></div>
             <a href="/jokers-concert-programmation-body-horror-1714.html">En savoir plus</a>
        </div></li>
        </ul></html>"""
        rows=j.listing_candidates(html,HOME,VENUE,"2026-11-02")
        self.assertEqual([r["name"] for r in rows],
                         ["VIOLENT SADIE MODE","AURORE + BRUTALISTE"])
        self.assertEqual([r["date"] for r in rows], ["2026-11-20","2026-12-11"])
        self.assertEqual([r["localTime"] for r in rows], ["20:30","20:00"])
        self.assertTrue(all(x["reviewRequired"] and not x["publicationAllowed"] for x in rows))
        diag=j.diagnose_layout(html)
        self.assertEqual(diag["listItemsWithDates"], 4)
        self.assertGreaterEqual(diag["officialDetailLinks"], 4)

    def test_multiple_artist_detail_titles_must_all_match(self):
        row={"name":"AURORE + BRUTALISTE","genreToConfirm":True,"reviewRequired":True,
             "publicationAllowed":False}
        detail="""<h1>AURORE</h1><h2>Hardcore mélodique - Marseille</h2>
                  <h1>BRUTALISTE</h1><h2>Hardcore - Angers</h2>"""
        full=j.with_details(row,detail)
        self.assertEqual(full["detailStatus"],"title_matched")
        self.assertEqual(full["classification"],["Hardcore mélodique - Marseille","Hardcore - Angers"])
        self.assertFalse(full["genreToConfirm"])
        self.assertFalse(full["publicationAllowed"])
        partial=j.with_details(row,detail.replace("<h1>BRUTALISTE</h1>","<h1>HOMONYME</h1>"))
        self.assertEqual(partial["detailStatus"],"mismatch_or_missing_title")
        self.assertTrue(partial["genreToConfirm"])
        other=j.with_details(row,detail.replace("Hardcore - Angers", "Electro-pop - Angers"))
        self.assertTrue(other["genreToConfirm"])
        self.assertNotIn("classification",other)



    def test_wrong_weekday_or_impossible_hour_never_creates_candidate(self):
        wrong = [
            "SAM 20 NOV 2026<span>20H30</span>",
            "VEN 20 NOV 2026<span>25H30</span>",
        ]
        for date_markup in wrong:
            page = f"""<ul><li><p>VIOLENT SADIE MODE</p>
                <div class="slide__date">{date_markup}</div>
                <a href="/jokers-concert-programmation-violent-sadie-mode-1705.html">Détail</a>
                </li></ul>"""
            with self.subTest(date_markup=date_markup):
                self.assertEqual(j.listing_candidates(page,HOME,VENUE,"2026-11-01"), [])


if __name__=="__main__":
    unittest.main()
