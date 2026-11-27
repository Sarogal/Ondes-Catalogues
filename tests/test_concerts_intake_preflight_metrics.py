"""Keep all-lane approval metrics distinct from actual publication."""
import unittest
from automation.concerts.intake_metrics import describe_preflight, build


class PreflightMetricsTests(unittest.TestCase):
    def test_real_dynamic_approval_with_zero_legacy_proposals(self):
        report = dict(status="validated", proposedApprovals=1, newApprovals=1,
                      publishableEvents=1, rejectedCount=0,
                      validatedByPublisher=True, applied=True)
        discovery = dict(schema="grossesondes.concert.discovery.v1", candidates=[])
        registry = dict(schema="grossesondes.concert.intake.v1", items={})
        metrics = build(discovery, discovery, registry,
                        {"results": [], "newApprovals": []},
                        {"needsReview": []}, [], "2026-11-27T07:23:37Z",
                        preflight=report)
        self.assertEqual(metrics["approvalsProposed"], 0)
        self.assertEqual(metrics["publisherProposals"], 1)
        self.assertEqual(metrics["publisherValidatedApprovals"], 1)
        self.assertEqual(metrics["publisherAppliedApprovals"], 1)
        self.assertEqual(metrics["actuallyPublishedByThisIntake"], 0)

    def test_preview_partial_and_no_changes(self):
        report = dict(status="partially_validated", proposedApprovals=3,
                      newApprovals=2, publishableEvents=2, rejectedCount=1,
                      validatedByPublisher=True, applied=False)
        metrics = describe_preflight(report)
        self.assertEqual(metrics["publisherProposals"], 3)
        self.assertEqual(metrics["publisherValidatedApprovals"], 2)
        self.assertEqual(metrics["publisherAppliedApprovals"], 0)
        self.assertEqual(metrics["publisherRejectedProposals"], 1)
        zero = describe_preflight(dict(status="no_changes", proposedApprovals=0,
            newApprovals=0, publishableEvents=0, rejectedCount=0,
            validatedByPublisher=False, applied=False))
        self.assertEqual(zero["publisherProposals"], 0)
        self.assertEqual(zero["publisherAppliedApprovals"], 0)

    def test_blocked_missing_or_invalid_never_claim_publication(self):
        blocked = describe_preflight(dict(status="blocked",
                         applied=False, validatedByPublisher=False,
                         reason="private detail", rejected=[{"url": "private"}]))
        self.assertEqual(blocked["publisherPreflightStatus"], "blocked")
        self.assertIsNone(blocked["publisherProposals"])
        self.assertEqual(blocked["publisherAppliedApprovals"], 0)
        self.assertNotIn("reason", blocked)
        for report in (None, [], {"status": "validated"},
                       dict(status="validated", proposedApprovals=1,
                            newApprovals=2, publishableEvents=2, rejectedCount=0,
                            validatedByPublisher=True, applied=True)):
            self.assertIsNone(describe_preflight(report)["publisherAppliedApprovals"])


if __name__ == "__main__":
    unittest.main()
