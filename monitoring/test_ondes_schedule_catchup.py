"""Offline adversarial tests for the two-motor schedule rescue (no GitHub writes)."""
import datetime as dt
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ondes_schedule_catchup as recovery

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 11, 18, 16, tzinfo=UTC)


def run(hours, conclusion="success", status="completed",
        event="schedule", branch="main"):
    return {
        "head_branch": branch, "event": event, "status": status,
        "conclusion": conclusion,
        "created_at": (NOW - dt.timedelta(hours=hours)).isoformat(),
    }


class RecoveryTests(unittest.TestCase):
    def test_only_two_existing_first_party_targets(self):
        self.assertEqual(set(recovery.TARGETS), {"festivals", "sorties"})
        f = recovery.TARGETS["festivals"]
        p = recovery.TARGETS["sorties"]
        self.assertEqual(f["inputs"], {"phase": "catchup"})
        self.assertEqual(p["inputs"],
                         {"cycle": "all", "mode": "write", "recovery": "catchup"})
        self.assertEqual(f["success_gap"], dt.timedelta(hours=14))
        self.assertEqual(p["success_gap"], dt.timedelta(hours=7))
        with self.assertRaises(TypeError):
            recovery.TARGETS["arbitrary"] = {}

    def test_recent_scheduled_run_suppresses_recovery(self):
        rows = [run(1)]
        for spec in recovery.TARGETS.values():
            self.assertEqual(recovery.decide(
                rows, NOW, spec["success_gap"], spec["active_gap"])[0], False)

    def test_dispatched_intake_counts_as_recent(self):
        rows = [run(18), run(1, event="workflow_dispatch")]
        self.assertFalse(recovery.decide(
            rows, NOW, dt.timedelta(hours=14),
            dt.timedelta(hours=14))[0])

    def test_festival_at_13h_not_due_and_at_15h_due(self):
        spec = recovery.TARGETS["festivals"]
        self.assertFalse(recovery.decide(
            [run(13)], NOW, spec["success_gap"], spec["active_gap"])[0])
        self.assertTrue(recovery.decide(
            [run(15)], NOW, spec["success_gap"], spec["active_gap"])[0])

    def test_outings_at_6h_not_due_and_at_8h_due(self):
        spec = recovery.TARGETS["sorties"]
        self.assertFalse(recovery.decide(
            [run(6)], NOW, spec["success_gap"], spec["active_gap"])[0])
        self.assertTrue(recovery.decide(
            [run(8)], NOW, spec["success_gap"], spec["active_gap"])[0])

    def test_failed_run_can_retry_after_90_minutes(self):
        spec = recovery.TARGETS["sorties"]
        self.assertFalse(recovery.decide(
            [run(1, conclusion="failure")], NOW,
            spec["success_gap"], spec["active_gap"])[0])
        self.assertTrue(recovery.decide(
            [run(2, conclusion="failure")], NOW,
            spec["success_gap"], spec["active_gap"])[0])

    def test_never_dispatch_again_while_recent_run_is_active(self):
        for status in ("queued", "in_progress", "waiting"):
            spec = recovery.TARGETS["sorties"]
            self.assertFalse(recovery.decide(
                [run(1, status=status, conclusion=None)], NOW,
                spec["success_gap"], spec["active_gap"])[0])

    def test_untrusted_pr_runs_not_counted(self):
        spec = recovery.TARGETS["festivals"]
        rows = [run(16), run(0, event="pull_request")]
        self.assertTrue(recovery.decide(
            rows, NOW, spec["success_gap"], spec["active_gap"])[0])
        rows = [run(16), run(0, event="workflow_dispatch", branch="foreign")]
        self.assertTrue(recovery.decide(
            rows, NOW, spec["success_gap"], spec["active_gap"])[0])

    def test_clock_skew_unknown_status_bad_payload_fail_closed(self):
        spec = recovery.TARGETS["sorties"]
        self.assertFalse(recovery.decide(
            [run(-1)], NOW, spec["success_gap"], spec["active_gap"])[0])
        self.assertFalse(recovery.decide(
            [run(8, status="invented")], NOW,
            spec["success_gap"], spec["active_gap"])[0])
        with self.assertRaises(ValueError):
            recovery.decide([{"event": "schedule", "head_branch": "main",
                              "created_at": "invalid"}], NOW,
                            spec["success_gap"], spec["active_gap"])
        with self.assertRaises(ValueError):
            recovery.decide("not a list", NOW, spec["success_gap"],
                            spec["active_gap"])

    def test_one_motor_due_does_not_wake_the_other(self):
        result = recovery.plan({"festivals": [run(10)],
                                "sorties": [run(10)]}, NOW)
        self.assertFalse(result["festivals"]["dispatch"])
        self.assertTrue(result["sorties"]["dispatch"])

    def test_invalid_target_history_rejected(self):
        with self.assertRaises(ValueError):
            recovery.plan({"festivals": []}, NOW)

    def test_no_intake_run_wakes_only_committed_target(self):
        spec = recovery.TARGETS["festivals"]
        self.assertTrue(recovery.decide(
            [], NOW, spec["success_gap"], spec["active_gap"])[0])

    def test_main_ref_and_scheduled_event_required_before_network(self):
        for key, value in (
            ("GITHUB_EVENT_NAME", "pull_request"),
            ("GITHUB_REF", "refs/heads/evil"),
            ("GITHUB_REPOSITORY", "outsider/fork"),
        ):
            env = {
                "GITHUB_EVENT_NAME": "schedule",
                "GITHUB_REF": "refs/heads/main",
                "GITHUB_REPOSITORY": recovery.REPO, "GH_TOKEN": "dummy",
            }
            env[key] = value
            with self.subTest(key=key), patch.dict(os.environ, env):
                with patch.object(sys, "argv", ["recovery", "--execute"]):
                    with patch.object(recovery, "request") as api:
                        with self.assertRaises(ValueError):
                            recovery.main()
                        api.assert_not_called()

    def test_dry_run_never_dispatches(self):
        env = {"GITHUB_EVENT_NAME": "schedule", "GITHUB_REF": "refs/heads/main",
               "GITHUB_REPOSITORY": recovery.REPO, "GH_TOKEN": "dummy"}
        with patch.dict(os.environ, env), patch.object(
                sys, "argv", ["recovery"]), patch.object(
                recovery, "request", return_value={"workflow_runs": []}) as api:
            recovery.main()
            self.assertEqual(api.call_count, 2)
            self.assertTrue(all(c.args[2:] == () for c in api.call_args_list))


if __name__ == "__main__":
    unittest.main()
