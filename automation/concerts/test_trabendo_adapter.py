"""Trabendo discovery safety, no-network tests."""
import datetime as dt
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0,str(Path(__file__).resolve().parent))
import trabendo_adapter as t
import discover

SOURCE={"name":"Le Trabendo","city":"Paris","department":"75",
        "url":"https://www.letrabendo.net/programmation/",
        "priority":"P1","adapter":"trabendo_official_detail_review",
        "maxDetailPagesPerRun":6}
URL="https://www.letrabendo.net/programmation/whitechapel/"
PAGE="""<html><head><title>Whitechapel – Trabendo</title></head>
<body><main><div>03 ― février 2027</div><h1>Whitechapel</h1>
<p>concert ― Metalcore</p><p>→ Trabendo - Salle de concert</p>
<p>03 ― février 2027</p><p>Whitechapel</p><p>Ouverture des portes 19:00</p>
</main></body></html>"""

class TrabendoTest(unittest.TestCase):
    def test_only_allowed_individual_links(self):
        page="<a href='/programmation/whitechapel/'>OK</a><a href='/programmation/whitechapel/'>Dupe</a><a href='https://evil.test/programmation/evil/'>bad</a><a href='/programmation/'>calendar</a>"
        self.assertEqual(t.detail_links(page,SOURCE["url"]),[URL])
        for url in ("http://www.letrabendo.net/programmation/whitechapel/",
                    "https://www.letrabendo.net@evil.test/programmation/whitechapel/",
                    URL+"?tracking=1","https://evil.test/programmation/whitechapel/",
                    "https://www.letrabendo.net/programmation/"):
            self.assertFalse(t.safe(url))
        with self.assertRaises(ValueError):
            t.detail_links(page,"https://evil.test/programmation/")

    def test_individual_page_only_date_headliner_genre_never_doors_or_approval(self):
        event=t.detail_candidate(PAGE,URL,SOURCE,"2026-11-02")
        self.assertEqual((event["date"],event["name"],event["classification"]),
                         ("2027-02-03","Whitechapel",["metalcore"]))
        self.assertIsNone(event["localTime"])
        self.assertTrue(event["reviewRequired"])
        self.assertFalse(event["publicationAllowed"])
        self.assertTrue(event["lineupToConfirm"])
        for bad in (PAGE.replace("2027","2025"),
                    PAGE.replace("Metalcore","Electro"),
                    PAGE.replace("Trabendo - Salle de concert","Autre salle"),
                    PAGE.replace("03 ― février 2027","03 février",2),
                    PAGE.replace("<h1>Whitechapel</h1>","<h1>CONCERT ANNULÉ</h1>")):
            with self.subTest(bad=bad[:60]):
                with self.assertRaises(ValueError):
                    t.detail_candidate(bad,URL,SOURCE,"2026-11-02")
        with self.assertRaises(ValueError):
            t.detail_candidate(PAGE,URL,SOURCE,"2027-03-01")
        with self.assertRaises(ValueError):
            t.detail_candidate(PAGE,URL,dict(SOURCE,city="Lyon"),"2026-11-02")

    def test_real_trabendo_nested_markup_and_recommendations_are_safe(self):
        page="""<html><head><title>Whitechapel – Trabendo</title>
        <script>Concert annulé 1999</script></head><body>
        <h1>Trabendo</h1><nav>Programmation Club Festival</nav>
        <h2><strong>Veryshow présente :</strong></h2>
        <p>Whitechapel, formé en 2006, album sorti en 2022 et 2025.
        Aucune de ces années n'est une date de concert.</p>
        <div class="first-party-event">
          <span>03</span><span>―</span><span>février</span><span>2027</span>
          <strong>Whitechapel</strong>
          <span>concert</span><span>―</span><span>Metalcore</span>
          <span>→ Trabendo</span><span> - Salle de concert</span>
        </div>
        <div>03 ― février 2027</div><p>Whitechapel</p>
        <p>Ouverture des portes 19:00</p>
        <section>Vous devriez aimer
          <h2>22 ― janvier 2027</h2><h5>Metalcore</h5><h3>Wage War</h3>
        </section>
        <footer>© 2022 Le Trabendo</footer></body></html>"""
        row=t.detail_candidate(page,URL,SOURCE,"2026-11-02")
        self.assertEqual((row["date"],row["name"],row["classification"]),
                         ("2027-02-03","Whitechapel",["metalcore"]))
        self.assertFalse(row["publicationAllowed"])
        self.assertTrue(row["reviewRequired"])
        self.assertIsNone(row["localTime"])
        self.assertTrue(row["lineupToConfirm"])
        # The main gig is undated; a recommendation alone cannot establish
        # the date, even when the recommendation happens to be a metal gig.
        other=page.replace(
            "<span>03</span><span>―</span><span>février</span><span>2027</span>",
            "<span>03</span><span>février</span>").replace(
            "<div>03 ― février 2027</div>","<div>03 février</div>")
        with self.assertRaises(ValueError):
            t.detail_candidate(other,URL,SOURCE,"2026-11-02")
        # A changed date in a second same-headliner card is ambiguous.
        ambiguous=page.replace(
            "<div>03 ― février 2027</div><p>Whitechapel</p>",
            "<div>04 ― février 2027</div><p>Whitechapel</p>"
            "<span>concert</span><span>Metalcore</span>"
            "<span>Trabendo - Salle de concert</span>")
        with self.assertRaises(ValueError):
            t.detail_candidate(ambiguous,URL,SOURCE,"2026-11-02")
        # An actual cancellation/relocation in the main event always
        # suppresses the candidate; a script mention is ignored.
        with self.assertRaises(ValueError):
            t.detail_candidate(page.replace(
                "Ouverture des portes 19:00",
                "Concert reporté, changement de salle à confirmer"),
                URL,SOURCE,"2026-11-02")

    def test_other_concert_recommendation_cannot_replace_main_headline(self):
        page="""<html><head><title>Whitechapel – Trabendo</title></head><body>
        <h1>Trabendo</h1><h2>Veryshow présente Whitechapel</h2>
        <p>Whitechapel a sorti un album en 2021.</p>
        <section>Vous devriez aimer
        <div>22 ― janvier 2027</div><p>Wage War</p>
        <p>concert ― Metalcore</p><p>→ Trabendo - Salle de concert</p>
        </section></body></html>"""
        with self.assertRaises(ValueError):
            t.detail_candidate(page,URL,SOURCE,"2026-11-02")

    def test_first_party_genre_tags_set_order_only_never_approve(self):
        html="""<a href='/programmation/electro-pop/'>Concert 20 ― janvier 2027
        <span>electro</span> Other Music</a>
        <a href='/programmation/wage-war/'>Concert 22 ― janvier 2027
        <span>Metalcore</span> Wage War</a>
        <a href='/programmation/whitechapel/'>Concert 03 ― février 2027
        <strong>Metalcore</strong> Whitechapel</a>
        <a href='/programmation/movements/'>Concert 23 ― février 2027
        <span>Post-Hardcore</span> Movements</a>
        <a href='/programmation/black-flag/'>Concert 06 ― juin 2027
        <span>Punk-Hardcore</span> Black Flag</a>
        <a href='/programmation/fake-evil/?redirect=https://evil.test'>No</a>
        <a href='https://evil.test/programmation/fake/'>Metal</a>"""
        focus,rest=t.categorized_detail_links(html,SOURCE["url"])
        self.assertEqual(
            [x.rsplit("/",2)[-2] for x in focus],
            ["wage-war","whitechapel","movements","black-flag"])
        self.assertEqual(
            [x.rsplit("/",2)[-2] for x in rest],["electro-pop"])
        self.assertTrue(all(t.safe(u) for u in focus+rest))
        # A fake category badge is NOT a certification: the individual
        # page still rejects an electronic genre.
        with self.assertRaises(ValueError):
            t.detail_candidate(PAGE.replace("Metalcore","Electro"),
                               URL,SOURCE,"2026-11-02")

    def test_prioritization_diagnostics_do_not_authorize_publication(self):
        listing="<a href='/programmation/whitechapel/'>Concert 03 février 2027 Metalcore Whitechapel</a>"
        inputs={SOURCE["url"]:(listing,SOURCE["url"]),URL:(PAGE,URL)}
        with mock.patch.object(discover,"robots_allow",return_value=True), \
             mock.patch.object(discover,"download",side_effect=lambda url,*a,**k:inputs[url]):
            report=[]
            rows=discover.scan_venues({"venues":[SOURCE]},set(),
                                      dt.date(2026,11,2),report,max_p2=0)
        chosen=[e for e in rows if e["venue"]=="Le Trabendo"]
        self.assertEqual(len(chosen),1)
        self.assertEqual(report[0]["adapterDiagnostic"]["categoryRelevantLinks"],1)
        self.assertEqual(report[0]["adapterDiagnostic"]["datedReviewLeads"],1)
        self.assertFalse(chosen[0]["publicationAllowed"])

    def test_real_run_diagnostic_distinguishes_source_failure_and_rejected_detail(self):
        urls={
            "valid":"https://www.letrabendo.net/programmation/whitechapel/",
            "network":"https://www.letrabendo.net/programmation/wage-war/",
            "wrong":"https://www.letrabendo.net/programmation/wrong-genre/",
            "robots":"https://www.letrabendo.net/programmation/robots-denied/",
        }
        listing="".join("<a href='"+url+"'>Concert Metalcore "+name+"</a>"
                        for name,url in urls.items())
        def fetch(url,*args,**kwargs):
            if url==SOURCE["url"]:return listing,url
            if url==urls["valid"]:return PAGE,url
            if url==urls["wrong"]:
                return PAGE.replace("Metalcore","Electro"),url
            if url==urls["network"]:
                raise OSError("network failed https://example.test/?secret=never-expose")
            raise AssertionError("robots-denied URL must not be fetched")
        def robots(url,cache):
            return url!=urls["robots"]
        with mock.patch.object(discover,"download",side_effect=fetch), \
             mock.patch.object(discover,"robots_allow",side_effect=robots):
            report=[]
            candidates=discover.scan_venues({"venues":[SOURCE]},set(),
                                            dt.date(2026,11,2),report,max_p2=0)
        diag=report[0]["adapterDiagnostic"]
        self.assertEqual(diag["eventLinksFound"],4)
        self.assertEqual(diag["selectedForReview"],4)
        self.assertEqual(diag["detailPagesChecked"],2)
        self.assertEqual(diag["datedReviewLeads"],1)
        self.assertEqual(diag["validationRejected"],1)
        self.assertEqual(diag["validationReasons"],
                         {"date_title_or_genre_not_correlated":1})
        self.assertEqual(diag["blockedOrRobotsUnavailable"],1)
        self.assertEqual(diag["fetchErrors"],1)
        self.assertEqual(diag["redirected"],0)
        self.assertEqual(diag["rejectedOrUnavailable"],3)
        self.assertNotIn("secret=never-expose",str(report))
        self.assertEqual(len([x for x in candidates
            if x["source"]=="agenda_officiel_trabendo_detail"]),1)
        self.assertFalse(diag["publicationAllowed"])

    def test_discovery_integration_never_publishes(self):
        listing="<a href='/programmation/whitechapel/'>Whitechapel</a>"
        inputs={SOURCE["url"]:(listing,SOURCE["url"]),URL:(PAGE,URL)}
        with mock.patch.object(discover,"robots_allow",return_value=True), \
             mock.patch.object(discover,"download",side_effect=lambda url,*a,**k:inputs[url]):
            report=[]
            rows=discover.scan_venues({"venues":[SOURCE]},set(),
                                      dt.date(2026,11,2),report,max_p2=0)
        selected=[r for r in rows if r["source"]=="agenda_officiel_trabendo_detail"]
        self.assertEqual(len(selected),1)
        self.assertFalse(selected[0]["publicationAllowed"])
        self.assertEqual(report[0]["adapterDiagnostic"]["datedReviewLeads"],1)

if __name__=="__main__":
    unittest.main()
