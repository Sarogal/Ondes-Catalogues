"""Offline adversarial checks for the read-only full-sweep auditor."""
from datetime import date
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_full_candidate_audit import full_audit, public_summary


TODAY = date(2026, 11, 12)


def lead(uid, collector="opendatasoft-index"):
    return {"external_id": str(uid), "date_start": "2027-01-12",
            "collector": collector, "source_url": "https://openagenda.com/private/events/x"}


def fixtures():
    leads = [lead(1), lead(1, "openagenda-v2"), lead(2), lead(3)]
    candidates = [lead(1), lead(2), lead(3)]
    baseline = {"events": []}
    published = {"events": [{"id": "original"}],
                 "updated_at": "2026-11-12T20:30:28+01:00"}
    return leads, candidates, baseline, published


class FullAuditTests(unittest.TestCase):
    def test_all_batches_and_alternatives_and_redacted_public_summary(self):
        leads, candidates, baseline, published = fixtures()
        calls = []

        def review(batch, unused_baseline, unused_published, today, limit, slot):
            calls.append((batch, limit, slot))
            n = len({x["external_id"] for x in batch})
            return ({"safe_to_publish": False,
                     "additions": [{"id": "preflight"}]},
                    {"eligible_with_reviewed_venue": n, "checked": n,
                     "date": str(today), "mode": "preview_no_public_write",
                     "accepted_preflight": 1, "deferred_or_duplicates": n - 1,
                     "details": [{"status": "unverified",
                                  "reason": "public enfant non confirmé",
                                  "source_url": "https://secret.example/"}]
                                * (n - 1)})
        with patch("ptitesondes_full_candidate_audit.unique_review_candidates",
                   return_value=(candidates, 4, 1, 0)), patch(
                   "ptitesondes_full_candidate_audit.permitted",
                   return_value=True), patch(
                   "ptitesondes_full_candidate_audit.MAX_FETCH", 2), patch(
                   "ptitesondes_full_candidate_audit.private_admission_diagnostics",
                   return_value={"top_unverified_venues": [
                       {"venue": "private venue"}]}):
            report = full_audit(leads, baseline, published, TODAY, review=review)
        self.assertEqual(report["unique_admissible"], 3)
        self.assertEqual(report["checked"], 3)
        self.assertEqual(report["accepted_preflight_decisions"], 2)
        self.assertEqual(report["rejected_decisions"], 1)
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(calls[0][0]), 3)  # first UID has both mirrors
        self.assertEqual(report["public_writes"], 0)
        public = json.dumps(public_summary(report))
        for forbidden in ("private", "venue", "reason_groups", "source_url",
                          "http", "accepted_preflight_decisionsX"):
            self.assertNotIn(forbidden, public)

    def test_wrong_checked_count_fails_closed(self):
        leads, candidates, baseline, published = fixtures()

        def incomplete(batch, *args, **kwargs):
            return ({"safe_to_publish": False, "additions": []},
                    {"eligible_with_reviewed_venue": 3, "checked": 2,
                     "date": str(TODAY), "mode": "preview_no_public_write",
                     "accepted_preflight": 0, "deferred_or_duplicates": 0,
                     "details": []})
        with patch("ptitesondes_full_candidate_audit.unique_review_candidates",
                   return_value=(candidates, 4, 1, 0)), patch(
                   "ptitesondes_full_candidate_audit.permitted",
                   return_value=True):
            with self.assertRaises(ValueError):
                full_audit(leads, baseline, published, TODAY, review=incomplete)

    def test_unbounded_candidates_refused_before_network(self):
        leads, _, baseline, published = fixtures()
        candidates = [lead(x) for x in range(201)]
        with patch("ptitesondes_full_candidate_audit.unique_review_candidates",
                   return_value=(candidates, 201, 0, 0)):
            with self.assertRaisesRegex(ValueError, "volumineux"):
                full_audit(leads, baseline, published, TODAY)

    def test_public_summary_requires_approved_schema(self):
        with self.assertRaises(ValueError):
            public_summary({"schema": "other", "checked": 3})

    def test_public_summary_drops_private_strings_and_injected_counts(self):
        source = {"schema": "ptitesondes.private_full_candidate_audit.v1",
                  "checked": 7, "raw_eligible": True,
                  "source_url": "https://private.example/",
                  "reason_groups": {"some secret": 2}}
        shown = public_summary(source)
        self.assertEqual(shown, {"checked": 7})
        self.assertNotIn("raw_eligible", shown)


if __name__ == "__main__":
    unittest.main()
