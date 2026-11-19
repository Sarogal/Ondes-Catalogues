"""Publisher proof gate tests for a truly new festival, without signed archive."""
from copy import deepcopy
from datetime import date
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "festival-automation"))
from grossesondes_institutional_linked_edition import (
    PROOF_MODE, linked_site, trusted_live_link, prove_dates,
    private_proposal, validate_private_proposal, independently_verify,
    validate_verified_row,
)
from grossesondes_cloud_sync import collect_registered_linked_sources, build_candidate
from grossesondes_stage import stage
from test_grosses_stage import fixtures

TODAY = "2026-11-07"
INDEX = "https://agenda.montpellier.fr/"
DETAIL = "https://agenda.montpellier.fr/evenement/metal-des-garrigues-2027"
TITLE = "Festival Metal des Garrigues 2027"
SITE = "https://festival-garrigues-exemple.fr/"
INDEX_HTML = ('<main><p>Festival metal et hardcore</p>'
              '<a href="/evenement/metal-des-garrigues-2027">'
              'Festival Metal des Garrigues 2027</a></main>')
DETAIL_HTML = ('<main><h1>Festival Metal des Garrigues 2027</h1>'
               '<p>Site officiel du Festival Metal des Garrigues 2027 : '
               f'<a href="{SITE}">site officiel</a></p></main>')
DATES_HTML = ('<main><h1>Festival Metal des Garrigues 2027</h1>'
              '<p>Les 4 et 5 juin 2027 - festival metal.</p></main>')
SPEC = {
    "index_url": INDEX, "index_page": INDEX, "url": DETAIL,
    "title": TITLE, "year": 2027,
}


def institutional(url):
    if url == INDEX:
        return INDEX_HTML
    if url == DETAIL:
        return DETAIL_HTML
    raise AssertionError("Unreviewed institution URL " + url)


def website(url):
    if url != SITE:
        raise AssertionError("Untrusted new host " + url)
    return DATES_HTML


def proposal():
    return private_proposal(SPEC, SITE, ("2027-06-04", "2027-06-05"), TODAY)


class InstitutionalLinkedPublisherTests(unittest.TestCase):
    def test_live_index_event_link_site_and_dates_independently_proven(self):
        self.assertEqual(linked_site(DETAIL_HTML, SPEC), SITE)
        calls = []
        def trace(url):
            calls.append(url)
            return institutional(url)
        self.assertEqual(trusted_live_link(SPEC, TODAY, trace), SITE)
        self.assertEqual(calls, [INDEX, DETAIL])
        self.assertEqual(prove_dates(DATES_HTML, TITLE, 2027, TODAY),
                         ("2027-06-04", "2027-06-05"))
        row = proposal()
        self.assertIsNotNone(row)
        self.assertEqual(row["proofMode"], PROOF_MODE)
        self.assertEqual(validate_private_proposal(row, TODAY), SPEC)
        approved = independently_verify(
            row, TODAY, institution_fetch=trace, organizer_fetch=website)
        self.assertIsNotNone(approved)
        self.assertEqual(approved["slug"], row["slug"])
        self.assertEqual(approved["officialSite"], SITE)
        self.assertEqual(approved["source"], DETAIL)
        self.assertEqual(approved["lineup"], [])
        self.assertEqual(approved["bands"], 0)
        self.assertIs(approved["showOnMap"], False)
        self.assertIsNone(approved["venue"])
        self.assertIsNone(approved["lat"])
        self.assertEqual(validate_verified_row(row, approved, TODAY), approved)
        self.assertNotIn("proofMode", approved)

    def test_live_domain_derived_only_after_trusted_index_and_visible_link(self):
        p = proposal()
        for detail in (
            "<main><h1>Festival Metal des Garrigues 2027</h1><p>Site officiel bientôt.</p></main>",
            '<main><a href="https://evil-site.fr/">site officiel</a></main>',
            '<main><h2>Autre Festival 2027</h2><p>Site officiel : '
            '<a href="https://evil-site.fr/">site officiel</a></p></main>',
            f'<main><p hidden>Site officiel du {TITLE} : '
            f'<a href="{SITE}">site officiel</a></p></main>',
            DETAIL_HTML.replace(SITE, "https://evil-site.fr/"),
            DETAIL_HTML.replace("site officiel</a>", "billetterie</a>").replace(
                "Site officiel du", "Billets pour"),
            DETAIL_HTML.replace(SITE, "https://127.0.0.1/"),
        ):
            with self.subTest(detail=detail[:80]):
                inspected = []
                def institution_fake(url):
                    inspected.append(url)
                    return INDEX_HTML if url == INDEX else detail
                result = independently_verify(
                    p, TODAY, institution_fetch=institution_fake,
                    organizer_fetch=lambda u: self.fail("Unauthorized website fetch"))
                self.assertIsNone(result)
                self.assertEqual(inspected, [INDEX, DETAIL])
        for index in (
            "<main>Festival Metal des Garrigues 2027 sans lien</main>",
            '<main><a href="/evenement/autre-festival-2027">'
            'Festival Metal des Garrigues 2027</a></main>',
        ):
            visit = []
            self.assertIsNone(independently_verify(
                p, TODAY,
                institution_fetch=lambda url: visit.append(url) or
                    (index if url == INDEX else DETAIL_HTML),
                organizer_fetch=lambda u: self.fail("Index not rechecked")))
            self.assertEqual(visit, [INDEX])

    def test_date_identity_cancellation_contradictions_and_forged_patch_fail(self):
        p = proposal()
        for altered in (
            {"showOnMap": True}, {"venue": "Fabricated venue"},
            {"lat": 47.2}, {"lineup": ["Invented Group"]},
            {"status": "Confirmé"}, {"bands": 1},
            {"officialSite": "https://evil-domain.fr/"},
            {"source": "https://evil-domain.fr/"},
            {"evidence": [INDEX, INDEX, DETAIL, "https://evil-domain.fr/"]},
            {"lastVerified": "2027-06-04", "verified_at": "2027-06-04"},
            {"proofMode": "unreviewed.mode"}, {"unknown": "unsafe"},
        ):
            with self.subTest(altered=altered):
                row = dict(p, **altered)
                self.assertIsNone(validate_private_proposal(row, TODAY))
                self.assertIsNone(independently_verify(
                    row, TODAY, institution_fetch=lambda u: self.fail("Forged proposal requested network"),
                    organizer_fetch=lambda u: self.fail("Forged domain requested network")))
        for html in (
            DATES_HTML.replace("4 et 5", "4 et 6"),
            DATES_HTML.replace("2027", "2026"),
            DATES_HTML.replace("Festival Metal des Garrigues", "Autre Festival"),
            DATES_HTML.replace("festival metal", "festival annulé"),
            "<script>Festival Metal des Garrigues 2027 4 et 5 juin 2027</script>",
            DATES_HTML + '<script type="application/ld+json">' +
            '{"@type":"MusicEvent","name":"Festival Metal des Garrigues 2027",'
            '"startDate":"2027-06-04","endDate":"2027-06-06"}</script>',
        ):
            with self.subTest(html=html[:70]):
                self.assertIsNone(prove_dates(html, TITLE, 2027, TODAY))
                self.assertIsNone(independently_verify(
                    p, TODAY, institution_fetch=institution,
                    organizer_fetch=lambda u: html))

    def test_new_festival_stage_requires_independent_publisher_sources(self):
        cal, history, patch = fixtures()
        p = proposal()
        patch["additions"] = [p]
        patch["updates"] = []
        old, held = stage(cal, history, patch, {}, TODAY)
        self.assertEqual(held["accepted_additions"], [])
        self.assertEqual(len(old["festivals"]), len(cal["festivals"]))
        sources = collect_registered_linked_sources(
            patch, frozenset(), TODAY,
            institution_fetch=institution, organizer_fetch=website)
        self.assertTrue(sources.get("registered-linked-verified:"+p["slug"]))
        approved, report = stage(cal, history, patch, sources, TODAY)
        self.assertEqual(report["accepted_additions"], [p["slug"]])
        self.assertEqual(len(approved["festivals"]), len(cal["festivals"])+1)
        self.assertEqual(approved["festivals"][-1]["lineup"], [])
        self.assertFalse(approved["festivals"][-1]["showOnMap"])
        # A manufactured marker is NOT enough to put forged fields into
        # the published catalogue.
        forged_sources = dict(sources)
        forged_sources["registered-linked:"+p["slug"]] = dict(
            sources["registered-linked:"+p["slug"]], lat=48.1)
        denied, report = stage(cal, history, patch, forged_sources, TODAY)
        self.assertEqual(report["accepted_additions"], [])
        self.assertEqual(len(denied["festivals"]), len(cal["festivals"]))
        for altered in (
            dict(p, officialSite="https://evil-domain.fr/"),
            dict(p, lat=45.2),
        ):
            patch["additions"] = [altered]
            visited = []
            no = collect_registered_linked_sources(
                patch, frozenset(), TODAY,
                institution_fetch=lambda u: visited.append(u),
                organizer_fetch=lambda u: visited.append(u))
            self.assertEqual(no, {})
            self.assertEqual(visited, [])

    def test_signed_duplicate_cannot_be_republished(self):
        cal, history, patch = fixtures()
        p = proposal()
        patch["additions"] = [p]
        patch["updates"] = []
        sources = collect_registered_linked_sources(
            patch, frozenset(), TODAY,
            institution_fetch=institution, organizer_fetch=website)
        cal["festivals"][0] = {
            "slug": "already-published-matching",
            "name": TITLE, "startDate": "2027-06-04", "endDate": "2027-06-05",
            "officialSite": SITE, "showOnMap": False,
        }
        _, report = stage(cal, history, patch, sources, TODAY)
        self.assertEqual(report["accepted_additions"], [])
        self.assertEqual(collect_registered_linked_sources(
            patch, {p["slug"]}, TODAY,
            institution_fetch=lambda u: self.fail("Already published")),
            {})


if __name__ == "__main__":
    unittest.main()
