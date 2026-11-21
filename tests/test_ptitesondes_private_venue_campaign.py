"""Adversarial offline checks of the private seven-batch runner (no network)."""
from contextlib import redirect_stdout
from datetime import date
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import ptitesondes_private_venue_campaign as campaign

DAY = date(2026, 11, 20)


class PrivateVenueCampaignTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.inputs = base / "private"
        self.outputs = base / "reports"
        self.inputs.mkdir(mode=0o700)
        self.outputs.mkdir(mode=0o700)
        self.backlog = self.inputs / "backlog.json"
        self.sources = self.inputs / "sources.json"
        self.backlog.write_text("[]", encoding="utf-8")
        self.sources.write_text(json.dumps({
            "schema": "ptitesondes.sources.v1",
            "openagenda_agendas": [],
        }), encoding="utf-8")
        self.venues = patch.object(
            campaign, "groups_for_review", return_value=[{}] * 79)
        self.venues.start()
        self.addCleanup(self.venues.stop)

    def plan(self):
        return campaign.prepare_campaign(
            self.backlog, self.sources, self.outputs, DAY)

    def test_full_79_venue_plan_has_seven_disjoint_batches(self):
        plan = self.plan()
        self.assertEqual(plan["unknown_venues"], 79)
        self.assertEqual(plan["batch_count"], 7)
        self.assertEqual(len(set(plan["report_paths"])), 7)
        self.assertTrue(all(not path.exists()
                            for path in plan["report_paths"]))
        self.assertFalse(plan["summary_path"].exists())

    def test_dry_run_cannot_call_network_or_write_files(self):
        args = ["runner", "--backlog", str(self.backlog),
                "--private-source-config", str(self.sources),
                "--private-output-dir", str(self.outputs),
                "--day", DAY.isoformat()]
        buffer = io.StringIO()
        with patch.object(sys, "argv", args), \
                patch.object(campaign, "execute_campaign",
                             side_effect=AssertionError("must stay offline")), \
                redirect_stdout(buffer):
            campaign.main()
        result = json.loads(buffer.getvalue())
        self.assertEqual(result["mode"], "dry_run_only")
        self.assertEqual(result["batch_count"], 7)
        self.assertEqual(result["public_writes"], 0)
        self.assertEqual(list(self.outputs.iterdir()), [])

    def test_no_live_key_is_fail_closed_before_any_batch(self):
        plan = self.plan()
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "read_key_required"):
                campaign.execute_campaign(
                    plan, self.backlog, self.sources, self.outputs, DAY,
                    runner=lambda *a, **k: self.fail("runner invoked"))
        self.assertEqual(list(self.outputs.iterdir()), [])

    def test_live_run_calls_exactly_seven_batches_then_private_rollup(self):
        plan = self.plan()
        calls = []
        def fake_runner(args, **kwargs):
            self.assertEqual(kwargs["stdout"], campaign.subprocess.DEVNULL)
            self.assertEqual(kwargs["stderr"], campaign.subprocess.DEVNULL)
            self.assertFalse(kwargs["check"])
            self.assertIn("--live-probe", args)
            self.assertIn("--shared-location-evidence", args)
            self.assertNotIn("push", args)
            self.assertNotIn("upload-artifact", args)
            calls.append(int(args[args.index("--batch-index") + 1]))
            report = Path(args[args.index("--output-private-report") + 1])
            report.write_text("{}", encoding="utf-8")
            return SimpleNamespace(returncode=0)
        fake_summary = {
            "batches_complete": True, "batches_examined": 7,
            "unknown_unique_venues": 79,
            "unknown_distinct_candidate_sessions": 138,
            "full_live_scan": True,
            "reusable_location_proof_venues_private": 0,
            "candidate_sessions_on_proven_places_not_published": 0,
            "publication_ready": False, "public_writes": 0,
        }
        with patch.dict(os.environ, {"OPENAGENDA_READ_KEY": "test-key"}), \
                patch.object(campaign, "rollup_private_batches",
                             return_value=fake_summary) as rollup:
            result = campaign.execute_campaign(
                plan, self.backlog, self.sources, self.outputs, DAY,
                runner=fake_runner)
        self.assertEqual(calls, list(range(7)))
        self.assertEqual(rollup.call_count, 1)
        self.assertEqual(result, fake_summary)
        self.assertEqual(json.loads(plan["summary_path"].read_text()),
                         fake_summary)
        self.assertEqual(plan["summary_path"].stat().st_mode & 0o077, 0)

    def test_failed_batch_never_writes_summary_or_starts_next_batch(self):
        plan = self.plan()
        called = []
        def failing(args, **kwargs):
            called.append(args[args.index("--batch-index") + 1])
            return SimpleNamespace(returncode=1)
        with patch.dict(os.environ, {"OPENAGENDA_READ_KEY": "test-key"}):
            with self.assertRaisesRegex(RuntimeError, "batch_failed"):
                campaign.execute_campaign(
                    plan, self.backlog, self.sources, self.outputs, DAY,
                    runner=failing)
        self.assertEqual(called, ["0"])
        self.assertFalse(plan["summary_path"].exists())

    def test_private_snapshot_changed_mid_campaign_fails_closed(self):
        plan = self.plan()
        def tampering(args, **kwargs):
            report = Path(args[args.index("--output-private-report") + 1])
            report.write_text("{}", encoding="utf-8")
            self.backlog.write_text('[{"changed": true}]', encoding="utf-8")
            return SimpleNamespace(returncode=0)
        with patch.dict(os.environ, {"OPENAGENDA_READ_KEY": "test-key"}):
            with self.assertRaisesRegex(ValueError, "snapshot_changed"):
                campaign.execute_campaign(
                    plan, self.backlog, self.sources, self.outputs, DAY,
                    runner=tampering)
        self.assertFalse(plan["summary_path"].exists())

    def test_existing_report_or_summary_blocks_overwrite(self):
        for name in ("venue-batch-2026-11-20-0.json",
                     "venue-campaign-2026-11-20.json"):
            path = self.outputs / name
            path.write_text("already exists", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "already_exists"):
                self.plan()
            path.unlink()

    def test_reject_public_checkout_and_world_readable_destinations(self):
        with self.assertRaisesRegex(ValueError, "invalid_private_input_path"):
            campaign._private_file(
                ROOT / "scripts" / "ptitesondes_private_venue_campaign.py",
                campaign.MAX_BACKLOG_BYTES)
        os.chmod(self.outputs, 0o755)
        with self.assertRaisesRegex(ValueError, "invalid_private_output_directory"):
            self.plan()
        os.chmod(self.outputs, 0o700)

    def test_symlink_and_malformed_source_rejected(self):
        link = self.inputs / "symlink.json"
        try:
            link.symlink_to(self.sources)
        except OSError:
            self.skipTest("symlinks unsupported")
        with self.assertRaisesRegex(ValueError, "invalid_private_input_path"):
            campaign.prepare_campaign(
                self.backlog, link, self.outputs, DAY)
        link.unlink()
        self.sources.write_text('{"schema":"wrong","openagenda_agendas":[]}')
        with self.assertRaisesRegex(ValueError, "invalid_private_campaign_input"):
            self.plan()


if __name__ == "__main__":
    unittest.main()
