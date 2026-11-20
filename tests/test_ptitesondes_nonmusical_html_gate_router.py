"""Adversarial, offline proof routing without publishers, tokens or network."""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_nonmusical_html_gate_router import (
    STAGES, SCHEMA, ACTIONS, aggregate_html_review_routes,
    route_nonmusical_html_session,
)
from ptitesondes_real_family_source_adapters import parse_montpellier_mpt_detail
from test_ptitesondes_html_index_detail_funnel import MPT_TEMPLATE, ONE, PIN

DAY = date(2026, 11, 20)
VENUE = {
    "city": "Montpellier", "aliases": ["Maison pour tous Albert Camus"],
    "lat": 43.60, "lng": 3.85,
    "official": "https://mpt.montpellier.fr/maisons/albert-camus",
    "geo_source": "https://www.openstreetmap.org/way/12345",
}
CONTEXT = {
    "legacy_venues": [VENUE],
    "public_places": [],
    "historical_catalogue": {
        "updated_at": "2026-11-20T06:00:00+01:00", "events": [],
    },
}
LEAD = parse_montpellier_mpt_detail(MPT_TEMPLATE, ONE, DAY)[0]
PAGE = {"url": ONE, "html": MPT_TEMPLATE}
DEFAULT = object()


def route(lead=DEFAULT, page=DEFAULT, context=DEFAULT, pin=DEFAULT, today=DAY):
    return route_nonmusical_html_session(
        deepcopy(LEAD if lead is DEFAULT else lead),
        deepcopy(PAGE if page is DEFAULT else page),
        deepcopy(PIN if pin is DEFAULT else pin),
        "/evenement/",
        deepcopy(CONTEXT if context is DEFAULT else context),
        today,
    )


class SourceOnlyNonMusicalRouterTests(unittest.TestCase):
    def assert_safe(self, result):
        self.assertEqual(result["schema"], SCHEMA)
        self.assertIn(result["stage"], STAGES)
        self.assertEqual(result["next_private_review_action"], ACTIONS[result["stage"]])
        self.assertFalse(result["publisher_schema_approved"])
        self.assertFalse(result["can_submit_to_publisher"])
        self.assertFalse(result["rights_reviewed"])
        self.assertFalse(result["approval_granted"])
        self.assertFalse(result["publication_ready"])
        self.assertFalse(result["organizer_independently_attested"])
        self.assertFalse(result["fresh_geo_independently_verified"])
        self.assertFalse(result["live_duplicates_independently_checked"])
        self.assertFalse(result["contains_candidate_fields"])
        self.assertEqual(result["public_writes"], 0)
        self.assertIn("origin_database_and_fact_reuse_policy",
                      result["remaining_independent_checks"])
        blob = json.dumps(result)
        for forbidden in (
            "Albert Camus", ONE, "Montpellier", "09:15",
            "Atelier snoezelen", "43.6", "3.85",
        ):
            self.assertNotIn(forbidden, blob)

    def test_all_source_and_curated_registry_checks_route_to_independent_review(self):
        result = route()
        self.assertEqual(result["stage"], "institutional_source_policy_pending")
        self.assertTrue(result["source_exact_session_confirmed"])
        self.assertTrue(result["source_family_audience_confirmed"])
        self.assertTrue(result["source_access_terms_noncontradictory"])
        self.assertTrue(result["source_only_factual_draft_possible"])
        self.assertEqual(result["venue_registry_status"], "matched")
        self.assertEqual(result["historical_snapshot_status"], "clear")
        self.assert_safe(result)

    def test_two_distinct_hours_are_not_collapsed(self):
        leads = parse_montpellier_mpt_detail(MPT_TEMPLATE, ONE, DAY)
        self.assertEqual(len(leads), 2)
        self.assertEqual([v["start_local"] for v in leads], ["09:15", "10:30"])
        reports = [route(lead=v) for v in leads]
        out = aggregate_html_review_routes(reports)
        self.assertEqual(out["checked"], 2)
        self.assertEqual(
            out["stage_counts"]["institutional_source_policy_pending"], 2)
        self.assertFalse(out["publisher_connected"])
        self.assertEqual(out["public_writes"], 0)

    def test_expired_exact_session_goes_to_archive_not_private_admission(self):
        out = route(today=date(2026, 11, 22))
        self.assertEqual(out["stage"], "session_already_expired")
        self.assertEqual(out["next_private_review_action"],
                         "archive_expired_session_no_publish")
        self.assert_safe(out)

    def test_far_future_exact_session_is_revisited_later(self):
        out = route(today=date(2026, 1, 1))
        self.assertEqual(out["stage"], "session_outside_discovery_horizon")
        self.assertEqual(out["next_private_review_action"],
                         "revisit_when_date_enters_window")
        self.assert_safe(out)

    def test_source_level_policy_cannot_be_bypassed_by_forged_candidate_claim(self):
        forged = dict(LEAD, source_approved=True, legal_rights_reviewed=True,
                      reuse_policy_state="fact_only_source_review_recorded",
                      source_licence="open")
        out = route(lead=forged)
        self.assertEqual(out["stage"], "institutional_source_policy_pending")
        self.assert_safe(out)

    def test_synthetic_source_review_still_requires_event_independent_checks(self):
        from unittest.mock import patch
        from ptitesondes_institutional_source_policy import _out
        with patch("ptitesondes_nonmusical_html_gate_router.committed_source_policy",
                   return_value=_out(
                       "source_fact_only_review_recorded_requires_independent_checks")):
            out = route()
        self.assertEqual(out["stage"], "independent_geo_rights_review_required")
        self.assert_safe(out)

    def test_missing_context_requests_snapshot_before_geo(self):
        out = route(context=None)
        self.assertEqual(out["stage"], "historical_snapshot_unchecked")
        self.assertEqual(out["venue_registry_status"], "not_checked")
        self.assert_safe(out)

    def test_stale_or_future_snapshot_is_not_trusted(self):
        for value in ("2026-11-15", "2026-11-21", "not-a-time", None):
            with self.subTest(value=value):
                context = deepcopy(CONTEXT)
                context["historical_catalogue"]["updated_at"] = value
                out = route(context=context)
                self.assertEqual(out["stage"], "historical_snapshot_unchecked")
                self.assert_safe(out)

    def test_missing_venue_registry_has_specific_next_action(self):
        context = deepcopy(CONTEXT)
        context["legacy_venues"] = []
        out = route(context=context)
        self.assertEqual(out["stage"], "reviewed_venue_missing")
        self.assertEqual(out["next_private_review_action"],
                         "register_independent_venue")
        self.assert_safe(out)

    def test_conflicting_venue_registry_does_not_choose_best_match(self):
        context = deepcopy(CONTEXT)
        context["public_places"].append(deepcopy(VENUE))
        out = route(context=context)
        self.assertEqual(out["stage"], "reviewed_venue_ambiguous")
        self.assert_safe(out)

    def test_suspicious_venue_with_same_source_and_geo_hosts_is_not_trusted(self):
        context = deepcopy(CONTEXT)
        context["legacy_venues"][0]["geo_source"] = (
            "https://mpt.montpellier.fr/maisons/albert-camus")
        out = route(context=context)
        self.assertEqual(out["stage"], "reviewed_venue_untrusted")
        self.assert_safe(out)

    def test_same_title_city_venue_date_and_clock_is_duplicate(self):
        context = deepcopy(CONTEXT)
        context["historical_catalogue"]["events"] = [{
            "title": LEAD["title"], "city": LEAD["city"],
            "venue": LEAD["venue"], "date_start": LEAD["date_start"],
            "date_end": LEAD["date_end"], "time": LEAD["start_local"],
            "source_url": LEAD["source_url"],
        }]
        out = route(context=context)
        self.assertEqual(out["stage"], "historical_duplicate")
        self.assertEqual(out["next_private_review_action"],
                         "do_not_republish_duplicate")
        self.assert_safe(out)

    def test_same_title_same_date_with_different_clock_is_review_not_duplicate(self):
        context = deepcopy(CONTEXT)
        context["historical_catalogue"]["events"] = [{
            "title": LEAD["title"], "city": LEAD["city"],
            "venue": LEAD["venue"], "date_start": LEAD["date_start"],
            "date_end": LEAD["date_end"], "time": "18:15",
            "source_url": LEAD["source_url"],
        }]
        out = route(context=context)
        self.assertEqual(out["stage"], "historical_collision_ambiguous")
        self.assert_safe(out)

    def test_bad_source_or_wrong_clock_blocks_before_context(self):
        cases = (
            (dict(LEAD, start_local="19:15"), PAGE, PIN),
            (dict(LEAD, venue="Maison inventée"), PAGE, PIN),
            (dict(LEAD, source_url="https://evil.example/evenement/x"), PAGE, PIN),
            (LEAD, dict(PAGE, url=ONE + "/redirect"), PIN),
            (LEAD, PAGE, dict(PIN, approved_host="evil.example")),
        )
        for lead, page, pin in cases:
            with self.subTest(lead=lead["source_url"]):
                out = route(lead=lead, page=page, pin=pin)
                self.assertEqual(out["stage"], "session_source_unverified")
                self.assert_safe(out)

    def test_false_verified_flags_from_collector_do_not_override_proof(self):
        forged = dict(LEAD, rights_reviewed=True, verified=True,
                      publisher_connected=True, organizer_independently_attested=True)
        out = route(lead=forged)
        self.assertEqual(out["stage"], "institutional_source_policy_pending")
        self.assert_safe(out)

    def test_missing_audience_cue_can_be_diagnosed(self):
        page = dict(PAGE)
        page["html"] = page["html"].replace(
            "<p>Atelier/Stage | Culture</p><p>Familles</p>",
            "<p>Atelier/Stage | Culture</p><p>Informations</p>",
        ).replace(
            "Partagez ce moment de découverte avec votre bébé et votre famille.",
            "Événement portant sur les livres illustrés.",
        )
        out = route(page=page)
        self.assertEqual(out["stage"], "family_audience_unconfirmed")
        self.assert_safe(out)

    def test_adult_only_event_is_never_candidate_for_family(self):
        page = dict(PAGE)
        page["html"] = page["html"].replace(
            "<p>Familles</p>", "<p>Adultes uniquement</p>",
        )
        out = route(page=page)
        self.assertIn(out["stage"], (
            "session_source_unverified", "family_audience_unconfirmed"))
        self.assert_safe(out)

    def test_conflicting_access_reenters_official_review(self):
        page = dict(PAGE)
        page["html"] = page["html"].replace(
            "<p>Sur inscription | Gratuit</p>",
            "<p>Sur inscription | Sans inscription | Gratuit</p>",
        )
        out = route(page=page)
        self.assertEqual(out["stage"], "access_terms_conflicting")
        self.assert_safe(out)

    def test_oversized_fragment_is_reported_as_source_scan_limit(self):
        page = dict(PAGE)
        page["html"] = page["html"].replace(
            "<p>Sur inscription | Gratuit</p>",
            "<p>" + ("texte " * 900) + "</p><p>Gratuit</p>",
        )
        out = route(page=page)
        self.assertEqual(out["stage"], "source_visible_terms_over_limit")
        self.assert_safe(out)

    def test_musical_and_unknown_categories_never_use_nonmusical_route(self):
        for category in ("concert", "atelier-musical", "unknown", None, []):
            with self.subTest(category=category):
                out = route(lead=dict(LEAD, category=category))
                self.assertEqual(out["stage"], "nonmusical_scope_unrecognized")
                self.assert_safe(out)

    def test_invalid_today_never_processes_untrusted_schedule(self):
        for bad in ("2026-11-20", None, 20261120, True):
            with self.subTest(bad=bad):
                out = route(today=bad)
                self.assertEqual(out["stage"], "historical_snapshot_unchecked")
                self.assert_safe(out)


class PublicAggregateSafetyTests(unittest.TestCase):
    def test_only_stable_categorical_counts_are_emitted(self):
        reports = [route(), route(context=None), route()]
        summary = aggregate_html_review_routes(reports)
        self.assertEqual(summary["checked"], 3)
        self.assertEqual(summary["stage_counts"]["institutional_source_policy_pending"], 2)
        self.assertEqual(summary["stage_counts"]["historical_snapshot_unchecked"], 1)
        self.assertEqual(sum(summary["stage_counts"].values()), 3)
        self.assertFalse(summary["publication_ready"])
        self.assertFalse(summary["candidate_identifiers_present"])
        self.assertNotIn("Montpellier", json.dumps(summary))
        self.assertNotIn(ONE, json.dumps(summary))

    def test_refuse_forged_or_candidate_leaking_reports(self):
        good = route()
        cases = (
            dict(good, approval_granted=True),
            dict(good, public_writes=1),
            dict(good, stage="public_approved"),
            dict(good, source_url=ONE),
            dict(good, candidate_fields={"city": "Montpellier"}),
            dict(good, contains_candidate_fields=True),
            dict(good, source_family_audience_confirmed="true"),
            dict(good, remaining_independent_checks=[]),
        )
        for report in cases:
            with self.subTest(keys=list(report)), self.assertRaises(ValueError):
                aggregate_html_review_routes([report])

    def test_overlong_batches_refused(self):
        with self.assertRaises(ValueError):
            aggregate_html_review_routes([route()] * 101)
        with self.assertRaises(ValueError):
            aggregate_html_review_routes({})


if __name__ == "__main__":
    unittest.main()
