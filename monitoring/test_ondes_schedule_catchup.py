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
                         {"cycle": "outings", "mode": "write", "recovery": "catchup"})
        self.assertEqual(f["success_gap"], dt.timedelta(hours=14))
        self.assertEqual(p["success_gap"], dt.timedelta(hours=7))
        with self.assertRaises(TypeError):
            recovery.TARGETS["arbitrary"] = {}

    def test_rescue_matches_existing_runner_fail_closed_guard(self):
        # Main workflow rejects recovery=catchup unless CYCLE=outings,
        # RUN_MODE=write and RUN_EVENT=external_rescue.
        from pathlib import Path
        script = Path(__file__).resolve().parents[1]
        workflow = (script / ".github/workflows/ptitesondes-private-intake-on-public-runners.yml").read_text()
        assert "if [[ \"$RECOVERY\" == 'catchup' ]]" in workflow
        assert '"$CYCLE" != ' in workflow and "'outings'" in workflow
        payload = recovery.TARGETS["sorties"]["inputs"]
        self.assertEqual(payload["cycle"], "outings")
        self.assertEqual(payload["mode"], "write")
        self.assertEqual(payload["recovery"], "catchup")

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
        result = recovery.plan({"festivals": [run(9)],
                                "sorties": [run(10)]}, NOW)
        self.assertFalse(result["festivals"]["dispatch"])
        self.assertTrue(result["sorties"]["dispatch"])

    def test_evening_slot_missed_despite_afternoon_push(self):
        utc = dt.timezone.utc
        now = dt.datetime(2026, 11, 19, 19, 35, tzinfo=utc)
        def at(hour, minute, *, status="completed", conclusion="success",
               event="schedule", branch="main"):
            return {
                "head_branch": branch, "event": event,
                "created_at": dt.datetime(2026, 11, 19, hour, minute,
                                         tzinfo=utc).isoformat(),
                "status": status, "conclusion": conclusion,
            }
        # 16:40 trusted push cannot conceal a missing 18:42 UTC schedule.
        self.assertEqual(recovery.festival_slot_decide(
            [at(16, 40, event="push")], now),
            (True, "expected-festivals-slot-missing"))
        # A real intake started after the expected slot satisfies the check,
        # regardless of schedule, protected push or authorized dispatch.
        for event in ("schedule", "workflow_dispatch", "push"):
            self.assertEqual(recovery.festival_slot_decide(
                [at(16, 40, event="push"), at(18, 48, event=event)], now),
                (False, "slot-succeeded"))
        self.assertFalse(recovery.festival_slot_decide(
            [at(18, 50, status="in_progress", conclusion=None)], now)[0])
        # Failed attempt gets a bounded grace, never a tight retry loop.
        self.assertFalse(recovery.festival_slot_decide(
            [at(18, 50, conclusion="failure")], now)[0])
        later = dt.datetime(2026, 11, 19, 21, tzinfo=utc)
        self.assertTrue(recovery.festival_slot_decide(
            [at(18, 50, conclusion="failure")], later)[0])
        self.assertFalse(recovery.festival_slot_decide(
            [at(18, 55, branch="untrusted"),
             at(18, 57, event="pull_request"),
             at(18, 59, event="workflow_run"),
             at(18, 58, status="queued", conclusion=None)], now)[0])

    def test_slot_grace_morning_evening_and_cross_day(self):
        utc = dt.timezone.utc
        completed = lambda stamp: {
            "head_branch": "main", "event": "schedule",
            "created_at": stamp.isoformat(),
            "status": "completed", "conclusion": "success",
        }
        yesterday = dt.datetime(2026, 11, 18, 19, tzinfo=utc)
        before_grace = dt.datetime(2026, 11, 19, 19, 20, tzinfo=utc)
        after_grace = dt.datetime(2026, 11, 19, 19, 28, tzinfo=utc)
        self.assertFalse(recovery.festival_slot_decide(
            [completed(yesterday), completed(
                dt.datetime(2026, 11, 19, 6, 29, tzinfo=utc))],
            before_grace)[0])
        self.assertTrue(recovery.festival_slot_decide(
            [completed(yesterday), completed(
                dt.datetime(2026, 11, 19, 6, 29, tzinfo=utc))],
            after_grace)[0])
        # A night-time rescue after 18:42 UTC also protects the next morning.
        next_morning = dt.datetime(2026, 11, 20, 6, 45, tzinfo=utc)
        self.assertFalse(recovery.festival_slot_decide(
            [completed(dt.datetime(2026, 11, 19, 22, 44, tzinfo=utc))],
            next_morning)[0])
        self.assertTrue(recovery.festival_slot_decide(
            [], dt.datetime(2026, 11, 20, 7, 15, tzinfo=utc))[0])

    def test_public_schedule_slots_are_fixed_and_no_private_crons(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github/workflows/grossesondes-festivals-private-intake-on-public-runners.yml").read_text()
        catchup = (root / ".github/workflows/ondes-national-schedule-catchup.yml").read_text()
        self.assertIn("cron: '24 6 * * *'", workflow)
        self.assertIn("cron: '42 18 * * *'", workflow)
        self.assertEqual(recovery.FESTIVAL_SLOTS_UTC, ((6, 24), (18, 42)))
        self.assertIn("cron: '34 7,19 * * *'", catchup)
        self.assertIn("runs-on: ubuntu-24.04", catchup)
        self.assertIn("contents: read", catchup)
        self.assertIn("actions: write", catchup)

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
