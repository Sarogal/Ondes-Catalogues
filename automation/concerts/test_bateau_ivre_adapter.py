"""Bateau Ivre Tours: no inferred dates, genres, venues or approvals."""
import datetime as dt
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import bateau_ivre_adapter as b
import discover

NOW = "2026-11-04"
URL = b.BASE + "/%C3%A9v%C3%A8nements/cachemire-la-phaze-bobs-not-dead/"
SOURCE = {
    "name": "Le Bateau Ivre", "city": "Tours", "department": "37",
    "priority": "P1", "url": b.ARCHIVE, "adapter": "bateau_ivre_official_detail_review",
    "maxDetailPagesPerRun": 6,
}
LISTING = """<html><main>
<a href="https://www.bateauivre.coop/évènements/cachemire-la-phaze-bobs-not-dead/">
CACHEMIRE</a>
<a href="https://www.bateauivre.coop/évènements/meteora-systemize/">
METEORA</a>
<a href="https://www.bateauivre.coop/évènements/cachemire-la-phaze-bobs-not-dead/">
Duplicate</a>
<a href="https://fake.example/évènements/fake-band/">Fake</a>
<a href="https://www.bateauivre.coop/évènements/cachemire-la-phaze-bobs-not-dead/?utm=1">
Tracking</a>
</main></html>"""
LIVE = """<html><main><article>
<h1>CACHEMIRE + LA PHAZE + BOB’S NOT DEAD</h1>
Jeudi 28 Jan 2027<br>19h30
<p>18€ / 22€ / 26€</p>
<h3>Du rock, de l’engagement et une cause essentielle qui rassemble</h3>
<p>Au programme, un plateau 100 % français, rock, généreux et taillé pour la scène :
CACHEMIRE : rock puissant, LA PHAZE : punk rock electro,
BOB’S NOT DEAD : chanson punk populaire.</p>
</article></main></html>"""
NO_GENRE = """<html><main><article>
<h1>METEORA + SYSTEMIZE</h1>
Vendredi 5 Fév 2027<br>19h30
<p>18€ / 20€ / 25€</p>
<p>Le Bateau remet ça avec ces deux cover bands hexagonaux.
Des hymnes pour chanter.</p>
</article></main></html>"""


class BateauIvreOfficialTests(unittest.TestCase):
    def test_only_exact_annual_2027_index_is_visited(self):
        self.assertTrue(b.valid_archive(b.ARCHIVE))
        for x in (
            b.BASE+"/2026/?post_type=events",
            b.BASE+"/2027/page/2/?post_type=events",
            b.BASE+"/2027/?post_type=events&page=2",
            b.BASE+"/2027/?post_type=concerts",
            "http://www.bateauivre.coop/2027/?post_type=events",
            "https://other.example/2027/?post_type=events",
            b.ARCHIVE+"&post_type=events",
        ):
            with self.subTest(x=x):
                self.assertFalse(b.valid_archive(x))
        with self.assertRaises(ValueError):
            b.archive_links(LISTING, b.BASE+"/2026/?post_type=events")

    def test_named_official_support_before_full_date_is_not_silently_lost(self):
        url = (b.BASE + "/%C3%A9v%C3%A8nements/"
               "orchestre-tout-puissant-marcel-duchamp/")
        page = """<html><main><article>
        <h1>Orchestre tout puissant Marcel Duchamp</h1>
        <h2>+ TACHYCARDIE</h2>
        Jeudi 21 Jan 2027<br>20h
        <p>Le groupe est post-punk, guitares et fanfare punk.</p>
        <h1>Orchestre tout puissant Marcel Duchamp</h1>
        Jeudi 21 Jan 2027<br>20h
        <p>Un concert de rock alternatif.</p>
        <h2>+ TACHYCARDIE</h2>
        <p>Présentation du second artiste.</p>
        <h2>+ GROUPE D'UNE AUTRE RECOMMANDATION</h2>
        </article></main></html>"""
        row = b.candidate(page, url, SOURCE, NOW)
        self.assertEqual(row["leadArtist"],
                         "Orchestre tout puissant Marcel Duchamp")
        self.assertEqual(row["name"],
                         "Orchestre tout puissant Marcel Duchamp + TACHYCARDIE")
        self.assertEqual(row["firstPartyNamedSupport"], ["TACHYCARDIE"])
        self.assertEqual(row["date"], "2027-01-21")
        self.assertFalse(row["publicationAllowed"])
        self.assertIsNone(row["localTime"])
        # The distant recommended H2 may not be accepted as an artist.
        self.assertNotIn("GROUPE D'UNE", row["name"])
        no_support = page.replace("<h2>+ TACHYCARDIE</h2>\n        Jeudi",
                                  "Jeudi", 1)
        row = b.candidate(no_support, url, SOURCE, NOW)
        self.assertEqual(row["firstPartyNamedSupport"], [])
        self.assertEqual(row["name"],
                         "Orchestre tout puissant Marcel Duchamp")

    def test_multiple_explicit_support_headings_need_same_event_masthead(self):
        url = b.BASE + "/%C3%A9v%C3%A8nements/some-band-one-two/"
        page = ("""<html><main><h1>SOME BAND</h1>
            <h2>+ OPENING ONE</h2><h2>+ OPENING TWO</h2>
            Vendredi 12 Mars 2027<br>20h
            <p>Concert punk et metal en salle.</p>
            </main></html>""")
        row = b.candidate(page, url, SOURCE, NOW)
        self.assertEqual(row["name"],
                         "SOME BAND + OPENING ONE + OPENING TWO")
        self.assertEqual(row["firstPartyNamedSupport"],
                         ["OPENING ONE", "OPENING TWO"])
        no_first_party = page.replace(
            "<h2>+ OPENING TWO</h2>",
            "Vendredi 12 Mars 2027<br><h2>+ OPENING TWO</h2>")
        row = b.candidate(no_first_party, url, SOURCE, NOW)
        self.assertEqual(row["firstPartyNamedSupport"], ["OPENING ONE"])

    def test_current_month_programme_is_exact_and_unpublished(self):
        source = {**SOURCE, "name": "Le Bateau Ivre — programme courant",
                  "url": b.CURRENT}
        self.assertTrue(b.valid_current(b.CURRENT))
        for blocked in (b.BASE+"/agenda-2/?page=2",
                        b.BASE+"/2026/?post_type=events",
                        "http://www.bateauivre.coop/agenda-2/",
                        b.BASE+"/agenda-2/#agenda"):
            self.assertFalse(b.valid_current(blocked))
            with self.assertRaises(ValueError):
                b.archive_links(LISTING, blocked)
        current_url = b.BASE+"/%C3%A9v%C3%A8nements/lofofora-akiavel-gravity/"
        listing = ('<main><a href="/évènements/lofofora-akiavel-gravity/">'
                   'Lofofora</a><a href="https://untrusted.example/évènements/nope/">'
                   'bad</a></main>')
        detail = ("<main><h1>LOFOFORA + AKIAVEL + GRAVITY</h1>"
                  "<h2>ASSAUT’LIDAIRE</h2>Samedi 7 Nov 2026<br>19h30"
                  "<p>Concert metal à Tours avec les trois groupes de metal.</p>"
                  "</main>")
        self.assertEqual(b.archive_links(listing,b.CURRENT),[current_url])
        candidate = b.candidate(detail,current_url,source,NOW)
        self.assertEqual(candidate["date"], "2026-11-07")
        self.assertEqual(candidate["venue"], "Le Bateau Ivre")
        self.assertEqual(candidate["sourcePage"], b.CURRENT)
        self.assertFalse(candidate["publicationAllowed"])
        self.assertIsNone(candidate["localTime"])
        with self.assertRaises(ValueError):
            b.candidate(detail.replace("7 Nov 2026", "7 Nov"),
                        current_url, source, NOW)
        with self.assertRaises(ValueError):
            b.candidate(detail,current_url,
                        {**source,"name":"Unrelated venue"}, NOW)

    def test_current_month_scanner_is_bounded_and_does_not_publish(self):
        config=json.loads((Path(__file__).parent/"sources.json").read_text())
        source=next(x for x in config["venues"]
                    if x["name"]=="Le Bateau Ivre — programme courant")
        url=b.BASE+"/%C3%A9v%C3%A8nements/lofofora-akiavel-gravity/"
        page=("<main><h1>LOFOFORA + AKIAVEL + GRAVITY</h1>"
              "Samedi 7 Nov 2026<br>19h30"
              "<p>Concert de metal et de rock.</p><p>Musique live.</p></main>")
        listing='<main><a href="/évènements/lofofora-akiavel-gravity/">Lofofora</a></main>'
        expected={b.CURRENT:listing,url:page}
        def download(value,**kwargs):
            if value not in expected:
                raise RuntimeError("No unexpected web crawling")
            return expected[value],value
        report=[]
        with (patch.object(discover,"robots_allow",return_value=True),
              patch.object(discover,"download",side_effect=download)):
            results=discover.scan_venues({"venues":[source]},set(),
                                         dt.date.fromisoformat(NOW),report)
        self.assertEqual(len(results),1)
        self.assertFalse(results[0]["publicationAllowed"])
        self.assertEqual(report[0]["adapterDiagnostic"]["datedGenreLeads"],1)

    def test_accept_encoded_and_unicode_event_url_but_no_external_redirects(self):
        encoded = b.normalize_detail(
            b.BASE+"/évènements/cachemire-la-phaze-bobs-not-dead/")
        self.assertEqual(encoded, URL)
        self.assertEqual(b.normalize_detail(URL), URL)
        self.assertEqual(b.archive_links(LISTING, b.ARCHIVE), [
            URL, b.BASE+"/%C3%A9v%C3%A8nements/meteora-systemize/"
        ])
        for url in (
            "https://evil.example/évènements/cachemire-la-phaze-bobs-not-dead/",
            "http://www.bateauivre.coop/évènements/cachemire-la-phaze-bobs-not-dead/",
            URL+"?utm_source=test", URL+"#info",
            b.BASE+"/events/cachemire-la-phaze-bobs-not-dead/",
        ):
            self.assertIsNone(b.normalize_detail(url))

    def test_first_party_full_date_rock_punk_and_no_concert_start(self):
        c = b.candidate(LIVE, URL, SOURCE, NOW)
        self.assertEqual(c["date"], "2027-01-28")
        self.assertEqual(c["venue"], "Le Bateau Ivre")
        self.assertEqual(c["leadArtist"], "CACHEMIRE")
        self.assertIn(c["classification"][0], ("rock", "punk"))
        self.assertIsNone(c["localTime"])
        self.assertFalse(c["publicationAllowed"])
        self.assertTrue(c["reviewRequired"])
        self.assertEqual(c["sourceUrl"], URL)

    def test_wordpress_repeated_h1_and_leading_main_chrome(self):
        # Actual first-party pages can repeat a visible masthead, while
        # navigation and hidden page chrome contribute text before H1.
        repeated = LIVE.replace(
            "</article>",
            "<h1>CACHEMIRE + LA PHAZE + BOB’S NOT DEAD</h1>"
            "Jeudi 28 Jan 2027<p>rock</p></article>",
        )
        chrome = "<div>Menus et informations annexes</div>" * 16
        repeated = repeated.replace("<main>", "<main>" + chrome)
        record = b.candidate(repeated, URL, SOURCE, NOW)
        self.assertEqual(record["date"], "2027-01-28")
        self.assertEqual(record["leadArtist"], "CACHEMIRE")
        conflict = repeated.replace(
            "<h1>CACHEMIRE + LA PHAZE + BOB’S NOT DEAD</h1>"
            "Jeudi 28 Jan 2027<p>rock</p></article>",
            "<h1>AUTRE GROUPE INCONNU</h1>"
            "Jeudi 28 Jan 2027<p>rock</p></article>")
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            b.candidate(conflict, URL, SOURCE, NOW)
        contradictory_date = repeated.replace(
            "Jeudi 28 Jan 2027<p>rock</p></article>",
            "Jeudi 29 Jan 2027<p>rock</p></article>")
        with self.assertRaisesRegex(ValueError, "conflicting dated"):
            b.candidate(contradictory_date, URL, SOURCE, NOW)

    def test_fail_closed_if_year_missing_or_in_biography_only(self):
        invalid = {
            "year_missing": LIVE.replace("28 Jan 2027", "28 Jan"),
            "bio_year_not_date": LIVE.replace("28 Jan 2027", "28 Jan").replace(
                "CACHEMIRE : rock", "En 2027, CACHEMIRE : rock"),
            "past": LIVE.replace("28 Jan 2027", "28 Jan 2025"),
            "no_genre": LIVE.replace("rock", "pop").replace("punk", "pop"),
            "wrong_title": LIVE.replace("CACHEMIRE + LA PHAZE", "Festival CACHEMIRE + LA PHAZE"),
            "no_heading": LIVE.replace("<h1>", "<h2>").replace("</h1>", "</h2>"),
        }
        for label, page in invalid.items():
            with self.subTest(label=label), self.assertRaises(ValueError):
                b.candidate(page, URL, SOURCE, NOW)
        with self.assertRaises(ValueError):
            b.candidate(NO_GENRE,
                b.BASE+"/%C3%A9v%C3%A8nements/meteora-systemize/", SOURCE, NOW)
        with self.assertRaises(ValueError):
            b.candidate(LIVE, URL, {**SOURCE, "city":"Nantes"}, NOW)
        with self.assertRaises(ValueError):
            b.candidate(LIVE, URL+"?spam=1", SOURCE, NOW)

    def test_three_daily_slots_expand_discovery_without_more_http_pages(self):
        urls = [b.BASE + "/%C3%A9v%C3%A8nements/official-act-" +
                f"{i:02d}/" for i in range(18)]
        day = "2026-11-09"
        results = [b.select_urls(urls, set(), day, limit=6, scan_slot=i)
                   for i in range(3)]
        self.assertTrue(all(len(result) == 6 for result in results))
        self.assertTrue(all(len(set(result)) == 6 for result in results))
        self.assertGreaterEqual(len(set.union(*(set(x) for x in results))), 12)
        self.assertGreaterEqual(len(set.intersection(*(set(x) for x in results))), 2)
        baseline = dt.date.fromisoformat(day)
        if baseline.toordinal() % 2:
            baseline += dt.timedelta(days=1)
        first = b.select_urls(urls, set(), baseline.isoformat(), scan_slot=0)
        second = b.select_urls(
            urls, set(), (baseline + dt.timedelta(days=1)).isoformat(),
            scan_slot=0)
        self.assertEqual(first[:2], second[:2])
        with self.assertRaises(ValueError):
            b.select_urls(urls, set(), day, scan_slot=3)

    def test_known_exact_url_moved_to_end_and_6_detail_max(self):
        links = b.archive_links(LISTING, b.ARCHIVE)
        selected = b.select_urls(links, {("officialUrl",URL)}, NOW, limit=2)
        self.assertEqual(set(selected), set(links))
        self.assertEqual(selected[-1], URL)
        self.assertEqual(len(b.select_urls(links*9, set(), NOW, limit=1)), 1)

    def test_discover_produces_only_private_review_candidates(self):
        real_config = json.loads((Path(__file__).parent/"sources.json").read_text(
            encoding="utf-8"))
        source = next(x for x in real_config["venues"]
                      if x["name"] == "Le Bateau Ivre")
        self.assertEqual(source["adapter"], SOURCE["adapter"])
        self.assertFalse(source["publish_automatically"])
        self.assertEqual(source["priority"], "P1")
        expected = {
            b.ARCHIVE: LISTING,
            URL: LIVE,
            b.BASE+"/%C3%A9v%C3%A8nements/meteora-systemize/": NO_GENRE,
        }
        def download(url, **kwargs):
            if url not in expected:
                raise RuntimeError("Unexpected unbounded or foreign URL")
            return expected[url], url
        report = []
        with patch.object(discover, "robots_allow", return_value=True), \
             patch.object(discover, "download", side_effect=download):
            records = discover.scan_venues({"venues": [source]}, set(),
                                           dt.date.fromisoformat(NOW), report)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["candidateId"],
                         "bateau-ivre:2027-01-28:cachemire-la-phaze-bobs-not-dead")
        self.assertFalse(records[0]["publicationAllowed"])
        self.assertEqual(report[0]["adapterDiagnostic"]["datedGenreLeads"], 1)
        self.assertEqual(report[0]["adapterDiagnostic"]["heldOrIrrelevant"], 1)
        self.assertEqual(report[0]["adapterDiagnostic"]["agendaPagesRead"], 1)
        diagnostic = report[0]["adapterDiagnostic"]
        self.assertEqual(diagnostic["heldReasons"],
                         {"No official relevant musical genre": 1})
        self.assertEqual(diagnostic["heldReviewSamples"], [{
            "url": b.BASE+"/%C3%A9v%C3%A8nements/meteora-systemize/",
            "reason": "No official relevant musical genre",
        }])


if __name__ == "__main__":
    unittest.main()
