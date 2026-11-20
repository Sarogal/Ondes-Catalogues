"""Three daily independent recheck cohorts, without weakening approvals.

No private registry or network data is required; the public source manifest,
actual publisher validation and stability rules remain unmodified.
"""
import copy
import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import official_recheck

TODAY = dt.date(2026, 11, 20)
CATALOGUE = {
    "schemaVersion": 1, "mode": "preview-public-unlisted",
    "venues": [], "artists": [], "events": [],
}
APPROVALS = {"schema": "grossesondes.concert.approvals.v1",
             "approvals": [], "venueApprovals": []}


def indexed_row(i):
    return {
        "status": "pending_review", "stableObservations": 2,
        "candidate": {
            "candidateId": f"synthetic-site-{i:03d}",
            "source": "agenda_officiel_structuré",
            "reviewBucket": "genre_unknown",
            "sourceUrl": f"https://unverified.example/concert/{i:03d}",
            "date": "2027-05-17", "venue": "Unknown public venue",
            "city": "Paris", "publicationAllowed": False,
            "reviewRequired": True,
        },
    }


class MultiSlotRecheckTests(unittest.TestCase):
    def process(self, entries, slot, **kw):
        return official_recheck.process(
            {"items": entries}, CATALOGUE, APPROVALS, TODAY,
            fetch=lambda *_: self.fail("Network must not be reached"),
            scan_slot=slot, **kw)

    def test_three_daily_cycles_recheck_distinct_stable_cohorts(self):
        registry = {f"case-{i:03d}": indexed_row(i) for i in range(36)}
        before = copy.deepcopy(registry)
        selections = []
        for slot in (0, 1, 2):
            out, report = self.process(registry, slot)
            self.assertEqual(out, APPROVALS)
            self.assertEqual(report["scanSlot"], slot)
            self.assertEqual(report["totalEligible"], 36)
            self.assertEqual(report["evaluated"], 10)
            self.assertEqual(report["newApprovals"], [])
            selections.append({x["candidateId"] for x in report["results"]})
        self.assertTrue(all(len(s) == 10 for s in selections))
        self.assertFalse(selections[0] & selections[1])
        self.assertFalse(selections[0] & selections[2])
        self.assertFalse(selections[1] & selections[2])
        _, repeat = self.process(registry, 1)
        self.assertEqual(
            selections[1], {x["candidateId"] for x in repeat["results"]})
        self.assertEqual(registry, before)

    def test_listing_without_individual_event_never_spends_review_budget(self):
        items = {f"case-{i}": indexed_row(i) for i in range(12)}
        for k, source in enumerate((
            "promoter_official_tour", "artist_official_tour",
            "promoter_official_tour_detail",
        )):
            items[f"missing-{k}"] = {
                "status": "pending_review", "stableObservations": 2,
                "candidate": {
                    "candidateId": f"missing-event-detail-{k}",
                    "date": "2027-05-17", "source": source,
                    "newVenueToReview": True,
                    "reviewBucket": "genre_unknown",
                    "publicationAllowed": False, "reviewRequired": True,
                }}
        out, report = self.process(items, 0)
        self.assertEqual(out, APPROVALS)
        self.assertEqual(report["awaitingIndividualOfficialEventDetail"], 3)
        self.assertEqual(report["totalEligible"], 12)
        self.assertEqual(report["evaluated"], 10)
        self.assertTrue(all(not x["candidateId"].startswith("missing-")
                            for x in report["results"]))
        self.assertEqual(len(items), 15)  # Still archived, never deleted.

    def test_one_day_and_rejected_rows_remain_quarantined(self):
        items = {
            "one": dict(indexed_row(1), stableObservations=1),
            "decided": dict(indexed_row(2), status="rejected"),
            "ready": indexed_row(3),
        }
        _, report = self.process(items, 2)
        self.assertEqual(report["evaluated"], 1)
        self.assertEqual(report["decidedSkipped"], 1)
        self.assertEqual(report["totalEligible"], 1)
        self.assertEqual(report["newApprovals"], [])

    def test_invalid_slot_rejected_before_any_approval_or_network(self):
        for bad in (-1, 3, "1", True, None):
            with self.subTest(slot=bad), self.assertRaises(ValueError):
                self.process({"one": indexed_row(1)}, bad)


if __name__ == "__main__":
    unittest.main()
