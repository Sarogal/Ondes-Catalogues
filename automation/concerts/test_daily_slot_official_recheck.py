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
            self.assertEqual(report["evaluated"], 12)
            self.assertEqual(report["newApprovals"], [])
            selections.append({x["candidateId"] for x in report["results"]})
        self.assertTrue(all(len(s) == 12 for s in selections))
        self.assertFalse(selections[0] & selections[1])
        self.assertFalse(selections[0] & selections[2])
        self.assertFalse(selections[1] & selections[2])
        _, repeat = self.process(registry, 1)
        self.assertEqual(
            selections[1], {x["candidateId"] for x in repeat["results"]})
        self.assertEqual(registry, before)

    def test_43_eligible_get_one_distinct_daily_recheck(self):
        # Actual 20 November queue had 43 potentially inspectable rows. An
        # uncapped daily sweep used to leave 13 rows unrechecked each day.
        entries = {f"case-{i:03d}": indexed_row(i) for i in range(43)}
        lists = []
        for slot in (0, 1, 2):
            _, report = self.process(entries, slot)
            lists.append({x["candidateId"] for x in report["results"]})
            self.assertEqual(report["dailyReviewCapacity"], 43)
            self.assertEqual(report["dailyReviewLimitPerSlot"], 16)
        self.assertEqual([len(x) for x in lists], [14, 14, 15])
        self.assertEqual(len(set.union(*lists)), 43)
        self.assertEqual(sum(map(len, lists)), 43)

    def test_larger_queues_rotate_without_daily_overlap(self):
        entries = [indexed_row(i) for i in range(100)]
        for day_offset in (0, 1, 2):
            daily = []
            for slot in (0, 1, 2):
                cohort = official_recheck.scheduled_review_cohort(
                    entries, TODAY + dt.timedelta(days=day_offset), slot, 16)
                daily.extend(row["candidate"]["candidateId"] for row in cohort)
            self.assertEqual(len(daily), 48)
            self.assertEqual(len(set(daily)), 48)
            if day_offset == 0:
                first_day = set(daily)
            elif day_offset == 1:
                second_day = set(daily)
                self.assertTrue(first_day.isdisjoint(second_day))
            else:
                self.assertEqual(len(first_day | second_day | set(daily)), 100)

    def test_small_queue_not_starved_on_any_slot(self):
        entries = [indexed_row(1)]
        for slot in (0, 1, 2):
            selected = official_recheck.scheduled_review_cohort(
                entries, TODAY, slot, 16)
            self.assertEqual(selected, entries)

    def test_capacity_and_slot_cannot_be_unbounded(self):
        for bad in (-1, 0, 25, True, "16"):
            with self.subTest(limit=bad), self.assertRaises(ValueError):
                official_recheck.scheduled_review_cohort([], TODAY, 1, bad)


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
        self.assertEqual(report["evaluated"], 12)
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
