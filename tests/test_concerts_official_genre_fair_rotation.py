"""Bounded, fair, no-trust admission review for named official music bills.

Genre on discovery is strictly a SCHEDULING HINT. An unrelated HTML page,
an ambiguous date or a forged source still fails independent verification.
"""
from __future__ import annotations
import datetime as dt
import unittest
from unittest import mock

from automation.concerts import dynamic_osm_official_proposals as pipeline

TODAY = dt.date(2026, 11, 23)
BEFORE = {"schema": "grossesondes.concert.approvals.v1", "approvals": []}
CATALOGUE = {"schemaVersion": 1, "venues": [], "artists": [], "events": []}


def row(label, index, kind="genre_unknown"):
    source = ("agenda_officiel_openagenda" if label == "oa"
              else "agenda_officiel_structuré")
    c = {"candidateId": f"{label}-{index:03d}", "source": source,
         "reviewBucket": kind}
    if label == "oa":
        c.update(openAgendaUid=123, openAgendaEventUid=index + 1)
    return (f"https://source.example/{label}/{index:03d}/",
            "2027-06-01", f"official-room-{index % 13}", c)


class FairGenreReviewSlots(unittest.TestCase):
    def run_day(self, queue, day, slot):
        with mock.patch.object(pipeline, "eligible", return_value=queue), \
             mock.patch.object(pipeline, "propose",
                               side_effect=ValueError("Independent recheck failed")):
            output, diagnostics = pipeline.build(
                {}, CATALOGUE, BEFORE, day, slot=slot, limit=12)
        self.assertEqual(output, BEFORE)
        self.assertEqual(diagnostics["examined"], 12)
        self.assertEqual(len({r["candidateId"]
                              for r in diagnostics["candidateChecks"]}), 12)
        self.assertEqual(diagnostics["privateApprovalApplied"], False)
        self.assertEqual(diagnostics["publicationAllowed"], False)
        return diagnostics

    def test_tagged_official_bills_get_two_checks_without_starving_unknown(self):
        # Two of 12 probes favour real event-level genres, not specific bands,
        # rooms, URLs or known artists. Ten remain open to any other source.
        queue = ([row("tag", x, "genre_tag_review") for x in range(6)] +
                 [row("unknown", x) for x in range(50)])
        seen_tagged, seen_unknown = set(), set()
        for slot in (0, 1, 2):
            report = self.run_day(queue, TODAY, slot)
            self.assertEqual(report["openAgendaExamined"], 0)
            self.assertEqual(report["officialGenreTaggedExamined"], 2)
            self.assertEqual(report["otherOfficialExamined"], 12)
            for checked in report["candidateChecks"]:
                (seen_tagged if checked["candidateId"].startswith("tag")
                 else seen_unknown).add(checked["candidateId"])
        self.assertEqual(len(seen_tagged), 6)
        self.assertEqual(len(seen_unknown), 30)
        for slot in range(3, 6):
            report = self.run_day(queue, TODAY + dt.timedelta(days=slot // 3),
                                  slot % 3)
            seen_unknown.update(check["candidateId"]
                                for check in report["candidateChecks"]
                                if check["candidateId"].startswith("unknown"))
        self.assertEqual(len(seen_unknown), 50)

    def test_mixed_openagenda_tagged_and_unknown_keep_all_lanes(self):
        queue = ([row("oa", i) for i in range(50)] +
                 [row("tag", i, "genre_tag_review") for i in range(10)] +
                 [row("unknown", i) for i in range(80)])
        seen = set()
        for tick in range(18):
            d = TODAY + dt.timedelta(days=tick // 3)
            report = self.run_day(queue, d, tick % 3)
            self.assertEqual(report["openAgendaExamined"], 4)
            self.assertEqual(report["officialGenreTaggedExamined"], 2)
            self.assertEqual(report["otherOfficialExamined"], 8)
            seen.update(x["candidateId"] for x in report["candidateChecks"])
        self.assertEqual(len(seen), 140)

    def test_tagged_only_does_not_leave_unused_capacity(self):
        tagged = [row("tag", i, "genre_tag_review") for i in range(30)]
        report = self.run_day(tagged, TODAY, 2)
        self.assertEqual(report["officialGenreTaggedExamined"], 12)
        self.assertEqual(report["otherOfficialExamined"], 12)

    def test_repeated_same_slot_advances_all_lanes_with_private_memory(self):
        queue = ([row("oa", i) for i in range(12)] +
                 [row("tag", i, "genre_tag_review") for i in range(12)] +
                 [row("unknown", i) for i in range(36)])
        prior = None
        seen = set()
        with mock.patch.object(pipeline, "eligible", return_value=queue), \
             mock.patch.object(pipeline, "propose", side_effect=ValueError("Held")):
            for cycle in range(3):
                out, report = pipeline.build({}, CATALOGUE, BEFORE, TODAY,
                                             slot=0, limit=16, prior=prior)
                ids = {c["candidateId"] for c in report["candidateChecks"]}
                self.assertEqual(len(ids), 16)
                self.assertFalse(seen & ids)
                self.assertEqual(report["firstReviewInMemory"], 16)
                self.assertEqual(report["previouslyReviewed"], 0)
                self.assertEqual(report["openAgendaExamined"], 3)
                self.assertEqual(report["officialGenreTaggedExamined"], 4)
                self.assertEqual(out, BEFORE)
                seen.update(ids)
                prior = report
            self.assertEqual(len(prior["recentReviewKeys"]), 48)
            _, report = pipeline.build({}, CATALOGUE, BEFORE, TODAY,
                                        slot=0, limit=16, prior=prior)
            self.assertGreater(report["previouslyReviewed"], 0)
            self.assertEqual(len(set(report["recentReviewKeys"])),
                             len(report["recentReviewKeys"]))

    def test_legacy_report_can_advance_same_slot_and_untrusted_memory_ignored(self):
        queue = [row("unknown", i) for i in range(40)]
        with mock.patch.object(pipeline, "eligible", return_value=queue), \
             mock.patch.object(pipeline, "propose", side_effect=ValueError("Held")):
            _, first = pipeline.build({}, CATALOGUE, BEFORE, TODAY, slot=1)
            legacy = {k: v for k, v in first.items() if k != "recentReviewKeys"}
            _, second = pipeline.build({}, CATALOGUE, BEFORE, TODAY,
                                        slot=1, prior=legacy)
            first_ids = {c["candidateId"] for c in first["candidateChecks"]}
            second_ids = {c["candidateId"] for c in second["candidateChecks"]}
            self.assertFalse(first_ids & second_ids)
            _, invalid = pipeline.build({}, CATALOGUE, BEFORE, TODAY, slot=1,
                                         prior={**first, "publicationAllowed": True})
            self.assertEqual(first["candidateChecks"], invalid["candidateChecks"])

    def test_all_unknown_sources_unchanged_rotation(self):
        queue = [row("unknown", i) for i in range(50)]
        seen = set()
        for tick in range(5):
            report = self.run_day(queue,
                                  TODAY + dt.timedelta(days=tick // 3),
                                  tick % 3)
            self.assertEqual(report["officialGenreTaggedExamined"], 0)
            seen.update(x["candidateId"] for x in report["candidateChecks"])
        self.assertEqual(len(seen), 50)


if __name__ == "__main__":
    unittest.main()
