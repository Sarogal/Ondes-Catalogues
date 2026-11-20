"""Offline adversarial suite for proposed family categories: NO publishing."""
from copy import deepcopy
from datetime import date, datetime
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from ptitesondes_family_national_scope import (
    SCHEMA, FAMILY_TYPES, LEGACY_MUSICAL, audit_family_scope,
)

TODAY = date(2026, 11, 17)


def event(category="lecture-jeunesse", **changes):
    row = {
        "record_kind": "dated_event",
        "category": category,
        "category_label": FAMILY_TYPES[category][0],
        "title": "Activité familiale fictive et documentée",
        "city": "Le Gosier",
        "venue": "Lieu fictif pour test",
        "source_url": "https://example.org/agenda/animation",
        "date_start": "2026-11-18",
        "date_end": "2026-11-18",
        "audience_claim": "explicit_child",
        "age_min": 5,
        "age_max": 12,
        "price_evidence": "not_stated",
        "registration_evidence": "not_stated",
    }
    row.update(changes)
    return row


def venue(**changes):
    row = event()
    row.update({
        "record_kind": "permanent_place",
        "category": None, "category_label": None,
        "date_start": None, "date_end": None,
        "audience_claim": "explicit_family",
        "age_min": None, "age_max": None,
    })
    row.update(changes)
    return row


class NationalFamilyScopeTests(unittest.TestCase):
    def test_historical_four_categories_keep_exact_ids_and_labels(self):
        four = {
            "lecture-jeunesse": "Lecture jeunesse",
            "atelier-numerique": "Atelier numérique",
            "lecture-cinema": "Lecture et cinéma",
            "jeux-famille": "Jeux en famille",
        }
        for slug, label in four.items():
            self.assertEqual(FAMILY_TYPES[slug][0], label)
        self.assertEqual(len(FAMILY_TYPES), 13)
        self.assertEqual(len(set(FAMILY_TYPES)), len(FAMILY_TYPES))
        self.assertFalse(set(FAMILY_TYPES) & LEGACY_MUSICAL)

    def test_general_taxonomy_remains_but_only_two_radio_adjacent_types_pass(self):
        rows = [event(slug) for slug in FAMILY_TYPES]
        before = deepcopy(rows)
        with patch("merge_policy.merge", side_effect=AssertionError(
            "publisher called"
        )):
            out = audit_family_scope(rows, TODAY)
        self.assertEqual(rows, before)
        self.assertEqual(out["schema"], SCHEMA)
        self.assertEqual(out["structurally_plausible_for_independent_review"], 2)
        self.assertEqual(out["rejected_scope_items"], 11)
        self.assertEqual(out["proposed_category_counts"], {
            "lecture-jeunesse": 1, "spectacle-jeunesse": 1})
        self.assertEqual(out["proposed_routes"], {"sorties": 2})
        self.assertEqual(out["blocked_reason_counts"], {
            "outside_radio_editorial_scope": 11})
        self.assertFalse(out["publication_ready"])
        self.assertFalse(out["approval_granted_to_publisher"])
        self.assertEqual(out["public_writes"], 0)

    def test_no_municipal_city_lock_for_mainland_corsica_and_overseas(self):
        # Geographic claims remain unverified; this only tests that the
        # general editorial taxonomy is not accidentally restricted to Gosier.
        cities = (
            "Montpellier", "Ajaccio", "Le Gosier", "Fort-de-France",
            "Cayenne", "Saint-Denis", "Mamoudzou",
        )
        out = audit_family_scope([event(city=city) for city in cities], TODAY)
        self.assertEqual(out["structurally_plausible_for_independent_review"], 7)
        self.assertTrue(out["geographic_provenance_not_verified"])
        self.assertEqual(out["public_writes"], 0)

    def test_permanent_place_routes_only_to_lieux(self):
        out = audit_family_scope([venue()], TODAY)
        self.assertEqual(out["proposed_routes"], {"lieux": 1})
        self.assertEqual(out["proposed_category_counts"], {})
        self.assertEqual(out["public_writes"], 0)

    def test_dated_event_at_permanent_place_remains_an_event(self):
        item = event("lecture-jeunesse", venue="Musée pour enfants")
        out = audit_family_scope([item], TODAY)
        self.assertEqual(out["proposed_routes"], {"sorties": 1})

    def test_fake_permanent_event_with_date_or_category_refused(self):
        for modified in ({"date_start": "2026-11-18"},
                         {"category": "lecture-jeunesse"},
                         {"category_label": "Lecture jeunesse"},
                         {"date_end": "2026-11-18"}):
            with self.subTest(modified=modified):
                out = audit_family_scope([venue(**modified)], TODAY)
                self.assertEqual(out["structurally_plausible_for_independent_review"], 0)
                self.assertIn("permanent_place_must_not_be_dated_outing",
                              out["blocked_reason_counts"])

    def test_no_automatic_legacy_musical_reclassification(self):
        for music in LEGACY_MUSICAL:
            with self.subTest(music=music):
                row = event()
                row["category"] = music
                row["category_label"] = music
                out = audit_family_scope([row], TODAY)
                self.assertEqual(out["rejected_scope_items"], 1)
                self.assertIn("legacy_musical_pipeline_unchanged",
                              out["blocked_reason_counts"])

    def test_category_is_not_inferred_from_friendly_title(self):
        out = audit_family_scope([event(category="sortie-nature",
            title="Atelier de dessin pour enfants")], TODAY)
        self.assertEqual(out["proposed_category_counts"], {})
        self.assertIn("outside_radio_editorial_scope",
                      out["blocked_reason_counts"])
        # This is *only* the declared category, not source-level validation.
        self.assertTrue(out["source_officiality_and_age_not_verified"])

    def test_unknown_categories_or_wrong_labels_are_not_auto_admitted(self):
        for modification in ({"category": "unverified-new-type"},
                             {"category": None}, {"category": ["bad"]},
                             {"category_label": "Autre intitulé"}):
            with self.subTest(modification=modification):
                row = event()
                row.update(modification)
                out = audit_family_scope([row], TODAY)
                self.assertEqual(out["structurally_plausible_for_independent_review"], 0)

    def test_age_must_be_explicit_claim_with_non_invented_numeric_bounds(self):
        for change in ({"audience_claim": None},
                       {"audience_claim": "everyone"},
                       {"audience_claim": ["explicit_child"]},
                       {"age_min": -1}, {"age_max": 18},
                       {"age_min": 9, "age_max": 5},
                       {"age_min": True}, {"age_max": 5.5}):
            with self.subTest(change=change):
                out = audit_family_scope([event(**change)], TODAY)
                self.assertIn("explicit_family_audience_claim_missing_or_invalid",
                              out["blocked_reason_counts"])

    def test_explicit_family_without_age_may_be_reviewed_but_not_proved(self):
        out = audit_family_scope([event(audience_claim="explicit_family",
                                        age_min=None, age_max=None)], TODAY)
        self.assertEqual(out["structurally_plausible_for_independent_review"], 1)
        self.assertTrue(out["source_officiality_and_age_not_verified"])

    def test_https_url_is_only_shape_check_not_official_proof(self):
        out = audit_family_scope([event(source_url="https://aggregator.example/event")], TODAY)
        self.assertEqual(out["structurally_plausible_for_independent_review"], 1)
        self.assertTrue(out["scope_is_not_source_evidence"])
        self.assertTrue(out["source_officiality_and_age_not_verified"])

    def test_unsafe_urls_refused(self):
        for url in ("http://organizer.example/e", "javascript:alert(1)",
                    "https://user:secret@example.org/e",
                    "https://example.org/path#forged", "https://",
                    42, ["https://example.org"]):
            with self.subTest(url=url):
                out = audit_family_scope([event(source_url=url)], TODAY)
                self.assertIn("source_url_shape_unverified",
                              out["blocked_reason_counts"])

    def test_expired_inverted_invalid_session_rejected(self):
        for times in ({"date_start": "2026-11-01", "date_end": "2026-11-01"},
                      {"date_start": "2026-11-19", "date_end": "2026-11-18"},
                      {"date_start": "2026-11-31"},
                      {"date_end": None},
                      {"date_start": "tomorrow"}):
            with self.subTest(times=times):
                out = audit_family_scope([event(**times)], TODAY)
                self.assertIn("dated_occurrence_unverified_or_expired",
                              out["blocked_reason_counts"])

    def test_event_spanning_today_can_be_proposed_without_recurrence(self):
        out = audit_family_scope([event(date_start="2026-11-10",
                                      date_end="2026-11-18")], TODAY)
        self.assertEqual(out["proposed_routes"], {"sorties": 1})
        self.assertTrue(out["recurrences_not_inferred"])

    def test_price_unknown_never_rewritten_as_free_or_no_registration(self):
        out = audit_family_scope([event(price_evidence="not_stated",
              registration_evidence="not_stated")], TODAY)
        self.assertEqual(out["structurally_plausible_for_independent_review"], 1)
        self.assertTrue(out["price_or_registration_not_inferred"])
        self.assertNotIn("price", out)
        self.assertNotIn("registration", out)
        self.assertFalse(out["publication_ready"])

    def test_conflicting_or_invalid_access_claims_never_grant_release(self):
        for variation in ({"price_evidence": "ambiguous"},
                          {"price_evidence": "contradictory"},
                          {"registration_evidence": "contradictory"}):
            out = audit_family_scope([event(**variation)], TODAY)
            self.assertFalse(out["publication_ready"])
            self.assertEqual(out["public_writes"], 0)
        for variation in ({"price_evidence": "automatic_free"},
                          {"registration_evidence": []}):
            out = audit_family_scope([event(**variation)], TODAY)
            self.assertIn("access_evidence_state_missing_or_invalid",
                          out["blocked_reason_counts"])

    def test_collector_cannot_inject_approval_or_recurrence(self):
        for variation in ({"safe_to_publish": True}, {"approved": True},
                          {"repeat_weekly": True}, {"additions": []}):
            with self.subTest(variation=variation):
                out = audit_family_scope([event(**variation)], TODAY)
                self.assertIn("unexpected_collector_field", out["blocked_reason_counts"])

    def test_missing_venue_or_unrecognized_record_kind(self):
        for variation in ({"venue": ""}, {"city": None}, {"title": " "},
                          {"record_kind": "online-only"},
                          {"record_kind": ["dated_event"]}):
            out = audit_family_scope([event(**variation)], TODAY)
            self.assertEqual(out["structurally_plausible_for_independent_review"], 0)

    def test_single_bad_candidate_blocks_itself_and_never_partially_publishes(self):
        rows = [event("spectacle-jeunesse"),
                event("fete-familiale", source_url="http://bad.example")]
        out = audit_family_scope(rows, TODAY)
        self.assertEqual(out["structurally_plausible_for_independent_review"], 1)
        self.assertEqual(out["rejected_scope_items"], 1)
        self.assertEqual(out["public_writes"], 0)
        self.assertFalse(out["approval_granted_to_publisher"])

    def test_never_return_event_ids_private_sources_or_publishable_patch(self):
        out = audit_family_scope([event(title="Private child event")], TODAY)
        forbidden = ("events", "additions", "patch", "patch.v1",
                     "catalogue", "source_url", "review_id", "candidates")
        self.assertTrue(all(field not in out for field in forbidden))
        self.assertNotIn("Private child event", json.dumps(out))
        self.assertNotIn("https://example.org", json.dumps(out))

    def test_original_json_categories_preserved_without_mutation(self):
        document = json.loads((ROOT / "docs/ptitesondes/sorties.json").read_text(encoding="utf-8"))
        original = deepcopy(document)
        known = {row["category"] for row in document["events"]}
        self.assertEqual(known, LEGACY_MUSICAL)
        self.assertFalse(known & set(FAMILY_TYPES))
        audit_family_scope([event()], TODAY)
        self.assertEqual(original, document)

    def test_empty_or_oversize_batch_rejected(self):
        for batch in ([], [event()] * 101, None, {}):
            with self.subTest(batch=type(batch).__name__):
                with self.assertRaisesRegex(ValueError, "invalid_scope_batch"):
                    audit_family_scope(batch, TODAY)

    def test_invalid_day_or_malformed_row_handled_safely(self):
        with self.assertRaisesRegex(ValueError, "invalid_scope_day"):
            audit_family_scope([event()], datetime(2026, 11, 17))
        out = audit_family_scope([None, "sneaky", 42], TODAY)
        self.assertEqual(out["rejected_scope_items"], 3)
        self.assertIn("invalid_scope_item", out["blocked_reason_counts"])


if __name__ == "__main__":
    unittest.main()
