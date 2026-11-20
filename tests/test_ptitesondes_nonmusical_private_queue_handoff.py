"""Offline tests for the PRIVATE queue; synthetic URLs only."""
from datetime import date
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_nonmusical_private_queue_handoff import (
    SCHEMA, reconcile_private_html_review_queue,
)


def packet():
    # A trusted caller must supply actual pinned evidence; these tests mock
    # the existing independent router and facts, NOT any publication token.
    return {
        "lead": {"untrusted_approved": True}, "page": {},
        "trusted_index": {}, "child_prefix": "/evenement/",
        "independent_context": {},
    }


def proven(stage="institutional_source_policy_pending",
           source="https://example.org/evenement/atelier",
           time="10:00"):
    route = {
        "stage": stage, "source_exact_session_confirmed": True,
        "source_only_factual_draft_possible": True,
        "can_submit_to_publisher": False, "publication_ready": False,
    }
    draft = {
        "status": "private_draft_for_rights_review",
        "draft": {
            "source_url": source, "source_title_identity_only": "Atelier famille",
            "city": "Montpellier", "venue": "Maison culturelle",
            "category": "atelier-creatif", "date_start": "2026-11-22",
            "start_local": time, "safe_to_publish": False,
        },
    }
    return route, draft


class PrivateQueueTests(unittest.TestCase):
    day = date(2026, 11, 20)

    def run_batch(self, rows, existing=None, stage="institutional_source_policy_pending",
                  source="https://example.org/evenement/atelier", time="10:00"):
        route, facts = proven(stage, source, time)
        with patch("ptitesondes_nonmusical_private_queue_handoff.route_nonmusical_html_session",
                   return_value=route) as verify, patch(
            "ptitesondes_nonmusical_private_queue_handoff.prepare_private_html_factual_draft",
            return_value=facts) as factual:
            result = reconcile_private_html_review_queue(
                [] if existing is None else existing, rows, self.day)
            self.assertEqual(verify.call_count, len(rows))
            self.assertEqual(factual.call_count, len(rows))
            return result

    def test_new_session_is_private_only_and_has_provenance(self):
        result = self.run_batch([packet()])
        row = result["queue"][0]
        self.assertEqual(result["report"]["new_private_reviews"], 1)
        self.assertEqual(row["schema"], SCHEMA)
        self.assertEqual(row["source_url"], "https://example.org/evenement/atelier")
        self.assertEqual(row["start_local"], "10:00")
        self.assertEqual(row["reason_code"], "institutional_source_policy_pending")
        self.assertIsNone(row["next_retry_on"])
        self.assertEqual((row["safe_to_publish"], row["approved"], row["published"]),
                         (False, False, False))
        self.assertEqual(result["report"]["public_writes"], 0)
        self.assertNotIn("source_url", result["report"])
        self.assertNotIn("queue", result["report"])

    def test_idempotent_against_private_queue(self):
        a = self.run_batch([packet()])["queue"]
        b = self.run_batch([packet()], existing=a)
        self.assertEqual(len(b["queue"]), 1)
        self.assertEqual(b["queue"][0]["review_id"], a[0]["review_id"])
        self.assertEqual(b["queue"][0]["observations"], 2)
        self.assertEqual(b["report"]["new_private_reviews"], 0)
        self.assertEqual(b["report"]["rechecked_private_reviews"], 1)

    def test_different_exact_clock_does_not_collapse(self):
        a = self.run_batch([packet()])["queue"]
        b = self.run_batch([packet()], existing=a, time="14:30")
        self.assertEqual(len(b["queue"]), 2)
        self.assertEqual({r["start_local"] for r in b["queue"]},
                         {"10:00", "14:30"})

    def test_cross_source_collision_is_only_flagged(self):
        a = self.run_batch([packet()])["queue"]
        b = self.run_batch([packet()], existing=a,
                           source="https://official.example.org/autre-agenda")
        self.assertEqual(len(b["queue"]), 2)
        self.assertEqual(b["report"]["possible_cross_source_same_session"], 2)

    def test_retryable_registry_issue_has_date(self):
        r = self.run_batch([packet()], stage="reviewed_venue_unchecked")
        self.assertEqual(r["queue"][0]["next_retry_on"], "2026-11-22")
        self.assertEqual(r["queue"][0]["review_class"], "retryable")

    def test_old_dossier_survives_when_source_unavailable(self):
        original = self.run_batch([packet()])["queue"]
        bad = {"stage": "session_source_unverified"}
        with patch("ptitesondes_nonmusical_private_queue_handoff.route_nonmusical_html_session",
                   return_value=bad):
            r = reconcile_private_html_review_queue(
                original, [packet()], self.day)
        self.assertEqual(r["queue"], original)
        self.assertEqual(r["report"]["held_without_exact_review_facts"], 1)
        self.assertEqual(r["report"]["retained_unseen_private_reviews"], 1)

    def test_forged_collector_approval_cannot_unlock_anything(self):
        r = self.run_batch([packet()])
        row = dict(r["queue"][0])
        row["approved"] = True
        with self.assertRaisesRegex(ValueError, "invalid_private_html"):
            reconcile_private_html_review_queue([row], [], self.day)
        self.assertEqual(r["report"]["catalogue_additions"], 0)

    def test_invalid_existing_queue_and_duplicates_fail_closed(self):
        row = self.run_batch([packet()])["queue"][0]
        with self.assertRaisesRegex(ValueError, "duplicate_private"):
            reconcile_private_html_review_queue([row, row], [], self.day)
        with self.assertRaisesRegex(ValueError, "invalid_private"):
            reconcile_private_html_review_queue(
                [{"source_url": "https://example.org"}], [], self.day)

    def test_malformed_and_unproved_packets_are_not_persisted(self):
        x = reconcile_private_html_review_queue([], [{"untrusted": True}], self.day)
        self.assertEqual(x["report"]["malformed_packets_held"], 1)
        self.assertEqual(x["queue"], [])
        # Even a synthetic draft cannot be accepted without the router's
        # source and audience corroboration flags.
        route, facts = proven()
        route["source_exact_session_confirmed"] = False
        with patch("ptitesondes_nonmusical_private_queue_handoff.route_nonmusical_html_session",
                   return_value=route), patch(
            "ptitesondes_nonmusical_private_queue_handoff.prepare_private_html_factual_draft",
            return_value=facts) as factual:
            x = reconcile_private_html_review_queue([], [packet()], self.day)
            factual.assert_not_called()
        self.assertEqual(x["queue"], [])
        self.assertEqual(x["report"]["held_without_exact_review_facts"], 1)

    def test_private_records_are_not_mutated(self):
        row = self.run_batch([packet()])["queue"][0]
        old = dict(row)
        self.run_batch([packet()], existing=[row])
        self.assertEqual(row, old)


if __name__ == "__main__":
    unittest.main()
