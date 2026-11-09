"""Offline, adversarial tests for overdue scheduled verification catch-up."""
from datetime import date, datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_schedule_catchup import (
    OUTINGS_CRONS, MAX_SLOTS, already_reviewed, pending_slots,
)

DAY = date(2026, 11, 9)


def utc(day, hour, minute):
    return datetime(day.year, day.month, day.day, hour, minute,
                    tzinfo=timezone.utc)


def add_completed_report(root, day, slot):
    path = root / f"qualification-{day.isoformat()}-slot{slot}.json"
    path.write_text(json.dumps({
        "schema": "ptitesondes.private_qualification_summary.v1",
        "day": day.isoformat(), "slot": slot,
        "checked": 15, "accepted_preflight": 0,
        "rejected": 15, "publications": 0,
        "mode": "private_diagnostic_only",
    }), encoding="utf-8")
    return path


class CatchupTests(unittest.TestCase):
    def test_on_time_one_slot_only(self):
        with tempfile.TemporaryDirectory() as base:
            root = Path(base)
            self.assertEqual(pending_slots(DAY, utc(DAY, 7, 17),
                                           "schedule", OUTINGS_CRONS[0][0], root),
                             [0])

    def test_delayed_first_cron_recovers_only_elapsed_missing_slots(self):
        with tempfile.TemporaryDirectory() as base:
            root = Path(base)
            add_completed_report(root, DAY, 0)
            self.assertEqual(pending_slots(DAY, utc(DAY, 17, 28),
                                           "schedule", OUTINGS_CRONS[0][0], root),
                             [1, 2])
            self.assertEqual(pending_slots(DAY, utc(DAY, 18, 28),
                                           "schedule", OUTINGS_CRONS[0][0], root),
                             [1, 2, 3])

    def test_final_cron_can_recover_all_four_if_others_never_started(self):
        with tempfile.TemporaryDirectory() as base:
            self.assertEqual(pending_slots(DAY, utc(DAY, 21, 0),
                                           "schedule", OUTINGS_CRONS[3][0], Path(base)),
                             [0, 1, 2, 3])

    def test_previous_reports_skip_successful_slots(self):
        with tempfile.TemporaryDirectory() as base:
            root = Path(base)
            for slot in (0, 2, 3):
                add_completed_report(root, DAY, slot)
            self.assertEqual(pending_slots(DAY, utc(DAY, 19, 0),
                                           "schedule", OUTINGS_CRONS[3][0], root),
                             [1])
            add_completed_report(root, DAY, 1)
            self.assertEqual(pending_slots(DAY, utc(DAY, 19, 0),
                                           "schedule", OUTINGS_CRONS[3][0], root),
                             [])

    def test_malformed_report_is_not_treated_as_a_success(self):
        with tempfile.TemporaryDirectory() as base:
            root = Path(base)
            file = add_completed_report(root, DAY, 0)
            for altered in (
                "{",
                json.dumps({"schema": "ptitesondes.private_qualification_summary.v1",
                            "day": "2026-11-08", "slot": 0,
                            "checked": 15, "accepted_preflight": 0,
                            "rejected": 15, "publications": 0,
                            "mode": "private_diagnostic_only"}),
                json.dumps({"schema": "ptitesondes.private_qualification_summary.v1",
                            "day": DAY.isoformat(), "slot": 0,
                            "checked": 16, "accepted_preflight": 0,
                            "rejected": 16, "publications": 0,
                            "mode": "private_diagnostic_only"}),
                json.dumps({"schema": "ptitesondes.private_qualification_summary.v1",
                            "day": DAY.isoformat(), "slot": 0,
                            "checked": 15, "accepted_preflight": 0,
                            "rejected": 15, "publications": 1,
                            "mode": "private_diagnostic_only"}),
            ):
                with self.subTest(altered=altered):
                    file.write_text(altered, encoding="utf-8")
                    with self.assertRaises(ValueError):
                        already_reviewed(root, DAY, 0)

    def test_do_not_attribute_yesterday_to_tomorrows_paris_day(self):
        with tempfile.TemporaryDirectory() as base:
            self.assertEqual(pending_slots(
                date(2026, 11, 10), utc(DAY, 23, 15),
                "schedule", OUTINGS_CRONS[0][0], Path(base)), [])

    def test_manual_and_push_preserve_single_slot_and_do_not_claim_recovery(self):
        with tempfile.TemporaryDirectory() as base:
            root = Path(base)
            add_completed_report(root, DAY, 0)
            for event in ("push", "workflow_dispatch"):
                self.assertEqual(pending_slots(DAY, utc(DAY, 20, 0),
                                               event, "", root), [0])

    def test_invalid_event_cron_or_clock_fails_closed(self):
        with tempfile.TemporaryDirectory() as base:
            root = Path(base)
            cases = (
                (DAY, utc(DAY, 19, 0), "schedule", "37 21 * * *"),
                (DAY, utc(DAY, 6, 0), "schedule", OUTINGS_CRONS[0][0]),
                (DAY, datetime(2026, 11, 9, 19, 0), "schedule",
                 OUTINGS_CRONS[3][0]),
                (DAY, utc(DAY, 19, 0), "push", OUTINGS_CRONS[0][0]),
                (DAY, utc(DAY, 19, 0), "other", ""),
            )
            for day, now, event, cron in cases:
                with self.subTest(event=event, cron=cron):
                    with self.assertRaises(ValueError):
                        pending_slots(day, now, event, cron, root)

    def test_bounded_unique_cron_mapping(self):
        self.assertEqual(len(OUTINGS_CRONS), MAX_SLOTS)
        self.assertEqual(len({c[0] for c in OUTINGS_CRONS}), MAX_SLOTS)
        with tempfile.TemporaryDirectory() as base:
            slots = pending_slots(DAY, utc(DAY, 23, 0),
                                  "schedule", OUTINGS_CRONS[2][0], Path(base))
            self.assertEqual(len(slots), MAX_SLOTS)
            self.assertEqual(len(slots), len(set(slots)))


if __name__ == "__main__":
    unittest.main()
