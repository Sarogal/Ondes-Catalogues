"""Offline runner durability: no writes by default, 0600 atomic state,
new segments auto-discovered, no static source registry or public publication.
"""
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock
import io
import json
import os
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
from ptitesondes_private_national_rotation_runner import (
    run_segment_file, run_all_discovered_segments,
    _state_path, _safe_existing_file, SCHEMA,
)
from ptitesondes_national_segment_rotation_bridge import SCHEMA as BRIDGE_SCHEMA
from test_ptitesondes_national_segment_rotation_bridge import (
    DAY, KEY, segment, fake_rotation,
    event_lead, source_event, event_page, dila, MUNICIPAL, SOURCE,
)

HOME = "https://www.ville-les-bois.fr/"


class PrivateNationalRunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.campaign = self.base / "private-campaign"
        self.private = self.base / "private-state"
        self.campaign.mkdir(mode=0o700)
        self.private.mkdir(mode=0o700)

    def put(self, name="agenda-0000-segment-0000.json", document=None):
        path = self.campaign / name
        path.write_text(json.dumps(
            document if document is not None else segment(),
            ensure_ascii=False), encoding="utf-8")
        return path

    def snapshot(self, source):
        path, digest = _state_path(
            self.private, source.read_bytes(), DAY)
        self.assertTrue(path.exists())
        self.assertEqual(path.stat().st_mode & 0o077, 0)
        obj = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(obj["source_file_sha256"], digest)
        return obj

    def test_dry_run_has_no_network_and_creates_no_state(self):
        self.put()
        reader = Mock(side_effect=AssertionError("network forbidden"))
        out = run_all_discovered_segments(
            self.campaign, self.private, DAY,
            execute_live=False, rotator=reader)
        self.assertEqual(out["mode"], "dry_run_no_network_or_writes")
        self.assertEqual(out["segment_reports_detected"], 1)
        self.assertFalse(list(self.private.iterdir()))
        reader.assert_not_called()

    def test_one_segment_restarts_from_private_atomic_cursor(self):
        source = self.put()
        first = run_segment_file(
            source, self.private, DAY, execute_live=True,
            key=KEY, event_budget=2, rotator=fake_rotation)
        self.assertEqual(first["events_considered"], 2)
        persisted = self.snapshot(source)
        self.assertEqual(persisted["serial"], 1)
        self.assertEqual(persisted["bridge_state"]["next_index"], 2)
        second = run_segment_file(
            source, self.private, DAY, execute_live=True,
            key=KEY, event_budget=2, rotator=fake_rotation)
        self.assertEqual(second["events_considered"], 2)
        persisted = self.snapshot(source)
        self.assertEqual(persisted["serial"], 2)
        self.assertEqual(persisted["bridge_state"]["next_index"], 0)
        self.assertEqual(persisted["bridge_state"]["full_passes_completed"], 1)
        self.assertEqual(persisted["last_cycle"]["status"],
                         "national_segment_full_discovery_completed_today")
        self.assertFalse(persisted["last_cycle"]["publication_ready"])
        self.assertEqual(persisted["last_cycle"]["public_writes"], 0)

    def test_cli_discovers_new_segment_files_not_organizer_allowlist(self):
        self.put("agenda-0000-segment-0000.json")
        out = run_all_discovered_segments(
            self.campaign, self.private, DAY, execute_live=True,
            key=KEY, segment_budget=1, event_budget=2,
            rotator=fake_rotation)
        self.assertEqual(out["segment_reports_detected"], 1)
        new = segment(known=(910,), unknown=(911,))
        new["campaign_meta"]["agenda_index"] = 1
        self.put("agenda-0001-segment-0000.json", new)
        next_cycle = run_all_discovered_segments(
            self.campaign, self.private, DAY, execute_live=True,
            key=KEY, segment_budget=2, event_budget=2,
            rotator=fake_rotation)
        self.assertEqual(next_cycle["segment_reports_detected"], 2)
        self.assertEqual(next_cycle["segment_reports_examined"], 2)
        self.assertEqual(next_cycle["segment_reports_held"], 0)
        self.assertEqual(next_cycle["event_slots_examined"], 4)

    def test_malformed_segment_is_held_without_starving_valid_segment(self):
        wrong = self.put("agenda-0000-segment-0000.json")
        wrong.write_text('{"invalid":"upstream"}', encoding="utf-8")
        good = segment(known=(919,), unknown=(920,))
        good["campaign_meta"]["agenda_index"] = 1
        self.put("agenda-0001-segment-0000.json", good)
        out = run_all_discovered_segments(
            self.campaign, self.private, DAY,
            execute_live=True, key=KEY, segment_budget=2,
            rotator=fake_rotation)
        self.assertEqual(out["segment_reports_examined"], 2)
        self.assertEqual(out["segment_reports_held"], 1)
        self.assertEqual(out["event_slots_examined"], 2)
        self.assertFalse(out["publication_ready"])

    def test_private_input_workspace_cannot_be_repository_or_shared(self):
        path = self.put()
        os.chmod(self.private, 0o755)
        with self.assertRaises(ValueError):
            run_segment_file(path, self.private, DAY, execute_live=False)
        os.chmod(self.private, 0o700)
        with self.assertRaises(ValueError):
            run_segment_file(path, self.campaign, DAY, execute_live=True,
                             key=KEY, rotator=fake_rotation)

    def test_stored_private_snapshot_is_not_trusted_if_forged(self):
        source = self.put()
        run_segment_file(source, self.private, DAY,
                         execute_live=True, key=KEY, rotator=fake_rotation)
        target, _ = _state_path(self.private, source.read_bytes(), DAY)
        snapshot = json.loads(target.read_text(encoding="utf-8"))
        snapshot["last_cycle"]["publication_ready"] = True
        target.write_text(json.dumps(snapshot), encoding="utf-8")
        with self.assertRaises(ValueError):
            run_segment_file(source, self.private, DAY,
                             execute_live=True, key=KEY,
                             rotator=fake_rotation)

    def test_independent_modified_report_creates_separate_cursor_not_replay(self):
        source = self.put()
        run_segment_file(source, self.private, DAY, execute_live=True,
                         key=KEY, rotator=fake_rotation)
        first = list(self.private.glob("national-segment-*.json"))
        self.assertEqual(len(first), 1)
        changed = segment()
        changed["event_leads"][0]["title"] = "Une autre histoire sonore"
        source.write_text(json.dumps(changed), encoding="utf-8")
        run_segment_file(source, self.private, DAY, execute_live=True,
                         key=KEY, rotator=fake_rotation)
        self.assertEqual(
            len(list(self.private.glob("national-segment-*.json"))), 2)
        self.assertEqual(self.snapshot(source)["serial"], 1)

    def test_live_mode_requires_public_read_key_no_silent_fallback(self):
        source = self.put()
        with self.assertRaises(ValueError):
            run_segment_file(source, self.private, DAY,
                             execute_live=True, key="",
                             rotator=fake_rotation)
        self.assertFalse(list(self.private.iterdir()))

    def test_no_private_session_dates_or_urls_returned_in_public_summary(self):
        source = self.put()
        out = run_segment_file(source, self.private, DAY,
                               execute_live=True, key=KEY,
                               rotator=fake_rotation)
        text = json.dumps(out)
        for forbidden in ("2026-12-05", "Ville-les-Bois",
                          "Création artistique", "http", KEY):
            self.assertNotIn(forbidden, text)
        self.assertEqual(out["public_writes"], 0)

    def test_live_mock_pipeline_rechecks_unknown_organizer_per_segment(self):
        event = event_lead()
        document = segment(known=(), unknown=(event["event_uid"],))
        document["agenda_uid"] = event["agenda_uid"]
        document["agenda_slug"] = event["agenda_slug"]
        row = document["unclassified_editorial_research_only"][0]
        row.update(event)
        row["editorial_category_proposal"] = None
        row["review_state"] = (
            "unknown_activity_requires_official_editorial_evidence")
        source = self.put(document=document)
        pages = {
            HOME: ("<html><body><a href='agenda/sorties'>"
                   "Sorties jeunesse</a></body></html>"),
            MUNICIPAL: event_page(event, True),
            SOURCE: event_page(event, False),
        }
        options = {
            "directory_reader": lambda city: dila(),
            "html_reader": lambda url: pages[url],
            "oa_agenda_reader": lambda uid, key: {
                "uid": event["agenda_uid"], "slug": event["agenda_slug"]},
            "oa_event_reader": lambda uid, eid, key: source_event(event),
            "pages_per_cycle": 1, "sources_per_cycle": 1,
        }
        a = run_segment_file(
            source, self.private, DAY, execute_live=True,
            key=KEY, rotator_options=options)
        self.assertEqual(a["events_considered"], 1)
        b = run_segment_file(
            source, self.private, DAY, execute_live=True,
            key=KEY, rotator_options=options)
        self.assertEqual(b["events_considered"], 1)
        snapshot = self.snapshot(source)
        self.assertEqual(snapshot["last_cycle"]["status"],
                         "national_segment_full_discovery_completed_today")
        details = snapshot["last_cycle"]["private_reviews"][0]["research"]
        self.assertEqual(details["source_candidates_examined"], 1)
        self.assertTrue(all(
            s["three_source_exact_claims"] for s
            in details["private_research_reviews"][0][
                "diagnostic"]["private_session_diagnostics"]))
        self.assertFalse(details["publication_ready"])


if __name__ == "__main__":
    unittest.main()
