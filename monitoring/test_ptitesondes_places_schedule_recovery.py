import unittest
from datetime import datetime, timedelta, timezone
from ptitesondes_places_schedule_recovery import (
    decide, trusted, place_job_result, REPO, INPUTS, PLACE_STEP, WRITE_STEP, RESEARCH_STEP,
)

NOW = datetime(2026, 11, 26, 21, tzinfo=timezone.utc)


def run(minutes, id=1, status="completed", event="schedule", branch="main"):
    return {"id": id, "status": status, "event": event, "head_branch": branch,
            "created_at": (NOW - timedelta(minutes=minutes)).isoformat()}


def job(place="success", write="success", conclusion="success", research="success"):
    steps = [{"name": PLACE_STEP, "conclusion": place},
             {"name": WRITE_STEP, "conclusion": write}]
    if research is not None:
        steps.append({"name": RESEARCH_STEP, "conclusion": research})
    return {"total_count": 1, "jobs": [{"name": "run-private", "conclusion": conclusion,
              "steps": steps}]}


class PlaceScheduleRecoveryTests(unittest.TestCase):
    def test_outings_success_does_not_hide_missing_places(self):
        self.assertEqual(decide([run(20)], NOW, lambda _: job(place="skipped")),
                         (True, "places_cycle_due"))

    def test_successful_places_write_suppresses_repeat_even_after_outings(self):
        rows = [run(20, 1), run(80, 2)]
        self.assertEqual(decide(rows, NOW, lambda rid: job(
            place="skipped") if rid == 1 else job()), (False, "recent_places_write"))

    def test_preview_does_not_count(self):
        self.assertEqual(decide([run(20, event="push")], NOW,
                                lambda _: job(write="skipped")),
                         (True, "places_cycle_due"))

    def test_legacy_success_does_not_mask_missing_generic_research(self):
        self.assertEqual(decide([run(20)], NOW, lambda _: job(research=None)),
                         (True, "places_cycle_due"))

    def test_generic_failure_in_otherwise_successful_write_observes_retry_grace(self):
        self.assertEqual(decide([run(20)], NOW, lambda _: job(research="skipped")),
                         (False, "failure_retry_grace"))
        self.assertEqual(decide([run(100)], NOW, lambda _: job(research="skipped")),
                         (True, "places_cycle_due"))

    def test_preview_completion_can_recover_even_after_legacy_success(self):
        rows = [run(10, 1, event="push"), run(25, 2, event="workflow_dispatch")]
        self.assertEqual(decide(rows, NOW, lambda rid: job(
            write="skipped", research="skipped") if rid == 1 else job(research=None)),
            (True, "places_cycle_due"))

    def test_active_intake_suppresses_dispatch_without_jobs_read(self):
        self.assertEqual(decide([run(10, status="in_progress")], NOW,
                                lambda _: self.fail("unexpected jobs read")),
                         (False, "trusted_intake_active"))

    def test_failure_retry_grace_and_old_success(self):
        self.assertEqual(decide([run(20)], NOW,
                                lambda _: job(place="failure", conclusion="failure")),
                         (False, "failure_retry_grace"))
        self.assertEqual(decide([run(100)], NOW,
                                lambda _: job(place="failure", conclusion="failure")),
                         (True, "places_cycle_due"))
        self.assertTrue(decide([run(250)], NOW, lambda _: job())[0])

    def test_pr_and_non_main_ignored(self):
        self.assertTrue(decide([run(1, event="pull_request"), run(1, branch="other")],
                               NOW, lambda _: self.fail("unexpected jobs read"))[0])

    def test_malformed_jobs_and_clock_skew_fail_closed(self):
        with self.assertRaises(ValueError):
            place_job_result({"total_count": 2, "jobs": []})
        self.assertFalse(decide([run(-10)], NOW, lambda _: job())[0])

    def test_pause_and_trusted_events(self):
        self.assertTrue(trusted(REPO, "refs/heads/main", "push", ""))
        self.assertTrue(trusted(REPO, "refs/heads/main", "schedule", ""))
        self.assertTrue(trusted(REPO, "refs/heads/main", "workflow_run", ""))
        self.assertFalse(trusted(REPO, "refs/heads/main", "workflow_run", "paused"))
        self.assertFalse(trusted(REPO, "refs/heads/main", "schedule", "paused"))
        self.assertFalse(trusted(REPO, "refs/heads/main", "pull_request", ""))
        self.assertEqual(INPUTS, {"cycle": "places", "mode": "write", "recovery": "none"})


if __name__ == "__main__":
    unittest.main()
