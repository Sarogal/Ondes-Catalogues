"""Offline continuity and no-publication tests for isolated national observation."""
from datetime import date, timedelta
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from ptitesondes_national_shadow_observation import (
    CONTROLLER_SCHEMA, REPORT_RE, BATCH_RE, available_index_reports,
    controller_read, run_observation, recover_pending_index,
)
from ptitesondes_private_national_rotation_runner import _write_atomic_private
from ptitesondes_openagenda_public_agenda_index import SCHEMA as INDEX_SCHEMA

DAY = date(2026, 11, 21)
KEY = "oa_pk_public_key_for_offline_testing_only"


def index_doc(uid=778899):
    return {
        "schema": INDEX_SCHEMA,
        "mode": "private_index_readonly_discovery_not_admission",
        "new_agenda_candidates": [{
            "agenda_uid": uid, "agenda_slug": f"unknown-agenda-{uid}",
            "agenda_title": "Scène découverte sans liste blanche",
            "source_identity_only": True,
            "owner_verified": False, "organiser_verified": False,
            "rights_reviewed": False, "publisher_enabled": False,
        }],
        "next_cursor": [1, uid],
        "index_pass_exhausted": False,
        "publication_ready": False, "public_writes": 0,
    }


def segment_summary(*args, **kwargs):
    return {"mode": "private_research_only", "public_writes": 0,
            "publication_ready": False,
            "segment_reports_examined": 2, "segment_reports_held": 1,
            "event_slots_examined": 5}


def campaign_summary(*args, **kwargs):
    return {"public_writes": 0, "publication_ready": False,
            "finished_index_batch": False}


class NationalShadowObservationTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cfg = self.root / "sources.json"
        self.cfg.write_text(json.dumps({
            "schema": "ptitesondes.sources.v1",
            "openagenda_agendas": [1234, 4567]}), encoding="utf-8")
        self.cfg.chmod(0o600)
        self.campaign = Mock(side_effect=campaign_summary)
        self.segments = Mock(side_effect=segment_summary)

    def invoke(self, day=DAY, batch_id="run1", *, index=None, live=True):
        index = index or Mock(return_value=index_doc())
        result = run_observation(
            self.cfg, self.root, day, batch_id,
            execute_live=live, key=KEY,
            index_reader=index, campaign_runner=self.campaign,
            segment_runner=self.segments)
        return result, index

    def test_default_dry_run_no_network_or_private_writes(self):
        report, reader = self.invoke(live=False)
        self.assertEqual(report["mode"], "dry_run_no_network_or_writes")
        self.assertFalse((self.root / "controller.json").exists())
        self.assertFalse((self.root / "index").exists())
        reader.assert_not_called()
        self.campaign.assert_not_called()
        self.segments.assert_not_called()

    def test_first_live_batch_is_read_only_and_resumable(self):
        result, reader = self.invoke()
        self.assertEqual(result["new_index_census"], 1)
        self.assertEqual(result["index_batches_advanced"], 1)
        self.assertEqual(result["segments_examined"], 2)
        self.assertEqual(result["event_slots_examined"], 5)
        self.assertFalse(result["publication_ready"])
        self.assertFalse(result["publisher_connected"])
        self.assertEqual(result["public_writes"], 0)
        self.assertEqual(controller_read(self.root / "controller.json")["invocations"], 1)
        self.assertEqual(len(available_index_reports(self.root / "index" / "reports")), 1)
        reader.assert_called_once()
        self.assertEqual(self.campaign.call_args.args[0]["day"], DAY)
        self.assertEqual(self.segments.call_args.args[2], DAY)

    def test_next_day_retains_previous_batch_without_rescanning(self):
        self.invoke()
        old = list((self.root / "index" / "reports").iterdir())[0]
        original = old.read_bytes()
        result, reader = self.invoke(day=DAY + timedelta(days=1),
                                     batch_id="run2")
        self.assertEqual(result["new_index_census"], 0)
        self.assertEqual(result["stored_index_batches"], 1)
        reader.assert_not_called()
        self.assertEqual(old.read_bytes(), original)
        self.assertEqual(self.segments.call_args.args[2], DAY)

    def test_later_new_report_joins_rotation_without_erasing_old(self):
        self.invoke()
        original = list((self.root / "index" / "reports").iterdir())[0]
        state = {"schema": CONTROLLER_SCHEMA, "invocations": 12,
                 "next_batch_index": 0}
        _write_atomic_private(self.root / "controller.json",
                              (json.dumps(state) + "\n").encode())
        index = Mock(return_value=index_doc(778900))
        result, _ = self.invoke(day=DAY + timedelta(days=1),
                                batch_id="run2", index=index)
        self.assertEqual(result["new_index_census"], 1)
        self.assertEqual(result["stored_index_batches"], 2)
        self.assertEqual(result["index_batches_examined"], 2)
        self.assertTrue(original.is_file())
        self.assertEqual(self.segments.call_args.args[2], DAY + timedelta(days=1))

    def test_invalid_older_report_is_held_not_removed_or_starving_new(self):
        self.invoke()
        invalid = self.root / "index" / "reports" / "index-2026-11-20-bad.json"
        invalid.write_text("{}", encoding="utf-8")
        invalid.chmod(0o600)
        self.campaign.reset_mock()
        out, _ = self.invoke(day=DAY, batch_id="run2")
        self.assertEqual(out["stored_index_batches"], 2)
        self.assertGreaterEqual(out["held_for_research"], 1)
        self.assertTrue(invalid.exists())
        self.assertGreaterEqual(self.campaign.call_count, 1)

    def test_empty_oversized_and_invalid_date_index_reports_do_not_starve_others(self):
        self.invoke()
        report_dir = self.root / "index" / "reports"
        for name, raw in (
            ("index-2026-11-19-empty.json", b""),
            ("index-2026-11-18-too_big.json", b" " * 800001),
            ("index-2026-99-99-bad_date.json", b"{}"),
        ):
            path = report_dir / name
            path.write_bytes(raw)
            path.chmod(0o600)
        self.campaign.reset_mock()
        first, _ = self.invoke(batch_id="fresh")
        second, _ = self.invoke(batch_id="fresher")
        self.assertEqual(first["stored_index_batches"], 4)
        self.assertGreaterEqual(first["held_for_research"], 1)
        self.assertEqual(second["stored_index_batches"], 4)
        # Two bounded fair rotations, not one unbounded catch-up.
        self.assertEqual(self.campaign.call_count, 1)

    def test_crash_after_report_before_cursor_is_recovered_without_requery(self):
        index = Mock(return_value=index_doc())
        with patch("ptitesondes_national_shadow_observation._write_state_atomic",
                   side_effect=OSError("injected power loss")):
            with self.assertRaises(OSError):
                self.invoke(index=index)
        pending = self.root / "index" / "pending-index-transaction.json"
        self.assertTrue(pending.exists())
        self.assertEqual(len(available_index_reports(
            self.root / "index" / "reports")), 1)
        self.assertFalse((self.root / "index" / "cursor.json").exists())
        resumed, reader = self.invoke(batch_id="after_restart",
                                      index=Mock(return_value=index_doc(99)))
        reader.assert_not_called()
        self.assertEqual(resumed["stored_index_batches"], 1)
        self.assertEqual(resumed["new_index_census"], 0)
        self.assertFalse(pending.exists())
        self.assertEqual(json.loads((self.root / "index" / "cursor.json")
                                    .read_text())["after"], [1, 778899])

    def test_crash_before_report_retries_original_cursor(self):
        index = Mock(return_value=index_doc())
        with patch("ptitesondes_national_shadow_observation._write_new_report",
                   side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                self.invoke(index=index)
        pending = self.root / "index" / "pending-index-transaction.json"
        self.assertTrue(pending.exists())
        self.assertEqual(len(available_index_reports(
            self.root / "index" / "reports")), 0)
        retried, reader = self.invoke(batch_id="recovery",
                                      index=Mock(return_value=index_doc()))
        reader.assert_called_once()
        self.assertEqual(retried["new_index_census"], 1)
        self.assertFalse(pending.exists())

    def test_tampered_index_transaction_refuses_cursor_advance(self):
        index = Mock(return_value=index_doc())
        with patch("ptitesondes_national_shadow_observation._write_state_atomic",
                   side_effect=OSError("interruption")):
            with self.assertRaises(OSError):
                self.invoke(index=index)
        stored = next((self.root / "index" / "reports").iterdir())
        stored.write_text('{"altered":true}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError,
                                    "index_transaction_report_digest_mismatch"):
            recover_pending_index(self.root / "index",
                                  self.root / "index" / "reports")
        self.assertFalse((self.root / "index" / "cursor.json").exists())

    def test_rejects_invalid_or_unsafe_parameters(self):
        self.assertIsNone(REPORT_RE.fullmatch("index-2026-11-21-segment.json.bak"))
        self.assertIsNone(BATCH_RE.fullmatch("bad/segment"))
        with self.assertRaises(ValueError):
            run_observation(self.cfg, self.root, DAY, "bad/segment")
        with self.assertRaises(ValueError):
            run_observation(self.cfg, self.root, DAY, "good",
                            execute_live=True, key="")

    def test_private_results_have_no_event_id_venue_or_source_url(self):
        out, _ = self.invoke()
        dumped = json.dumps(out, ensure_ascii=False)
        self.assertNotIn("unknown-agenda", dumped)
        self.assertNotIn("778899", dumped)
        self.assertNotIn("https://", dumped)
        self.assertNotIn(KEY, dumped)

    def test_workflow_is_manual_only_for_live_and_never_replaces_active_workflow(self):
        workflow = (ROOT / ".github/workflows/ptitesondes-national-shadow-observation.yml")
        content = workflow.read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", content)
        self.assertIn("github.event_name == 'workflow_dispatch'", content)
        self.assertIn("github.ref == 'refs/heads/main'", content)
        self.assertNotIn("  schedule:", content)
        self.assertNotIn("deploy-pages", content)
        self.assertNotIn("docs/ptitesondes/sorties.json", content)
        self.assertIn("ptitesondes-public-private-intake", content)


if __name__ == "__main__":
    unittest.main()
