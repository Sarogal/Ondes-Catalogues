"""Offline private campaign tests: bounded scans, checkpoints, dry-run safety."""
from datetime import date
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from ptitesondes_private_national_event_campaign import (
    SCHEMA, MAX_STEPS, plan_campaign, run_campaign, load_checkpoint,
    STATE_SCHEMA, main,
)
from ptitesondes_openagenda_public_agenda_index import SCHEMA as INDEX_SCHEMA
from ptitesondes_openagenda_national_event_research import SCHEMA as EVENT_SCHEMA

DAY = date(2026, 11, 21)
KEY = "oa_pk_public_research_key_from_tests"
DIGEST = "a" * 64


def index(n=2):
    return {
        "schema": INDEX_SCHEMA,
        "mode": "private_index_readonly_discovery_not_admission",
        "publication_ready": False, "public_writes": 0,
        "new_agenda_candidates": [
            {"agenda_uid": 70000 + i, "agenda_slug": f"agenda-{i}",
             "source_identity_only": True, "publisher_enabled": False}
            for i in range(n)
        ],
    }


def segment(agenda, *, after=None, done=True):
    return {
        "schema": EVENT_SCHEMA, "mode": "private_research_event_leads_only",
        "agenda_uid": agenda["agenda_uid"],
        "agenda_slug": agenda["agenda_slug"],
        "counts": {"pages_read": 3, "public_event_uids_seen": 2},
        "event_leads": [{
            "event_uid": 9001, "title": "Concert jeune public fictif",
            "venue_unverified": "Place sans numéro",
            "publication_ready": False, "public_writes": 0,
        }],
        "no_publisher_bridge": True,
        "next_cursor": None if done else after,
        "agenda_scan_complete": done,
        "publication_ready": False, "public_writes": 0,
    }


class PrivateNationalEventCampaignTests(unittest.TestCase):
    def test_unknown_editorial_hints_are_private_and_cannot_forge_admission(self):
        from ptitesondes_private_national_event_campaign import _validate_segment
        agenda = index(n=1)["new_agenda_candidates"][0]
        base = segment(agenda)
        base["campaign_meta"] = {
            "source_sha256": DIGEST, "scan_day": str(DAY),
            "agenda_index": 0, "segment": 0, "start_cursor": None,
        }
        hint = {
            "agenda_uid": agenda["agenda_uid"],
            "agenda_slug": agenda["agenda_slug"],
            "event_uid": 9002, "title": "Nouvelle forme sonore jeunesse",
            "editorial_category_proposal": None,
            "review_state": "unknown_activity_requires_official_editorial_evidence",
            "source_organizer_independently_verified": False,
            "rights_reviewed": False, "venue_verified": False,
            "publisher_connected": False, "publication_ready": False,
            "public_writes": 0,
        }
        base["unclassified_editorial_research_only"] = [hint]
        self.assertIsNone(_validate_segment(base, agenda, base["campaign_meta"]))
        for modified in (
            dict(hint, rights_reviewed=True),
            dict(hint, publication_ready=True),
            dict(hint, publisher_connected=True),
            dict(hint, source_organizer_independently_verified=True),
            dict(hint, editorial_category_proposal="concert"),
            dict(hint, public_writes=False),
            dict(hint, agenda_uid=1),
            dict(hint, event_uid=9001),
        ):
            with self.subTest(modified=modified), self.assertRaises(ValueError):
                forged = dict(base, unclassified_editorial_research_only=[modified])
                _validate_segment(forged, agenda, forged["campaign_meta"])

    def test_unclassified_research_is_not_a_new_publisher_addition(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = plan_campaign(index(n=1), DIGEST, DAY, root, steps=1)
            def explorer(agenda, key, today, *, after):
                report = segment(agenda)
                report["unclassified_editorial_research_only"] = [{
                    "agenda_uid": agenda["agenda_uid"],
                    "agenda_slug": agenda["agenda_slug"],
                    "event_uid": 91234, "title": "Inédit jeunesse",
                    "editorial_category_proposal": None,
                    "review_state": "unknown_activity_requires_official_editorial_evidence",
                    "source_organizer_independently_verified": False,
                    "rights_reviewed": False, "venue_verified": False,
                    "publisher_connected": False,
                    "publication_ready": False, "public_writes": 0,
                }]
                return report
            report = run_campaign(plan, public_key=KEY, explorer=explorer)
            self.assertEqual(report["segments_examined"], 1)
            files = list(root.glob("agenda-*-segment-*.json"))
            self.assertEqual(len(files), 1)
            stored = json.loads(files[0].read_text(encoding="utf-8"))
            self.assertEqual(len(stored["unclassified_editorial_research_only"]), 1)
            self.assertFalse(stored["unclassified_editorial_research_only"][0]["publication_ready"])
            self.assertEqual(len(stored["event_leads"]), 1)
            self.assertNotIn("additions", stored)
            self.assertEqual(report["public_writes"], 0)

    def test_three_segments_two_agendas_progress_and_finish(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = plan_campaign(index(), DIGEST, DAY, root, steps=3)
            seen = []
            def explorer(agenda, key, today, *, after):
                seen.append((agenda["agenda_uid"], after))
                if len(seen) == 1:
                    return segment(agenda, after=["000001"], done=False)
                return segment(agenda)
            outcome = run_campaign(plan, public_key=KEY, explorer=explorer)
            self.assertEqual(seen, [
                (70000, None), (70000, ["000001"]), (70001, None)
            ])
            self.assertEqual(outcome["segments_examined"], 3)
            self.assertEqual(outcome["next_agenda_index"], 2)
            self.assertTrue(outcome["finished_index_batch"])
            self.assertEqual(outcome["public_writes"], 0)
            self.assertFalse(outcome["publication_ready"])
            self.assertEqual(len(list(root.glob("agenda-*-segment-*.json"))), 3)
            state = load_checkpoint(root, DIGEST, DAY, 2)
            self.assertEqual(state["next_agenda_index"], 2)
            self.assertIsNone(state["event_after"])
            self.assertEqual(state["segment"], 0)
            self.assertFalse((root / ".national-event-campaign.lock").exists())

    def test_resume_from_cursor_next_execution_without_restarting_agenda(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            def first(agenda, key, today, *, after):
                self.assertIsNone(after)
                return segment(agenda, after=["0", "0000006"], done=False)
            result = run_campaign(
                plan_campaign(index(), DIGEST, DAY, root, steps=1),
                public_key=KEY, explorer=first)
            self.assertEqual(result["next_agenda_index"], 0)
            seen = []
            def resume(agenda, key, today, *, after):
                seen.append(after)
                return segment(agenda)
            result = run_campaign(
                plan_campaign(index(), DIGEST, DAY, root, steps=1),
                public_key=KEY, explorer=resume)
            self.assertEqual(seen, [["0", "0000006"]])
            self.assertEqual(result["next_agenda_index"], 1)

    def test_stale_prepared_plan_reloads_checkpoint_inside_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stale_plan = plan_campaign(index(), DIGEST, DAY, root, steps=1)
            first = run_campaign(
                plan_campaign(index(), DIGEST, DAY, root, steps=1),
                public_key=KEY,
                explorer=lambda agenda, key, day, **kw: segment(agenda))
            self.assertEqual(first["next_agenda_index"], 1)
            seen = []
            def scan_second(agenda, key, day, *, after):
                seen.append((agenda["agenda_uid"], after))
                return segment(agenda)
            second = run_campaign(stale_plan, public_key=KEY,
                                  explorer=scan_second)
            self.assertEqual(seen, [(70001, None)])
            self.assertEqual(second["segments_examined"], 1)
            self.assertEqual(second["segments_recovered_from_private_report"], 0)
            self.assertEqual(second["next_agenda_index"], 2)
            self.assertEqual(load_checkpoint(root, DIGEST, DAY, 2)["next_agenda_index"], 2)

    def test_stale_plan_rejects_changed_checkpoint_under_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stale_plan = plan_campaign(index(), DIGEST, DAY, root, steps=1)
            run_campaign(stale_plan, public_key=KEY,
                         explorer=lambda agenda, key, day, **kw: segment(agenda))
            path = root / "national-event-checkpoint.json"
            checkpoint = json.loads(path.read_text(encoding="utf-8"))
            checkpoint["source_sha256"] = "b" * 64
            path.write_text(json.dumps(checkpoint), encoding="utf-8")
            scan = Mock(side_effect=AssertionError("Never scan with a stale plan"))
            with self.assertRaisesRegex(ValueError, "cursor_or_source_mismatch"):
                run_campaign(stale_plan, public_key=KEY, explorer=scan)
            scan.assert_not_called()
            self.assertFalse((root / ".national-event-campaign.lock").exists())

    def test_changed_source_or_day_never_reuses_cursor(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_campaign(plan_campaign(index(), DIGEST, DAY, root, steps=1),
                         public_key=KEY,
                         explorer=lambda agenda, key, day, **kw:
                         segment(agenda, after=["1"], done=False))
            with self.assertRaisesRegex(ValueError, "cursor_or_source_mismatch"):
                plan_campaign(index(), "b" * 64, DAY, root)
            with self.assertRaisesRegex(ValueError, "cursor_or_source_mismatch"):
                plan_campaign(index(), DIGEST, date(2026, 11, 22), root)

    def test_corrupted_segment_cursor_relationship_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            initial = plan_campaign(index(), DIGEST, DAY, root, steps=1)
            run_campaign(initial, public_key=KEY,
                         explorer=lambda agenda, key, day, **kw: segment(agenda))
            path = root / "national-event-checkpoint.json"
            good = json.loads(path.read_text(encoding="utf-8"))
            for segment_num, cursor in ((0, ["abc"]), (1, None)):
                with self.subTest(segment=segment_num, cursor=cursor):
                    invalid = {**good, "segment": segment_num,
                               "event_after": cursor}
                    path.write_text(json.dumps(invalid), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, "cursor_or_source_mismatch"):
                        plan_campaign(index(), DIGEST, DAY, root, steps=1)

    def test_stale_duplicate_segment_fails_closed_without_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "agenda-0000-segment-0000.json").write_text("collision")
            explorer = Mock(side_effect=AssertionError("must not fetch"))
            with self.assertRaisesRegex(ValueError, "existing_private_segment"):
                run_campaign(plan_campaign(index(), DIGEST, DAY, root),
                             public_key=KEY, explorer=explorer)
            explorer.assert_not_called()
            self.assertFalse((root / ".national-event-campaign.lock").exists())

    def test_crash_after_report_write_recovers_exact_segment_without_fetch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = index()["new_agenda_candidates"][0]
            report = segment(candidate, after=["000001"], done=False)
            report["campaign_meta"] = {
                "source_sha256": DIGEST, "scan_day": DAY.isoformat(),
                "agenda_index": 0, "segment": 0, "start_cursor": None,
            }
            (root / "agenda-0000-segment-0000.json").write_text(
                json.dumps(report), encoding="utf-8")
            explorer = Mock(side_effect=AssertionError(
                "No network reread for validated crash-recovery report"))
            result = run_campaign(
                plan_campaign(index(), DIGEST, DAY, root, steps=1),
                public_key=KEY, explorer=explorer)
            explorer.assert_not_called()
            self.assertEqual(result["segments_examined"], 0)
            self.assertEqual(result["segments_recovered_from_private_report"], 1)
            state = load_checkpoint(root, DIGEST, DAY, 2)
            self.assertEqual(state["next_agenda_index"], 0)
            self.assertEqual(state["segment"], 1)
            self.assertEqual(state["event_after"], ["000001"])

    def test_crash_recovery_cannot_accept_other_source_or_cursor(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = index()["new_agenda_candidates"][0]
            report = segment(candidate, after=["1"], done=False)
            report["campaign_meta"] = {
                "source_sha256": "x" * 64,
                "scan_day": DAY.isoformat(), "agenda_index": 0,
                "segment": 0, "start_cursor": None,
            }
            (root / "agenda-0000-segment-0000.json").write_text(
                json.dumps(report), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "existing_private_segment_requires_recovery"):
                run_campaign(
                    plan_campaign(index(), DIGEST, DAY, root, steps=1),
                    public_key=KEY,
                    explorer=lambda *a, **kw: self.fail("Unsafe network retry"))
            self.assertFalse((root / "national-event-checkpoint.json").exists())

    def test_reject_mismatched_or_publishing_segment_before_file_write(self):
        for changed in (
            {"agenda_uid": 999},
            {"agenda_slug": "other"},
            {"publication_ready": True},
            {"public_writes": 1},
            {"event_leads": [{}] * 61},
            {"event_leads": [{"publication_ready": True, "public_writes": 1}]},
            {"event_leads": [{"publication_ready": False, "public_writes": 9}]},
            {"no_publisher_bridge": False},
            {"counts": {"pages_read": 0, "public_event_uids_seen": 2}},
            {"counts": {"pages_read": 3, "public_event_uids_seen": 0}},
            {"agenda_scan_complete": True, "next_cursor": ["1"]},
        ):
            with self.subTest(changed=changed):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    def malicious(agenda, key, day, **kw):
                        return {**segment(agenda), **changed}
                    with self.assertRaisesRegex(ValueError, "invalid_private_agenda_segment"):
                        run_campaign(plan_campaign(index(), DIGEST, DAY, root),
                                     public_key=KEY, explorer=malicious)
                    self.assertFalse((root / "national-event-checkpoint.json").exists())
                    self.assertEqual(list(root.glob("agenda-*.json")), [])

    def test_only_public_read_key_and_one_process_are_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = plan_campaign(index(), DIGEST, DAY, root)
            with self.assertRaisesRegex(ValueError, "private_oa_public_read_key"):
                run_campaign(plan, public_key="oa_sk_secret")
            (root / ".national-event-campaign.lock").touch()
            with self.assertRaises(FileExistsError):
                run_campaign(plan, public_key=KEY)
            self.assertTrue((root / ".national-event-campaign.lock").exists())

    def test_bad_index_size_and_step_bounds_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            for size, steps in ((161, 2), (2, 9), (2, 0)):
                with self.subTest(size=size, steps=steps):
                    with self.assertRaises(ValueError):
                        plan_campaign(index(size), DIGEST, DAY, Path(tmp), steps=steps)

    def test_valid_empty_index_is_a_successful_completed_campaign(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = plan_campaign(index(0), DIGEST, DAY, Path(tmp), steps=2)
            network = Mock(side_effect=AssertionError(
                "Zero unknown agendas must never contact OpenAgenda"))
            result = run_campaign(plan, public_key=KEY, explorer=network)
            network.assert_not_called()
            self.assertEqual(result["segments_examined"], 0)
            self.assertEqual(result["total_agendas"], 0)
            self.assertTrue(result["finished_index_batch"])
            self.assertEqual(result["public_writes"], 0)

    def test_dry_run_does_not_create_private_state_or_fetch_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "input.json"
            src.write_text(json.dumps(index()), encoding="utf-8")
            with patch.object(sys, "argv", [
                "prog", "--private-agenda-index-report", str(src),
                "--private-output-dir", str(root), "--day", str(DAY),
            ]), patch("ptitesondes_private_national_event_campaign.scan_agenda",
                       side_effect=AssertionError("must not scan")):
                main()
            self.assertFalse((root / "national-event-checkpoint.json").exists())
            self.assertEqual(list(root.glob("agenda-*.json")), [])

    def test_private_report_not_public_patch_and_no_organizer_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_campaign(
                plan_campaign(index(), DIGEST, DAY, Path(tmp), steps=1),
                public_key=KEY,
                explorer=lambda agenda, key, day, **kw: segment(agenda))
            self.assertNotIn("title", result)
            self.assertNotIn("venue", result)
            self.assertNotIn("event_uid", result)
            self.assertNotIn("additions", result)
            self.assertNotIn("safe_to_publish", result)
            self.assertEqual(result["public_writes"], 0)


if __name__ == "__main__":
    unittest.main()
