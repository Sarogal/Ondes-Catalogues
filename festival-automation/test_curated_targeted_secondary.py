"""Cross-pipeline tests for targeted independent-source research, never approval."""
from copy import deepcopy
from pathlib import Path
import json
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parent))
from curated_future_lead_watch import load_leads
from curated_targeted_secondary import (
    TARGETED_INDEXES, APPROVED_ALL, validated_targets, targeted_scan)
from curated_secondary_discovery import scan, build_review, STATUS

LEADS = load_leads(json.loads(Path(__file__).with_name(
    "curated_future_leads.json").read_text(encoding="utf-8")))
REGIONAL = [
    {"id": "paca-digne", "region": "Provence-Alpes-Côte d'Azur",
     "url": "https://www.dignelesbains-tourisme.com/agendas/tout-lagenda/"}
]
JDS = [r for r in validated_targets() if "jds.fr" in r["url"]][0]
DETAIL = "https://www.jds.fr/marseille/manifestations/festival/la-sainte-rock-festival-2027-1799241_A"
DAY1, DAY2 = "2026-11-06", "2026-11-07"


def html_index():
    return ('<main><a href="' + DETAIL
            + '">La Sainte Rock Festival 2027</a><p>Programme local.</p></main>')


def html_details():
    return ('<main><h1>La Sainte Rock Festival</h1>'
            '<p>23 24 avril 2027 à Aix en Provence, au 6MIC.</p></main>')


class TargetedDiscoveryTests(unittest.TestCase):
    def test_exact_curated_targets_not_user_supplied(self):
        targets = validated_targets()
        self.assertEqual(len(targets), 3)
        self.assertIn(JDS["url"], APPROVED_ALL)
        self.assertEqual(APPROVED_ALL[JDS["url"]], "Provence-Alpes-Côte d'Azur")
        self.assertTrue(all("independent" not in row for row in targets))
        self.assertTrue(all(r["role"] != "INDEPENDENTLY_CORROBORATED"
                            for r in TARGETED_INDEXES))

    def test_jds_aix_index_discovers_sainte_but_not_verified(self):
        state = {"schema": "grossesondes.source-watch.v1"}
        visited = []
        def fetch(url):
            visited.append(url)
            return html_index() if url == JDS["url"] else html_details()
        # A one-item targeted slice allows deterministically testing the JDS source.
        outcomes, new, checks = scan(
            state, LEADS, [JDS], DAY1, fetch=fetch,
            approved=APPROVED_ALL, attempts_key="secondary_targeted_index_last_attempted",
            queue_indexes=REGIONAL + validated_targets())
        self.assertEqual((new, checks), (1, 0))
        self.assertEqual(visited, [JDS["url"]])
        row = build_review(state, LEADS, REGIONAL + validated_targets(),
                           DAY1, approved=APPROVED_ALL)["sources"][0]
        self.assertEqual(row["lead_id"], "la-sainte-rock-festival-2027")
        self.assertFalse(row["independence_verified"])
        self.assertFalse(row["publication_authorized"])

    def test_next_day_targeted_detail_still_not_independent(self):
        state = {"schema": "grossesondes.source-watch.v1"}
        def fetch(url):
            return html_index() if url == JDS["url"] else html_details()
        kwargs = dict(fetch=fetch, approved=APPROVED_ALL,
                      attempts_key="secondary_targeted_index_last_attempted",
                      queue_indexes=REGIONAL + validated_targets())
        scan(state, LEADS, [JDS], DAY1, **kwargs)
        _, new, attempts = scan(state, LEADS, [JDS], DAY2, **kwargs)
        self.assertEqual((new, attempts), (0, 1))
        result = build_review(state, LEADS, REGIONAL + validated_targets(),
                              DAY2, approved=APPROVED_ALL)
        row = result["sources"][0]
        self.assertTrue(row["detail_date_seen"])
        self.assertEqual(result["independently_verified_count"], 0)
        self.assertFalse(result["publication_authorized"])
        self.assertFalse(result["safe_to_publish"])

    def test_national_media_is_not_a_geographic_restriction(self):
        src = [x for x in validated_targets()
               if x["region"] == "FRANCE"][0]
        state = {"schema": "grossesondes.source-watch.v1"}
        seen = []
        def fetch(url):
            seen.append(url)
            return "<main>Festival, prochainement</main>"
        scan(state, LEADS, [src], DAY1, fetch=fetch,
             approved=APPROVED_ALL,
             attempts_key="secondary_targeted_index_last_attempted",
             queue_indexes=validated_targets())
        self.assertEqual(seen, [src["url"]])
        self.assertEqual(state["secondary_source_candidates_private"], {})

    def test_targeted_scan_preserves_regional_candidates(self):
        state = {"schema": "grossesondes.source-watch.v1"}
        url = ("https://www.dignelesbains-tourisme.com/agendas/tout-lagenda/"
               "la-sainte-rock-2027/")
        state["secondary_source_candidates_private"] = {
            "la-sainte-rock-festival-2027": [{
                "lead_id": "la-sainte-rock-festival-2027",
                "candidate_url": url, "index_url": REGIONAL[0]["url"],
                "firstSeen": DAY1, "lastSeen": DAY1,
                "status": STATUS, "publication_authorized": False,
                "independence_verified": False,
            }]
        }
        outcomes, _, _, report = targeted_scan(
            state, LEADS, REGIONAL, DAY2, fetch=lambda _: "<main>aucun lien</main>",
            limit=2, detail_limit=0)
        self.assertEqual(len(outcomes), 2)
        self.assertEqual(report["candidate_sources_count"], 1)
        self.assertEqual(report["sources"][0]["candidate_url"], url)
        self.assertFalse(report["publication_authorized"])

    def test_regionals_can_preserve_targeted_candidate(self):
        state = {"schema": "grossesondes.source-watch.v1"}
        state["secondary_source_candidates_private"] = {
            "la-sainte-rock-festival-2027": [{
                "lead_id": "la-sainte-rock-festival-2027",
                "candidate_url": DETAIL, "index_url": JDS["url"],
                "firstSeen": DAY1, "lastSeen": DAY1,
                "status": STATUS, "publication_authorized": False,
                "independence_verified": False,
            }]
        }
        scan(state, LEADS, REGIONAL, DAY2,
             fetch=lambda _: "<main>nothing</main>", detail_limit=0,
             approved=APPROVED_ALL,
             queue_indexes=REGIONAL + validated_targets())
        row = build_review(state, LEADS, REGIONAL + validated_targets(),
                           DAY2, approved=APPROVED_ALL)["sources"][0]
        self.assertEqual(row["candidate_url"], DETAIL)

    def test_fake_link_and_query_do_not_get_fetched(self):
        state = {"schema": "grossesondes.source-watch.v1"}
        malicious = ('<main><a href="https://attacker.example/evil-2027">'
                     'La Sainte Rock Festival 2027</a></main>')
        visited = []
        def fetch(url):
            visited.append(url)
            return malicious
        scan(state, LEADS, [JDS], DAY1, fetch=fetch, approved=APPROVED_ALL,
             attempts_key="secondary_targeted_index_last_attempted",
             queue_indexes=validated_targets())
        self.assertEqual(visited, [JDS["url"]])
        self.assertEqual(state["secondary_source_candidates_private"], {})

    def test_index_budgets_are_strict(self):
        state = {"schema": "grossesondes.source-watch.v1"}
        with self.assertRaises(ValueError):
            targeted_scan(state, LEADS, REGIONAL, DAY1,
                          fetch=lambda _: "<main>nothing</main>", limit=3)
        with self.assertRaises(ValueError):
            targeted_scan(state, LEADS, REGIONAL, DAY1,
                          fetch=lambda _: "<main>nothing</main>", detail_limit=2)


if __name__ == "__main__":
    unittest.main()
