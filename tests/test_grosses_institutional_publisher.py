"""Offline publisher contract for generic, never-coded institutional festivals."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from grossesondes_institutional_edition import (
    PROOF_MODE, private_proposal, trusted_source, independently_fetch,
    validate_private_proposal, validate_independent,
    conflicts_with_signed_catalogue,
)
from grossesondes_cloud_sync import (
    collect_registered_institutional_sources, build_candidate,
)
from grossesondes_stage import stage
from test_grosses_stage import fixtures

TODAY = "2026-11-07"
INDEX = "https://agenda.montpellier.fr/"
DETAIL = "https://agenda.montpellier.fr/evenement/metal-des-garrigues-2027"
TITLE = "Festival Metal des Garrigues 2027"
INDEX_HTML = ('<main><a href="/evenement/metal-des-garrigues-2027">'
              'Festival Metal des Garrigues 2027</a></main>')
DETAIL_HTML = ('<main><h1>Festival Metal des Garrigues 2027</h1>'
               '<p>Les 4 et 5 juin 2027, festival de métal.</p></main>')


def proposed():
    return private_proposal({
        "index_url": INDEX, "index_page": INDEX,
        "url": DETAIL, "title": TITLE, "year": 2027,
    }, ("2027-06-04", "2027-06-05"), TODAY)


class InstitutionalPublisherTests(unittest.TestCase):
    def test_generic_edition_enters_catalogue_only_after_independent_live_reproof(self):
        p = proposed()
        self.assertIsNotNone(p)
        self.assertEqual(p["proofMode"], PROOF_MODE)
        self.assertEqual(p["evidence"], [INDEX, INDEX, DETAIL])
        self.assertEqual(p["originSlug"], INDEX)
        self.assertIsNone(p["lat"])
        visited = []
        def fetch(url):
            visited.append(url)
            return {INDEX: INDEX_HTML, DETAIL: DETAIL_HTML}[url]
        sources = collect_registered_institutional_sources(
            {"additions":[p]}, set(), TODAY, fetcher=fetch)
        self.assertEqual(visited, [INDEX, DETAIL])
        self.assertTrue(sources["registered-institutional-verified:"+p["slug"]])
        cal, hist, patch = fixtures()
        patch["additions"] = [p]
        patch["updates"] = []
        snapshot = {"festivals.json": cal, "festival-history.json": hist}
        candidate, report = build_candidate(
            snapshot, snapshot, patch, sources, TODAY, trusted_published=True)
        self.assertEqual(report["accepted_additions"], [p["slug"]])
        self.assertEqual(len(candidate["festivals"]), len(cal["festivals"])+1)
        row = candidate["festivals"][-1]
        self.assertEqual(row["startDate"], "2027-06-04")
        self.assertEqual(row["endDate"], "2027-06-05")
        self.assertIsNone(row["city"])
        self.assertIsNone(row["lat"])
        self.assertFalse(row["showOnMap"])
        self.assertEqual(row["lineup"], [])
        self.assertEqual(row["bands"], 0)
        self.assertNotIn("proofMode", row)
        self.assertIn("institutionnel", row["sourceConfidence"])
        missing, held = build_candidate(
            snapshot, snapshot, patch, {}, TODAY, trusted_published=True)
        self.assertEqual(held["accepted_additions"], [])
        self.assertEqual(missing["festivals"], cal["festivals"])
        # Publishing the same source next time must be idempotent.
        again, second = build_candidate(
            snapshot, {"festivals.json": candidate, "festival-history.json": hist},
            patch, {}, TODAY, trusted_published=True)
        self.assertEqual(second["accepted_additions"], [])
        self.assertFalse(second["changed"])

    def test_spoofed_private_urls_are_never_fetched(self):
        p = proposed()
        for altered in (
                dict(p, originSlug="https://evil.example/"),
                dict(p, officialSite="https://evil.example/event"),
                dict(p, source="https://evil.example/event"),
                dict(p, evidence=[INDEX, INDEX, "https://evil.example/"]),
                dict(p, evidence=[INDEX, "https://agenda.montpellier.fr/admin", DETAIL]),
                dict(p, evidence=[INDEX, INDEX, "http://agenda.montpellier.fr/fest"]),
                dict(p, slug="different-metal-fest-2027"),
                dict(p, showOnMap=True),
                dict(p, lineup=["Imaginary Band"], bands=1),
                dict(p, lat=43.1), dict(p, venue="Old Venue"),
                dict(p, extra_field="untrusted")):
            with self.subTest(altered=altered):
                self.assertIsNone(validate_private_proposal(altered, TODAY))
                visited = []
                sources = collect_registered_institutional_sources(
                    {"additions":[altered]}, set(), TODAY,
                    fetcher=lambda url: visited.append(url))
                self.assertEqual(visited, [])
                self.assertFalse(sources)

    def test_missing_live_index_link_or_genre_refuses_before_detail_fetch(self):
        p = proposed()
        for html in (
            "<main>Festival Metal des Garrigues 2027</main>",
            '<a href="https://evil.example/evil">Festival Metal des Garrigues 2027</a>',
            INDEX_HTML.replace("2027</a>", "2028</a>"),
            INDEX_HTML.replace("Festival Metal", "Festival Jazz"),
            INDEX_HTML.replace("Festival Metal", "Concert Metal"),
        ):
            with self.subTest(html=html):
                visited = []
                def fetch(url):
                    visited.append(url)
                    if url == INDEX:
                        return html
                    raise AssertionError("Detail must not be visited")
                self.assertIsNone(independently_fetch(p, TODAY, fetch=fetch))
                self.assertEqual(visited, [INDEX])

    def test_contradictory_dates_hidden_or_cancelled_not_publishable(self):
        p = proposed()
        for html in (
            DETAIL_HTML.replace("4 et 5", "4 et 6"),
            DETAIL_HTML.replace("2027", "2028"),
            DETAIL_HTML.replace("festival de métal", "festival annulé de métal"),
            '<script>Festival Metal des Garrigues 2027, 4 et 5 juin 2027</script>',
            DETAIL_HTML + '<script type="application/ld+json">' +
            '{"@context":"https://schema.org","@type":"MusicEvent",'
            '"name":"Festival Metal des Garrigues 2027",'
            '"startDate":"2027-06-04","endDate":"2027-06-06"}</script>',
        ):
            with self.subTest(html=html):
                self.assertIsNone(validate_independent(p,html,TODAY))
                sources = collect_registered_institutional_sources(
                    {"additions":[p]}, set(), TODAY,
                    fetcher=lambda url: INDEX_HTML if url == INDEX else html)
                self.assertFalse(sources)

    def test_different_slug_same_official_page_and_year_is_duplicate(self):
        p=proposed()
        cal, hist, patch=fixtures()
        other = {"slug":"same-event-other-title-2027",
                 "name":"Another Festival 2027","startDate":"2027-06-04",
                 "officialSite":DETAIL}
        self.assertTrue(conflicts_with_signed_catalogue(
            p,cal["festivals"]+[other],hist["knownFestivals"]))
        self.assertFalse(conflicts_with_signed_catalogue(
            p,cal["festivals"],hist["knownFestivals"]))

    def test_four_pending_institutions_rotate_two_per_day(self):
        proposals = []
        anchors = []
        details = {}
        for name in ("Nord", "Sud", "Est", "Ouest"):
            title = "Festival Metal des " + name + " 2027"
            url = INDEX + "evenement/festival-metal-des-" + name.lower() + "-2027"
            proposal = private_proposal({
                "index_url":INDEX, "index_page":INDEX,
                "url":url, "title":title, "year":2027,
            }, ("2027-06-04","2027-06-05"), TODAY)
            self.assertIsNotNone(proposal)
            proposals.append(proposal)
            anchors.append('<a href="' + url + '">' + title + '</a>')
            details[url] = ('<h1>' + title + '</h1>'
                            '<p>4 et 5 juin 2027, festival de metal</p>')
        index_html = "<main>" + "".join(anchors) + "</main>"
        def run_day(day):
            checked = []
            def fetch(url):
                checked.append(url)
                return index_html if url == INDEX else details[url]
            sources=collect_registered_institutional_sources(
                {"additions":proposals}, set(), day, fetcher=fetch)
            return set(k for k in sources if
                       k.startswith("registered-institutional-verified:")), checked
        first, visits1 = run_day(TODAY)
        second, visits2 = run_day("2026-11-08")
        self.assertEqual(len(first),2)
        self.assertEqual(len(second),2)
        self.assertEqual(len(first|second),4)
        self.assertEqual(len(visits1),4)
        self.assertEqual(len(visits2),4)

    def test_publisher_recheck_skips_already_published_slug(self):
        p=proposed()
        visited=[]
        sources = collect_registered_institutional_sources(
            {"additions":[p]}, {p["slug"]}, TODAY,
            fetcher=lambda u: visited.append(u))
        self.assertEqual(visited,[])
        self.assertEqual(sources,{})


if __name__=="__main__":
    unittest.main()
