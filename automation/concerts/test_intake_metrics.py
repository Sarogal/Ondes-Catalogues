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
                             "detailPagesRead": 3, "detailErrors": 1},
                          "pagesChecked": 4, "eventDetailLinksFound": 54,
                          "eventDetailPagesFetched": 3,
                          "htmlVisibleBillLeads": 2,
                          "candidatesDetected": 2},
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
        self.assertEqual(report["venueSources"][0]["pagesChecked"], 4)
        self.assertEqual(report["venueSources"][0]["eventDetailLinksFound"], 54)
        self.assertEqual(report["venueSources"][0]["eventDetailPagesFetched"], 3)
        self.assertEqual(report["venueSources"][0]["htmlVisibleBillLeads"], 2)
        self.assertEqual(report["venueHtmlVisibleBillLeads"], 2)
        self.assertEqual(report["venueEventDetailPagesFetched"], 3)
        self.assertEqual(report["venueEventLinksDiscovered"], 54)
        self.assertEqual(report["tourSources"][0]["candidateCount"], 2)
        self.assertEqual(report["newPrivateCandidates"], 3)
        self.assertEqual(report["privatePending"], 2)
        self.assertEqual(report["privateEligibleStable"], 1)
        self.assertEqual(report["privateDecided"], 1)
        self.assertEqual(report["approvalsProposed"], 1)
        self.assertEqual(report["publishedWatchAnomalies"], 1)
        self.assertEqual(report["actuallyPublishedByThisIntake"], 0)
        self.assertNotIn("https://", str(report))

    def test_organizer_counts_are_private_and_all_three_archives_count(self):
        discovery = {"schema": "grossesondes.concert.discovery.v1",
                     "catalogue": {"events": 378},
                     "venueChecks": [], "partnerChecks": [], "candidates": []}
        tours = {"schema": "grossesondes.concert.discovery.v1",
                 "sourceChecks": [], "candidates": []}
        organizers = {"schema": "grossesondes.concert.discovery.v1",
                      "candidates": [{"candidateId": "secret-new-band"}],
                      "sourceChecks": [
                          {"organizerSourceId": "reviewed-source",
                           "status": "read", "listingPageFetched": True,
                           "eventDetailLinks": 12,
                           "individualPagesRead": 6,
                           "individualPagesHeld": 2, "candidateCount": 1,
                           "url": "https://secret.example/agenda/"},
                          {"organizerSourceId": "failed-source",
                           "status": "held_source_unavailable",
                           "individualPagesRead": True,
                           "candidateCount": -3}]}
        registry = {"schema": "grossesondes.concert.intake.v1", "items": {}}
        official = {"results": [], "held": [], "newApprovals": []}
        watch = {"needsReview": []}
        report = m.build(discovery, tours, registry, official, watch,
                         [{"added": 1}, {"added": 2}, {"added": 1}],
                         "2026-11-20", organizers=organizers)
        self.assertEqual(report["organizerDiscoveriesThisRun"], 1)
        self.assertEqual(report["organizerSourcesFetched"], 1)
        self.assertEqual(report["organizerSourcesHeld"], 1)
        self.assertEqual(report["organizerDetailPagesRead"], 6)
        self.assertEqual(report["organizerDetailPagesHeld"], 2)
        self.assertEqual(report["newPrivateCandidates"], 4)
        self.assertEqual(report["organizerSources"][1]["individualPagesRead"], 0)
        self.assertNotIn("https://", str(report))
        self.assertNotIn("secret-new-band", str(report))
        with self.assertRaises(ValueError):
            m.build(discovery, tours, registry, official, watch, [],
                    "2026-11-20", organizers={"schema": "invalid"})

    def test_invalid_or_untrusted_counts_cannot_escape_into_metrics(self):
        a = m.describe_venue({
            "venue": "La Rayonne",
            "pagesChecked": True, "eventDetailLinksFound": -1,
            "eventDetailPagesFetched": "secret count",
            "htmlVisibleBillLeads": 100001,
            "candidatesDetected": None,
            "adapterDiagnostic": {"detailPagesRead": "bad"},
        })
        self.assertEqual(a["pagesChecked"], 0)
        self.assertEqual(a["eventDetailLinksFound"], 0)
        self.assertEqual(a["eventDetailPagesFetched"], 0)
        self.assertEqual(a["htmlVisibleBillLeads"], 0)
        self.assertEqual(a["detailsRead"], 0)
        self.assertEqual(a["candidatesDetected"], 0)
        self.assertNotIn("url", a)
        self.assertNotIn("artist", str(a))


    def test_osm_discovery_yield_is_private_and_cannot_approve(self):
        venues = {"schema": "grossesondes.concert.discovery.v1",
                  "catalogue": {"events": 379}, "venueChecks": [],
                  "partnerChecks": [], "candidates": []}
        tours = {"schema": "grossesondes.concert.discovery.v1",
                 "sourceChecks": [], "candidates": []}
        registry = {"schema": "grossesondes.concert.intake.v1",
                    "items": {"a": {"status": "pending_review"}}}
        osm = {"schema": "grossesondes.concert.discovery.v1",
               "publicationAllowed": False, "automaticPublication": False,
               "eligiblePhysicalVenues": 88,
               "sourceChecks": {"roomsConsidered": 5,
                                "namedOsmWebsitesVerified": 2,
                                "individualDetailsQueued": 11,
                                "detailPagesRead": 4,
                                "sourcesHeld": 3,
                                "untrustedUrl": "https://private.example/"},
               "triageCounts": {"genre_tag_review": 1},
               "candidates": [{"candidateId": "private-unpublished",
                               "sourceUrl": "https://secret.example/event",
                               "publicationAllowed": False,
                               "reviewRequired": True}]}
        kwargs = dict(osm_venues=osm,
                      osm_archive={"added": 1, "seenAgain": 2})
        report = m.build(venues, tours, registry,
                         {"results": [], "newApprovals": []},
                         {"needsReview": []}, [{"added": 2, "seenAgain": 3}],
                         "2026-11-21", **kwargs)
        self.assertEqual(report["osmEligibleVenues"], 88)
        self.assertEqual(report["osmSitesVerified"], 2)
        self.assertEqual(report["osmRoomsConsidered"], 5)
        self.assertEqual(report["osmDetailPagesQueued"], 11)
        self.assertEqual(report["osmDetailPagesRead"], 4)
        self.assertEqual(report["osmHeldSources"], 3)
        self.assertEqual(report["osmDiscoveryCandidates"], 1)
        self.assertEqual(report["osmNewPrivateCandidates"], 1)
        self.assertEqual(report["newPrivateCandidates"], 3)
        self.assertEqual(report["rediscoveredPrivateCandidates"], 5)
        self.assertEqual(report["actuallyPublishedByThisIntake"], 0)
        self.assertNotIn("https://", str(report))
        self.assertNotIn("private-unpublished", str(report))
        osm["sourceChecks"]["roomsConsidered"] = True
        self.assertEqual(m.describe_osm(osm, {"added": True})[
            "osmRoomsConsidered"], 0)
        self.assertEqual(m.describe_osm(osm, {"added": True})[
            "osmNewPrivateCandidates"], 0)
        osm["candidates"][0]["publicationAllowed"] = True
        with self.assertRaises(ValueError):
            m.describe_osm(osm, {"added": 1})
        with self.assertRaises(ValueError):
            m.describe_osm(None, {"added": 1})

    def test_rejects_broken_or_missing_source_payload(self):
        with self.assertRaises(ValueError):
            m.build({"schema": "other"}, {}, {}, {}, {}, [], "2026-11-09")


if __name__ == "__main__":
    unittest.main()
