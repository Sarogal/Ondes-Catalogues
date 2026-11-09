"""Offline private metrics regression tests: sources and publication counts."""
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import intake_metrics as m


class PrivateMetricsTests(unittest.TestCase):
    def test_sources_and_private_counts_are_separated(self):
        discovery = {"schema": "grossesondes.concert.discovery.v1",
                     "catalogue": {"events": 353},
                     "venueChecks": [
                         {"venue": "A", "adapterDiagnostic": {
                             "detailPagesRead": 3, "detailErrors": 1}},
                         {"venue": "B", "error": "robots.txt indisponible"},
                         {"venue": "C", "error": "timeout"},
                     ], "partnerChecks": [],
                     "candidates": [{"candidateId": "x"}]}
        tours = {"schema": "grossesondes.concert.discovery.v1",
                 "sourceChecks": [{"artistId": "band",
                                   "status": "fetched",
                                   "candidateCount": 2}],
                 "candidates": [{}, {}]}
        registry = {"schema": "grossesondes.concert.intake.v1", "items": {
            "a": {"status": "pending_review", "stableObservations": 2},
            "b": {"status": "pending_review", "stableObservations": 1},
            "c": {"status": "rejected", "stableObservations": 9},
        }}
        official = {"results": [{"status": "held"}], "evaluated": 1,
                    "held": [{"status": "held"}], "expiredSkipped": 2,
                    "newApprovals": ["proposed"]}
        watch = {"checked": 24, "needsReview": [{"id": "past"}]}
        report = m.build(discovery, tours, registry, official, watch,
                         [{"added": 1, "seenAgain": 2},
                          {"added": 2, "seenAgain": 1}], "2026-11-09")
        self.assertEqual(report["venueSourcesFetched"], 1)
        self.assertEqual(report["venueSourcesRobotsDeniedOrUnavailable"], 1)
        self.assertEqual(report["venueSourcesOtherErrors"], 1)
        self.assertEqual(report["tourSources"][0]["candidateCount"], 2)
        self.assertEqual(report["newPrivateCandidates"], 3)
        self.assertEqual(report["privatePending"], 2)
        self.assertEqual(report["privateEligibleStable"], 1)
        self.assertEqual(report["privateDecided"], 1)
        self.assertEqual(report["approvalsProposed"], 1)
        self.assertEqual(report["publishedWatchAnomalies"], 1)
        self.assertEqual(report["actuallyPublishedByThisIntake"], 0)
        self.assertNotIn("https://", str(report))

    def test_rejects_broken_or_missing_source_payload(self):
        with self.assertRaises(ValueError):
            m.build({"schema": "other"}, {}, {}, {}, {}, [], "2026-11-09")


if __name__ == "__main__":
    unittest.main()
