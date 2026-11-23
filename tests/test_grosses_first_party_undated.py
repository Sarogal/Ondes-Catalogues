"""New national official-first-party festival editions without fixed dates.

No live network, no named allowlist, no copied past-date venue or coordinates.
"""
from copy import deepcopy
from pathlib import Path
import json
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "festival-automation"))

from grossesondes_first_party_undated_edition import (
    PROOF_MODE, confirmed_future_without_dates, private_proposal,
    validate_private_proposal, independently_verify, validate_verified_row,
)
from grossesondes_cloud_sync import collect_registered_direct_undated_sources
from grossesondes_stage import stage
from national_generic_primary_domain_preflight import (
    append_direct_first_party_undated_proposals,
)
from test_grosses_stage import fixtures

TODAY = "2026-11-23"
SITE = "https://esquiriot.fr/"
TITLE = "Esqui'Riot 2027"
HTML = """<html><head><title>Esqui'Riot — programmation 2026</title></head>
<main><h1>Esqui'Riot</h1><section>
<p>Édition 2 — Été 2027</p><p>Festival Punk · Métal · Rock</p>
<p>Sainte-Hélène, Gironde</p><p>Billets bientôt disponibles</p>
</section><section><h2>Line Up 2026</h2>
<p>Retrouvez les photos de la première édition du festival.</p>
<p>Esqui'Riot vit grâce à toi.</p></section></main></html>"""


def private_queue():
    return {
        "schema": "grossesondes.national-festival-discovery-private.v1",
        "as_of": TODAY, "review_only": True,
        "safe_to_publish": False, "publication_authorized": False,
        "dossiers": [{
            "id": "national-6f910829672ed8ea614c",
            "name_hint": "Esqui'Riot",
            "edition_year_hint": 2027,
            "publication_authorized": False, "safe_to_publish": False,
            "sources": [{
                "url": SITE, "kind": "CURATED_PRIMARY_CANDIDATE",
                "discovered_via": SITE, "firstSeen": TODAY,
                "lastSeen": TODAY, "publication_authorized": False,
            }],
        }],
    }


class DirectUndatedNationalTests(unittest.TestCase):
    def test_realistic_2027_first_party_announcement(self):
        self.assertTrue(confirmed_future_without_dates(
            SITE, TITLE, HTML, TODAY))
        proposal = private_proposal(TITLE, SITE, TODAY)
        self.assertEqual(proposal["proofMode"], PROOF_MODE)
        self.assertEqual(proposal["slug"], "esqui-riot-2027")
        self.assertEqual(proposal["status"], "Dates à venir")
        self.assertIsNone(proposal["startDate"])
        self.assertIsNone(proposal["endDate"])
        self.assertIsNone(proposal["city"])
        self.assertIsNone(proposal["venue"])
        self.assertIsNone(proposal["lat"])
        self.assertIsNone(proposal["lon"])
        self.assertFalse(proposal["showOnMap"])
        self.assertEqual(proposal["lineup"], [])
        self.assertEqual(proposal["bands"], 0)
        self.assertIsNone(proposal["price"])

    def test_no_2026_reuse_or_unrelated_year_or_conditional_proposal(self):
        cases = [
            HTML.replace("Été 2027", "Été 2026"),
            HTML.replace("Édition 2 — Été 2027",
                         "Préparer l'édition 2 — Été 2027"),
            HTML.replace("Édition 2 — Été 2027",
                         "Édition 2 — Été 2027. Les 13 et 14 août 2027"),
            HTML.replace("<p>Édition 2 — Été 2027</p>",
                         "<script>Édition 2 — Été 2027</script>"),
            HTML.replace("Festival Punk · Métal · Rock",
                         "Festival électro / techno"),
        ]
        for html in cases:
            with self.subTest(html=html[:100]):
                self.assertFalse(confirmed_future_without_dates(
                    SITE, TITLE, html, TODAY))
        self.assertFalse(confirmed_future_without_dates(
            "https://unrelated-example.fr/", TITLE, HTML, TODAY))

    def test_publisher_second_first_party_fetch_and_strict_signed_row(self):
        proposal = private_proposal(TITLE, SITE, TODAY)
        fetches = []
        def read(url):
            fetches.append(url)
            return HTML
        verified = independently_verify(proposal, TODAY, fetch=read)
        self.assertEqual(fetches, [SITE])
        self.assertIsNotNone(verified)
        self.assertEqual(validate_verified_row(proposal, verified, TODAY), verified)
        self.assertFalse(verified["showOnMap"])
        self.assertEqual(verified["status"], "Dates à venir")
        altered = dict(verified, city="Sainte-Hélène")
        self.assertIsNone(validate_verified_row(proposal, altered, TODAY))
        altered = dict(verified, startDate="2027-08-01")
        self.assertIsNone(validate_verified_row(proposal, altered, TODAY))
        altered = dict(proposal, showOnMap=True, lat=45.0, lon=-1.0)
        self.assertIsNone(validate_private_proposal(altered, TODAY))
        self.assertIsNone(independently_verify(
            proposal, TODAY, fetch=lambda _: HTML.replace(
                "Été 2027", "Été 2026")))

    def test_closed_patch_not_authority_and_duplicate_not_republished(self):
        p = private_proposal(TITLE, SITE, TODAY)
        sources = collect_registered_direct_undated_sources(
            {"additions": [p]}, set(), TODAY, fetch=lambda _: HTML)
        self.assertTrue(sources["registered-direct-undated-verified:" + p["slug"]])
        self.assertIsNotNone(sources["registered-direct-undated:" + p["slug"]])
        self.assertEqual(collect_registered_direct_undated_sources(
            {"additions": [p]}, {p["slug"]}, TODAY, fetch=lambda _: HTML),
            {})
        malformed = dict(p, venue="Forged venue")
        self.assertEqual(collect_registered_direct_undated_sources(
            {"additions": [malformed]}, set(), TODAY,
            fetch=lambda _: HTML), {})

    def test_stage_needs_publisher_verified_proof_to_add(self):
        cal, history, patch = fixtures()
        patch["generated_at"] = TODAY
        patch["additions"] = [private_proposal(TITLE, SITE, TODAY)]
        patch["updates"] = []
        published, report = stage(
            cal, history, patch, {}, TODAY,
            production_calendar=cal, production_history=history)
        self.assertNotIn("esqui-riot-2027", report["accepted_additions"])
        self.assertEqual(len(published["festivals"]), len(cal["festivals"]))
        sources = collect_registered_direct_undated_sources(
            patch, set(), TODAY, fetch=lambda _: HTML)
        published, report = stage(
            cal, history, patch, sources, TODAY,
            production_calendar=cal, production_history=history)
        self.assertIn("esqui-riot-2027", report["accepted_additions"])
        new = published["festivals"][-1]
        self.assertEqual(new["status"], "Dates à venir")
        self.assertIsNone(new["startDate"])
        self.assertEqual(new["lineup"], [])
        self.assertEqual(new["officialSite"], SITE)
        self.assertFalse(new["showOnMap"])
        existing = dict(new)
        cal2 = dict(cal, festivals=cal["festivals"] + [existing])
        patch["source"]["festivals"]["count"] = len(cal2["festivals"])
        rejected, report2 = stage(
            cal2, history, patch, sources, TODAY,
            production_calendar=cal2, production_history=history)
        self.assertEqual(len(rejected["festivals"]), len(cal2["festivals"]))
        self.assertEqual(report2["accepted_additions"], [])

    def test_private_national_intake_creates_a_candidate_not_a_publication(self):
        cal, history, patch = fixtures()
        empty = {"schema": 1, "festivals": []}
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            patch["generated_at"] = TODAY
            patch["additions"] = []
            patch["updates"] = []
            (folder / ("patch-" + TODAY + ".json")).write_text(
                json.dumps(patch, ensure_ascii=False), encoding="utf-8")
            added, diagnostics = append_direct_first_party_undated_proposals(
                folder, empty, history, private_queue(), TODAY,
                fetch=lambda _: HTML)
            self.assertEqual(added, 1)
            self.assertEqual(
                diagnostics[0]["gate"], "PRIVATE_UNDATED_PROPOSAL_CREATED")
            new = json.loads(
                (folder / ("patch-" + TODAY + ".json")).read_text(
                    encoding="utf-8"))
            self.assertEqual(len(new["additions"]), 1)
            self.assertFalse(new["safe_to_publish"])
            self.assertEqual(new["additions"][0]["slug"], "esqui-riot-2027")
            self.assertFalse(diagnostics[0]["publication_authorized"])
            again, _ = append_direct_first_party_undated_proposals(
                folder, empty, history, private_queue(), TODAY,
                fetch=lambda _: HTML)
            self.assertEqual(again, 0)


if __name__ == "__main__":
    unittest.main()
