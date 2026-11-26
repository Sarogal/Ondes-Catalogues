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

    def test_double_budget_keeps_lanes_and_advances_same_slot(self):
        queue = ([row("oa", i) for i in range(24)] +
                 [row("tag", i, "genre_tag_review") for i in range(24)] +
                 [row("unknown", i) for i in range(72)])
        prior = None
        seen = set()
        with mock.patch.object(pipeline, "eligible", return_value=queue), \
             mock.patch.object(pipeline, "propose", side_effect=ValueError("Held")):
            for _ in range(3):
                out, report = pipeline.build({}, CATALOGUE, BEFORE, TODAY,
                                             slot=0, limit=32, prior=prior)
                ids = {c["candidateId"] for c in report["candidateChecks"]}
                self.assertEqual(len(ids), 32)
                self.assertFalse(seen & ids)
                self.assertEqual(report["reviewBudget"], 32)
                self.assertEqual(report["firstReviewInMemory"], 32)
                self.assertEqual(report["previouslyReviewed"], 0)
                self.assertEqual(report["openAgendaExamined"], 6)
                self.assertEqual(report["officialGenreTaggedExamined"], 8)
                self.assertEqual(out, BEFORE)
                self.assertFalse(report["publicationAllowed"])
                seen.update(ids)
                prior = report
            self.assertEqual(len(seen), 96)
            self.assertEqual(len(prior["recentReviewKeys"]), 96)
            with self.assertRaises(ValueError):
                pipeline.build({}, CATALOGUE, BEFORE, TODAY, slot=0, limit=49)

    def test_expanded_budget_and_time_deferred_rows_keep_original_recency(self):
        queue = ([row("oa", i) for i in range(24)] +
                 [row("tag", i, "genre_tag_review") for i in range(24)] +
                 [row("unknown", i) for i in range(72)])
        with mock.patch.object(pipeline, "eligible", return_value=queue), \
             mock.patch.object(pipeline, "propose", side_effect=ValueError("Held")):
            _, complete = pipeline.build({}, CATALOGUE, BEFORE, TODAY, limit=48)
            self.assertEqual(complete["examined"], 48)
            self.assertEqual(complete["officialGenreTaggedExamined"], 12)
            self.assertEqual(complete["reviewDeferredByTimeBudget"], 0)
            with mock.patch.object(pipeline.time, "monotonic",
                                   side_effect=[0, 0, 1, 2, 3, 3]):
                _, partial = pipeline.build({}, CATALOGUE, BEFORE, TODAY,
                                            limit=48, max_seconds=3)
            self.assertEqual(partial["examined"], 3)
            self.assertEqual(partial["reviewDeferredByTimeBudget"], 45)
            self.assertEqual(len(partial["recentReviewKeys"]), 3)
            self.assertEqual(len(partial["candidateChecks"]), 3)
            self.assertEqual(partial["firstReviewInMemory"], 3)
            _, next_report = pipeline.build({}, CATALOGUE, BEFORE, TODAY,
                                            limit=48, prior=partial)
            ids = {c["candidateId"] for c in partial["candidateChecks"]}
            self.assertFalse(ids & {c["candidateId"] for c in next_report["candidateChecks"]})
            self.assertEqual(next_report["examined"], 48)
            self.assertFalse(next_report["publicationAllowed"])
            for bad in (0, 241, True):
                with self.assertRaises(ValueError):
                    pipeline.build({}, CATALOGUE, BEFORE, TODAY, max_seconds=bad)

    def test_seen_priority_lanes_spill_into_unseen_general_queue(self):
        queue = ([row("oa", i) for i in range(2)] +
                 [row("tag", i, "genre_tag_review") for i in range(4)] +
                 [row("unknown", i) for i in range(122)])
        prior = None
        seen = set()
        with mock.patch.object(pipeline, "eligible", return_value=queue), \
             mock.patch.object(pipeline, "propose", side_effect=ValueError("Held")):
            for cycle in range(4):
                _, report = pipeline.build({}, CATALOGUE, BEFORE, TODAY,
                                           slot=0, limit=32, prior=prior)
                ids = {c["candidateId"] for c in report["candidateChecks"]}
                self.assertEqual(len(ids), 32)
                self.assertFalse(seen & ids)
                self.assertEqual(report["firstReviewInMemory"], 32)
                self.assertEqual(report["previouslyReviewed"], 0)
                seen.update(ids)
                prior = report
            self.assertEqual(len(seen), 128)
            self.assertEqual(len(prior["recentReviewKeys"]), 128)
            _, report = pipeline.build({}, CATALOGUE, BEFORE, TODAY,
                                       slot=0, limit=32, prior=prior)
            self.assertEqual(report["previouslyReviewed"], 32)
            self.assertGreater(report["openAgendaExamined"], 0)
            self.assertGreater(report["officialGenreTaggedExamined"], 0)
            self.assertFalse(report["publicationAllowed"])

    def test_malformed_legacy_review_history_is_only_advisory(self):
        queue = [row("unknown", i) for i in range(40)]
        header = {"schema": pipeline.SCHEMA, "publicationAllowed": False,
                  "privateApprovalApplied": False}
        with mock.patch.object(pipeline, "eligible", return_value=queue), \
             mock.patch.object(pipeline, "propose", side_effect=ValueError("Held")):
            for checks in (None, 3, [{"candidateId": [], "date": {}, "venueId": "x"}]):
                _, report = pipeline.build({}, CATALOGUE, BEFORE, TODAY,
                                           slot=0, prior={**header, "candidateChecks": checks})
                self.assertEqual(report["examined"], 16)
                self.assertEqual(report["firstReviewInMemory"], 16)

    def test_real_extractor_fingerprint_and_post_merge_trigger_cover_same_files(self):
        import fnmatch
        import re
        import tempfile
        from pathlib import Path

        paths = pipeline.EXTRACTOR_FILES
        actual = pipeline._extractor_revision()
        self.assertTrue(pipeline._valid_revision(actual))
        self.assertEqual(actual, pipeline._extractor_revision())
        workflow = (pipeline.ROOT / ".github/workflows/"
                    "grossesondes-concerts-private-intake-on-public-runners.yml").read_text(
                        encoding="utf-8")
        push = workflow.split("  workflow_dispatch:", 1)[0]
        patterns = re.findall(r"^\s+- '([^']+)'$", push, re.MULTILINE)
        for path in paths:
            with self.subTest(path=path):
                self.assertTrue((pipeline.ROOT / path).is_file())
                self.assertTrue(any(fnmatch.fnmatchcase(path, p) for p in patterns))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for path in paths:
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"fixture source")
            with mock.patch.object(pipeline, "ROOT", root):
                initial = pipeline._extractor_revision()
                self.assertTrue(pipeline._valid_revision(initial))
                (root / "unrelated-radio-catalogue.json").write_text("{}", encoding="utf-8")
                self.assertEqual(initial, pipeline._extractor_revision())
                (root / paths[0]).write_bytes(b"changed extractor")
                self.assertNotEqual(initial, pipeline._extractor_revision())
                (root / paths[0]).unlink()
                self.assertIsNone(pipeline._extractor_revision())

    def test_extractor_revision_retries_are_bounded_and_keep_other_lanes(self):
        queue = ([row("oa", i) for i in range(24)] +
                 [row("tag", i, "genre_tag_review") for i in range(24)] +
                 [row("unknown", i) for i in range(72)])
        old, new = "a" * 64, "b" * 64
        reason = next(iter(pipeline._EXTRACTION_REASONS))
        def fail(row, *args, **kwargs):
            raise ValueError(reason if row[3]["source"] != "agenda_officiel_openagenda"
                             else "Other source failure")
        with mock.patch.object(pipeline, "eligible", return_value=queue), \
             mock.patch.object(pipeline, "propose", side_effect=fail), \
             mock.patch.object(pipeline, "_extractor_revision", return_value=old):
            _, first = pipeline.build({}, CATALOGUE, BEFORE, TODAY, slot=0, limit=32)
            _, same = pipeline.build({}, CATALOGUE, BEFORE, TODAY, slot=0,
                                     limit=32, prior=first)
        self.assertEqual(len(first["extractionRetryMemory"]), 26)
        self.assertEqual(same["changedExtractorPriorityChecks"], 0)
        self.assertEqual(same["changedExtractorRetryPendingBefore"], 0)
        self.assertEqual(same["firstReviewInMemory"], 32)
        old_ids = {c["candidateId"] for c in first["candidateChecks"]}
        with mock.patch.object(pipeline, "eligible", return_value=queue), \
             mock.patch.object(pipeline, "propose", side_effect=fail), \
             mock.patch.object(pipeline, "_extractor_revision", return_value=new):
            out, retry = pipeline.build({}, CATALOGUE, BEFORE, TODAY, slot=0,
                                        limit=32, prior=first)
            self.assertEqual(out, BEFORE)
            self.assertEqual(retry["examined"], 32)
            self.assertEqual(retry["changedExtractorRetryPendingBefore"], 26)
            self.assertEqual(retry["changedExtractorPriorityChecks"], 8)
            self.assertEqual(retry["changedExtractorRetryPendingAfter"], 18)
            self.assertEqual(retry["openAgendaExamined"], 6)
            self.assertEqual(retry["officialGenreTaggedExamined"], 8)
            self.assertEqual(len(old_ids & {c["candidateId"]
                                           for c in retry["candidateChecks"]}), 8)
            self.assertEqual(retry["firstReviewInMemory"], 24)
            # A second cycle on the same revision consumes remaining stale
            # rows, but never gives the newly failed rows priority again.
            _, next_report = pipeline.build({}, CATALOGUE, BEFORE, TODAY,
                                            slot=0, limit=32, prior=retry)
            self.assertEqual(next_report["changedExtractorRetryPendingBefore"], 18)
            self.assertLess(next_report["changedExtractorRetryPendingAfter"], 18)
            self.assertLessEqual(next_report["changedExtractorPriorityChecks"], 8)
            self.assertFalse(next_report["publicationAllowed"])

    def test_frequent_extractor_revisions_rotate_priority_instead_of_first_rows(self):
        queue = [row("unknown", i) for i in range(48)]
        ordinary = queue[32:48]
        stale = queue[:32]
        keys = [pipeline._review_key(r) for r in stale]
        # Simulate a new revision between every review cycle. Even though
        # all failures become stale again, every old retry must get a turn.
        memory = list(reversed(keys))
        seen = set()
        for cycle in range(8):
            revision = f"{cycle+2:064x}"
            failures = {key: f"{cycle+1:064x}" for key in keys}
            window, picked, pending = pipeline._prioritize_extraction_retries(
                ordinary, queue, failures, revision, 16,
                recency={k: i for i, k in enumerate(memory)})
            self.assertEqual(pending, 32)
            self.assertEqual(len(picked), 4)
            self.assertEqual(len(window), 16)
            self.assertFalse(seen & picked)
            self.assertEqual(len({pipeline._review_key(r) for r in window}), 16)
            seen.update(picked)
            ordered = [pipeline._review_key(r) for r in window
                       if pipeline._review_key(r) in picked]
            memory = [k for k in memory if k not in picked] + ordered
        self.assertEqual(seen, set(keys))
        # A newly geocorrected candidate keeps precedence over the oldest
        # extraction failure, without increasing the total retry budget.
        recent = keys[0]
        _, picked, _ = pipeline._prioritize_extraction_retries(
            ordinary, queue, {k: "a"*64 for k in keys}, "b"*64, 16,
            geo_stale={recent}, recency={k: i for i, k in enumerate(memory)})
        self.assertIn(recent, picked)
        self.assertEqual(len(picked), 4)

    def test_legacy_extraction_retry_migration_and_untrusted_state(self):
        queue = [row("unknown", i) for i in range(60)]
        reason = next(iter(pipeline._EXTRACTION_REASONS))
        def fail(row, *args, **kwargs):
            raise ValueError(reason)
        with mock.patch.object(pipeline, "eligible", return_value=queue), \
             mock.patch.object(pipeline, "propose", side_effect=fail), \
             mock.patch.object(pipeline, "_extractor_revision", return_value="c" * 64):
            _, first = pipeline.build({}, CATALOGUE, BEFORE, TODAY, slot=0)
            legacy = {k: v for k, v in first.items()
                      if k not in ("extractionRetryMemory", "extractorRevision")}
            _, result = pipeline.build({}, CATALOGUE, BEFORE, TODAY, slot=0, prior=legacy)
            self.assertEqual(result["changedExtractorRetryPendingBefore"], 16)
            self.assertEqual(result["changedExtractorPriorityChecks"], 4)
            self.assertEqual(result["firstReviewInMemory"], 12)
            for invalid in (
                    {**legacy, "publicationAllowed": True},
                    {**first, "extractionRetryMemory": {"unknown": "a" * 64}},
                    {**first, "extractionRetryMemory": {k: [] for k in first["recentReviewKeys"]}},
                    {**first, "extractionRetryMemory": []}):
                _, report = pipeline.build({}, CATALOGUE, BEFORE, TODAY, slot=0, prior=invalid)
                self.assertEqual(report["changedExtractorPriorityChecks"], 0)
                self.assertEqual(report["examined"], 16)

    def test_missing_address_replay_migrates_existing_memory_once_per_revision(self):
        queue = [row("unknown", i) for i in range(60)]
        old, new = "a" * 64, "b" * 64
        reason = ("publisher_recheck: Unlisted official source: no unique exact "
                  "first-party MusicEvent: venue_address_missing")
        with mock.patch.object(pipeline, "eligible", return_value=queue), \
             mock.patch.object(pipeline, "propose", side_effect=ValueError(reason)), \
             mock.patch.object(pipeline, "_extractor_revision", return_value=old):
            _, first = pipeline.build({}, CATALOGUE, BEFORE, TODAY, limit=16)
            self.assertEqual(len(first["extractionRetryMemory"]), 16)
        # Simulate the preceding release: it knew the revision but did not
        # retain this reason in its existing extraction retry dictionary.
        prior = {**first, "extractionRetryMemory": {}}
        with mock.patch.object(pipeline, "eligible", return_value=queue), \
             mock.patch.object(pipeline, "propose", side_effect=ValueError(reason)), \
             mock.patch.object(pipeline, "_extractor_revision", return_value=new):
            out, retry = pipeline.build({}, CATALOGUE, BEFORE, TODAY,
                                        limit=16, prior=prior)
            self.assertEqual(out, BEFORE)
            self.assertEqual(retry["changedExtractorRetryPendingBefore"], 16)
            self.assertEqual(retry["changedExtractorPriorityChecks"], 4)
            self.assertEqual(retry["changedExtractorRetryPendingAfter"], 12)
            self.assertFalse(retry["publicationAllowed"])
            _, again = pipeline.build({}, CATALOGUE, BEFORE, TODAY,
                                      limit=16, prior=retry)
            self.assertEqual(again["changedExtractorRetryPendingBefore"], 12)
            self.assertLess(again["changedExtractorRetryPendingAfter"], 12)
            _, invalid = pipeline.build({}, CATALOGUE, BEFORE, TODAY,
                                        limit=16, prior={**prior, "publicationAllowed": True})
            self.assertEqual(invalid["changedExtractorPriorityChecks"], 0)

    def test_extraction_revision_ignores_unrelated_failure_reasons(self):
        queue = [row("unknown", i) for i in range(40)]
        with mock.patch.object(pipeline, "eligible", return_value=queue), \
             mock.patch.object(pipeline, "propose", side_effect=ValueError("date conflict")), \
             mock.patch.object(pipeline, "_extractor_revision", return_value="d" * 64):
            _, report = pipeline.build({}, CATALOGUE, BEFORE, TODAY)
            self.assertEqual(report["extractionRetryMemory"], {})
        with mock.patch.object(pipeline, "eligible", return_value=queue), \
             mock.patch.object(pipeline, "propose", side_effect=ValueError("date conflict")), \
             mock.patch.object(pipeline, "_extractor_revision", return_value="e" * 64):
            _, next_report = pipeline.build({}, CATALOGUE, BEFORE, TODAY, prior=report)
            self.assertEqual(next_report["changedExtractorPriorityChecks"], 0)
            self.assertEqual(next_report["firstReviewInMemory"], 16)

    def test_postal_hold_requeued_only_after_exact_venue_correction(self):
        import copy

        queue = [row("unknown", i) for i in range(60)]
        cat = {**CATALOGUE, "venues": [
            {"id": "official-room-" + str(i), "name": "Room " + str(i),
             "city": "Tours", "postalCode": "À vérifier", "address": "À vérifier",
             "geoPrecision": "centre de commune"}
            for i in range(13)]}
        reason = next(iter(pipeline._GEO_REPLAY_REASONS))
        with mock.patch.object(pipeline, "eligible", return_value=queue), \
             mock.patch.object(pipeline, "propose", side_effect=ValueError(reason)), \
             mock.patch.object(pipeline, "_extractor_revision", return_value="a" * 64):
            _, first = pipeline.build({}, cat, BEFORE, TODAY, limit=16)
            self.assertEqual(len(first["venueGeoRetryMemory"]), 16)
            _, unchanged = pipeline.build({}, cat, BEFORE, TODAY, limit=16, prior=first)
            self.assertEqual(unchanged["changedVenueGeoPriorityChecks"], 0)
            target = first["candidateChecks"][0]["venueId"]
            corrected = copy.deepcopy(cat)
            next(v for v in corrected["venues"] if v["id"] == target).update(
                postalCode="37000", address="12 rue Exemple",
                geoSource="https://www.openstreetmap.org/way/123",
                geoPrecision="named-site-area", latitude=47.395, longitude=0.688)
            out, retry = pipeline.build({}, corrected, BEFORE, TODAY, limit=16, prior=first)
            self.assertGreater(retry["changedVenueGeoRetryPendingBefore"], 0)
            self.assertGreater(retry["changedVenueGeoPriorityChecks"], 0)
            self.assertLessEqual(retry["changedVenueGeoPriorityChecks"], 4)
            self.assertEqual(retry["changedVenueGeoRetryPendingAfter"], 0)
            self.assertEqual(out, BEFORE)
            self.assertFalse(retry["publicationAllowed"])
            self.assertEqual(retry["examined"], 16)
            _, again = pipeline.build({}, corrected, BEFORE, TODAY, limit=16, prior=retry)
            self.assertEqual(again["changedVenueGeoPriorityChecks"], 0)
            legacy = {k: v for k, v in first.items() if k != "venueGeoRetryMemory"}
            _, migrated = pipeline.build({}, corrected, BEFORE, TODAY, limit=16, prior=legacy)
            self.assertGreater(migrated["changedVenueGeoPriorityChecks"], 0)
            _, invalid = pipeline.build({}, corrected, BEFORE, TODAY, limit=16,
                                        prior={**first, "publicationAllowed": True})
            self.assertEqual(invalid["changedVenueGeoPriorityChecks"], 0)

    def test_geographic_and_extractor_retries_share_one_budget(self):
        queue = [row("unknown", i) for i in range(50)]
        window = queue[20:36]
        old = "a" * 64
        new = "b" * 64
        extraction = {pipeline._review_key(r): old for r in queue[:10]}
        geographic = {pipeline._review_key(r) for r in queue[10:20]}
        actual, prioritized, pending = pipeline._prioritize_extraction_retries(
            window, queue, extraction, new, 16, geo_stale=geographic)
        self.assertEqual(len(actual), 16)
        self.assertEqual(len(prioritized), 4)
        self.assertTrue(prioritized <= geographic)
        self.assertEqual(pending, 10)

    def test_double_budget_reuses_unused_lanes(self):
        queue = [row("unknown", i) for i in range(40)]
        with mock.patch.object(pipeline, "eligible", return_value=queue), \
             mock.patch.object(pipeline, "propose", side_effect=ValueError("Held")):
            _, report = pipeline.build({}, CATALOGUE, BEFORE, TODAY,
                                       slot=0, limit=32)
            self.assertEqual(report["examined"], 32)
            self.assertEqual(report["otherOfficialExamined"], 32)
            self.assertEqual(report["officialGenreTaggedExamined"], 0)

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
