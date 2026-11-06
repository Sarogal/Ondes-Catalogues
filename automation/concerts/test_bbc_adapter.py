"""Offline regression fixtures from BBC's observed 03/11/2026 WordPress pages."""
import json
from pathlib import Path
import unittest
import bbc_adapter as m

TODAY="2026-11-03"
SOURCE={"name":"Big Band Café","city":"Hérouville-Saint-Clair",
        "department":"14","url":m.AGENDA}
UGLY_URL="https://bigbandcafe.com/ugly-kid-joe/"
MADAM_URL="https://bigbandcafe.com/madam/"
AGENDA_HTML='''<html><body><nav><a href="/tickets/">menu</a></nav>
<section><h1>Programmation</h1>
<a href="/ugly-kid-joe/"><h2>UGLY KID JOE</h2>ven. 5 février 2027 - 20:00</a>
<a href="/madam/"><h2>MADAM</h2>ven. 2 avril 2027 - 20:00</a>
<a href="/concerts/">Retour</a>
<a href="https://evil.example/ugly-kid-joe/">evil</a>
<a href="/ugly-kid-joe/?utm=1">tracking</a>
</section><footer><a href="/privacy/">footer</a></footer></body></html>'''
UGLY='''<html><body><p>Big Band Café</p><section>
<h1>UGLY KID JOE</h1><h2>ven. 5 février 2027 - 20:00</h2>
<p>Abonné : 22 € / Réduit : 24 €</p>
<p>Groupe américain de hard rock satirique teinté de funk et de métal alternatif.</p>
<p>Ugly Kid Joe a sorti l'album America’s Least Wanted en 1992, puis en 2022.</p>
<p>Précédent ZED YUN PAVAROTTI</p>
</section></body></html>'''
MADAM='''<html><body><section><h1>MADAM</h1>
<h3>En accord avec Adone Productions</h3>
<h2>ven. 2 avril 2027 - 20:00</h2>
<p>Formé par Gabbie, Anais et Marine, MADAM est une formation rock actuelle.</p>
<p>Premier album en 2024, retour en 2027.</p>
</section></body></html>'''


class BBCAdapterTests(unittest.TestCase):
    def test_section_list_only_verified_internal_detail_links(self):
        self.assertEqual(m.official_links(AGENDA_HTML),[UGLY_URL,MADAM_URL])
        self.assertTrue(m.allowed_agenda(m.AGENDA))
        with self.assertRaises(ValueError):
            m.official_links(AGENDA_HTML,"https://bigbandcafe.com/")
        for url in ("/concerts/","https://evil.example/madam/",
                    MADAM_URL+"?utm=1",MADAM_URL+"#contact"):
            with self.subTest(url=url):
                self.assertIsNone(m.event_url(url))

    def test_both_detail_years_and_genres_but_no_start_times(self):
        for markup,url,date,title,genre,clock in (
            (UGLY,UGLY_URL,"2027-02-05","UGLY KID JOE","Hard Rock","20:00"),
            (MADAM,MADAM_URL,"2027-04-02","MADAM","Rock","20:00")
        ):
            with self.subTest(title=title):
                c=m.candidate(markup,url,SOURCE,TODAY)
                self.assertEqual(c["date"],date)
                self.assertEqual(c["name"],title)
                self.assertEqual(c["classification"],[genre])
                self.assertEqual(c["announcedClock"],clock)
                self.assertIsNone(c["localTime"])
                self.assertEqual(c["timeMeaning"],
                    "displayed_clock_unqualified_not_musical_start")
                self.assertFalse(c["publicationAllowed"])
                self.assertTrue(c["reviewRequired"])

    def test_no_year_inferred_from_album_biography(self):
        page=UGLY.replace("5 février 2027 - 20:00","5 février - 20:00")
        with self.assertRaises(ValueError):
            m.candidate(page,UGLY_URL,SOURCE,TODAY)

    def test_genre_and_event_safety(self):
        bad=[
            UGLY.replace("hard rock satirique teinté de funk et de métal alternatif",
                         "funk satirique et pop alternative"),
            UGLY.replace("UGLY KID JOE</h1>","Festival UGLY KID JOE</h1>"),
            UGLY.replace("5 février 2027","5 février 2025"),
            UGLY.replace("5 février 2027","31 février 2027"),
            UGLY.replace("5 février 2027","5 février 2029"),
            UGLY.replace("5 février 2027","5 février 2027").replace(
                "<h2>ven. 5 février 2027 - 20:00</h2>",""),
            UGLY.replace("</section>","<h2>autre heure 12 mars 2027 - 20:00</h2></section>"),
        ]
        for i,html in enumerate(bad):
            with self.subTest(case=i),self.assertRaises(ValueError):
                m.candidate(html,UGLY_URL,SOURCE,TODAY)
        with self.assertRaises(ValueError):
            m.candidate(UGLY,UGLY_URL,{**SOURCE,"city":"Caen"},TODAY)

    def test_bound_and_prioritize_unpublished_detail_urls(self):
        values=[f"https://bigbandcafe.com/event-{i}/" for i in range(40)]
        self.assertEqual(len(m.selected_urls(values,set(),TODAY,99)),8)
        self.assertEqual(m.selected_urls([UGLY_URL],
            {("officialUrl",UGLY_URL)},TODAY),[UGLY_URL])

    def test_p1_review_only_source_config(self):
        data=json.loads((Path(__file__).resolve().parent/"sources.json").read_text(
            encoding="utf-8"))
        source=next(v for v in data["venues"] if v["id"]=="venue-source-021")
        self.assertEqual(source["priority"],"P1")
        self.assertEqual(source["adapter"],"bbc_official_detail_review")
        self.assertEqual(source["maxDetailPagesPerRun"],8)
        self.assertFalse(source["publicationAllowed"])
        self.assertFalse(source["publish_automatically"])


if __name__=="__main__":
    unittest.main()
