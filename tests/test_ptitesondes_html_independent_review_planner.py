"""Offline tests: fair independent HTML evidence planning, zero approval."""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_family_national_scope import FAMILY_TYPES
from ptitesondes_nonmusical_private_queue_handoff import _row_from_proof
from ptitesondes_html_independent_review_planner import (
    CHALLENGES, SOURCE_CHALLENGES, SCHEMA, plan_independent_reviews,
)

TODAY = date(2026, 11, 20)


def review(*, n=1, city="Montpellier", source="mpt.montpellier.fr",
           reason="institutional_source_policy_pending", day="2026-11-22",
           clock="09:15", category="atelier-sensoriel"):
    draft = {
        "source_url": f"https://{source}/evenement/atelier-{n}",
        "source_title_identity_only": f"Atelier sensoriel {n}",
        "city": city, "venue": f"Lieu officiel {n}",
        "category": category, "date_start": day, "start_local": clock,
    }
    return _row_from_proof(draft, {"stage": reason}, TODAY, None)


class IndependentHtmlReviewPlannerTests(unittest.TestCase):
    def test_each_session_has_six_independent_challenges_and_no_approval(self):
        a, b = review(clock="09:15"), review(clock="10:30")
        result = plan_independent_reviews([a, b], TODAY)
        work = result["private_tasks"]["sessions"]
        self.assertEqual(len(work), 2)
        self.assertNotEqual(work[0]["review_id"], work[1]["review_id"])
        for task in work:
            self.assertEqual(set(task["challenges"]), set(CHALLENGES))
            self.assertIs(task["evidence_verified"], False)
            self.assertIs(task["admission_authorized"], False)
            self.assertNotIn("source_url", task)
            self.assertNotIn("title", task)
        self.assertEqual(result["report"]["selected_sessions"], 2)
        self.assertFalse(result["report"]["publication_ready"])
        self.assertEqual(result["report"]["public_writes"], 0)

    def test_all_fourteen_family_categories_are_covered_equally(self):
        rows = [
            review(n=i+1, category=category, city=f"Commune-{i}")
            for i, category in enumerate(FAMILY_TYPES)
        ]
        result = plan_independent_reviews(rows, TODAY, limit=40)
        self.assertEqual(len(FAMILY_TYPES), 14)
        self.assertEqual(result["report"]["selected_sessions"], 14)
        self.assertEqual(result["report"]["distinct_cities_due"], 14)
        self.assertEqual(result["report"]["cities_covered_in_batch"], 14)

    def test_novel_venue_does_not_require_registration_before_discovery(self):
        a = review(reason="reviewed_venue_missing")
        result = plan_independent_reviews([a], TODAY)
        tasks = result["private_tasks"]["sessions"]
        self.assertEqual(len(tasks), 1)
        self.assertIn("resolve_independent_venue_and_geo",
                      tasks[0]["challenges"])
        self.assertFalse(tasks[0]["admission_authorized"])

    def test_source_reuse_review_one_per_host_not_per_event(self):
        rows = [review(n=i, city=f"Ville-{i}") for i in range(1, 9)]
        out = plan_independent_reviews(rows, TODAY)
        self.assertEqual(out["report"]["selected_source_policies"], 1)
        self.assertEqual(out["report"]["distinct_host_policies_due"], 1)
        source = out["private_tasks"]["source_policies"][0]
        self.assertEqual(source["challenge"],
                         "review_factual_reuse_policy_once_per_host")
        self.assertFalse(source["legal_rights_attested"])
        self.assertFalse(source["source_approved"])

    def test_fair_rotation_across_cities_not_a_city_whitelist(self):
        rows = [review(n=i, city="Montpellier") for i in range(1, 25)]
        rows += [review(n=100+i, city=f"Ville-{i}") for i in range(12)]
        out = plan_independent_reviews(rows, TODAY, limit=12)
        self.assertEqual(out["report"]["selected_sessions"], 12)
        self.assertGreaterEqual(out["report"]["cities_covered_in_batch"], 11)
        self.assertEqual(out["report"]["pending_sessions_unselected"], 24)

    def test_trusted_retry_schedule_is_respected(self):
        a = review(reason="reviewed_venue_unchecked")
        self.assertEqual(a["next_retry_on"], "2026-11-22")
        early = plan_independent_reviews([a], TODAY)
        self.assertEqual(early["report"]["deferred_by_existing_retry"], 1)
        self.assertEqual(early["report"]["selected_sessions"], 0)
        due = plan_independent_reviews([a], date(2026, 11, 22))
        self.assertEqual(due["report"]["selected_sessions"], 1)

    def test_ambiguous_slots_are_rechecked_not_thrown_away(self):
        row = review(reason="historical_collision_ambiguous")
        work = plan_independent_reviews([row], TODAY)["private_tasks"]["sessions"][0]
        self.assertEqual(work["challenges"][0],
                         "independently_recheck_distinct_clock")
        self.assertFalse(work["admission_authorized"])

    def test_expired_duplicates_restrictions_are_held_without_publication(self):
        rows = [
            review(n=1, day="2026-11-19"),
            review(n=2, reason="historical_duplicate"),
            review(n=3, reason="institutional_source_policy_restricted"),
            review(n=4),
        ]
        out = plan_independent_reviews(rows, TODAY)
        report = out["report"]
        self.assertEqual(report["expired_sessions"], 1)
        self.assertEqual(report["duplicates_held"], 1)
        self.assertEqual(report["restricted_sources_held"], 1)
        self.assertEqual(report["selected_sessions"], 1)
        self.assertEqual(report["future_sessions"], 3)
        self.assertEqual(out["private_tasks"]["source_policies"][0][
            "challenge"], "maintain_restricted_source_hold")

    def test_synthetic_malicious_queue_flags_and_duplicates_fail_closed(self):
        a = review()
        for change in (
            {"approved": True}, {"published": True},
            {"safe_to_publish": True}, {"reason_code": "unapproved_new_reason"},
            {"review_id": "bad"}, {"source_url": "http://evil.example/event"},
            {"category": "concert"}, {"start_local": ""},
        ):
            with self.subTest(change=change):
                bad = dict(a, **change)
                with self.assertRaises((ValueError, KeyError)):
                    plan_independent_reviews([bad], TODAY)
        with self.assertRaises(ValueError):
            plan_independent_reviews([a, deepcopy(a)], TODAY)

    def test_public_report_contains_no_candidate_or_location(self):
        a = review(city="Pointe-à-Pitre",
                   source="institution.guadeloupe.example",
                   category="sortie-nature")
        out = plan_independent_reviews([a], TODAY)
        self.assertEqual(out["schema"], SCHEMA)
        report = json.dumps(out["report"], ensure_ascii=False)
        for secret in (
            "Pointe-à-Pitre", "guadeloupe", "https://",
            "html-review-", "2026-11-22", "source_url",
        ):
            self.assertNotIn(secret, report)
        self.assertFalse(out["report"]["contains_candidate_data"])

    def test_cap_and_strict_type_validation(self):
        a = review()
        for limit in (0, 81, True, "40"):
            with self.assertRaises(ValueError):
                plan_independent_reviews([a], TODAY, limit=limit)
        with self.assertRaises(ValueError):
            plan_independent_reviews([a], "2026-11-20")
        self.assertEqual(len(plan_independent_reviews([], TODAY)[
            "private_tasks"]["sessions"]), 0)


if __name__ == "__main__":
    unittest.main()
