"""Trusted-checkout worklist runner: private-only, stage/preview safety."""
from datetime import datetime, date
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_html_private_queue_cycle import _stage_queue
from ptitesondes_nonmusical_private_queue_handoff import _row_from_proof
from ptitesondes_html_independent_review_cycle import (
    PRIVATE_WORKLIST, SCHEMA, execute_worklist,
)

NOW = datetime(2026, 11, 20, 11, 0, tzinfo=ZoneInfo("Europe/Paris"))


def review(clock):
    return _row_from_proof({
        "source_url": "https://official.example.org/evenement/atelier",
        "source_title_identity_only": "Séance familiale",
        "city": "Montpellier", "venue": "Maison du quartier",
        "category": "atelier-creatif", "date_start": "2026-11-22",
        "start_local": clock,
    }, {"stage": "institutional_source_policy_pending"}, date(2026, 11, 20), None)


def git_checkout(root):
    subprocess.run(
        ["git", "init", "-q", "-b", "automation/ptitesondes-intake",
         str(root)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(root), "remote", "add", "origin",
         "https://github.com/Sarogal/PtitesOndes"],
        check=True, capture_output=True)


class HtmlIndependentReviewCycleTests(unittest.TestCase):
    def test_preview_is_readonly_and_stage_writes_private_worklist_only(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            git_checkout(root)
            candidates = root / "automation-intake/ptitesondes/html-review-candidates.json"
            candidates.parent.mkdir(parents=True)
            _stage_queue(candidates, [review("09:15"), review("10:30")])
            output = root / PRIVATE_WORKLIST
            before = candidates.read_bytes()
            summary = execute_worklist(root, NOW, mode="preview")
            self.assertFalse(output.exists())
            self.assertEqual(summary["selected_sessions"], 2)
            self.assertNotIn("source_url", summary)
            self.assertEqual(candidates.read_bytes(), before)
            actual = execute_worklist(root, NOW, mode="stage")
            self.assertEqual(actual["public_writes"], 0)
            self.assertTrue(output.exists())
            data = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(data["schema"], SCHEMA)
            self.assertEqual(data["planned_on"], "2026-11-20")
            self.assertFalse(data["worklist_is_evidence"])
            self.assertFalse(data["publication_ready"])
            self.assertFalse(data["approved"])
            self.assertFalse(data["published"])
            tasks = data["tasks"]["sessions"]
            self.assertEqual(len(tasks), 2)
            self.assertNotEqual(tasks[0]["review_id"], tasks[1]["review_id"])
            self.assertFalse(tasks[0]["admission_authorized"])
            self.assertEqual(candidates.read_bytes(), before)
            self.assertNotIn("Séance familiale", output.read_text(encoding="utf-8"))
            self.assertNotIn("official.example.org", output.read_text(encoding="utf-8"))

    def test_spoofed_remote_or_fake_approvals_fail_before_stage(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            git_checkout(root)
            candidates = root / "automation-intake/ptitesondes/html-review-candidates.json"
            candidates.parent.mkdir(parents=True)
            approved = review("09:15")
            approved["approved"] = True
            candidates.write_text(json.dumps([approved]), encoding="utf-8")
            with self.assertRaises(ValueError):
                execute_worklist(root, NOW, mode="stage")
            self.assertFalse((root / PRIVATE_WORKLIST).exists())
            _stage_queue(candidates, [review("09:15")])
            subprocess.run(
                ["git", "-C", str(root), "remote", "set-url", "origin",
                 "https://github.com/outsider/fork"],
                check=True, capture_output=True)
            with self.assertRaises(ValueError):
                execute_worklist(root, NOW, mode="stage")
            self.assertFalse((root / PRIVATE_WORKLIST).exists())

    def test_unsafe_symlink_destination_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            git_checkout(root)
            candidates = root / "automation-intake/ptitesondes/html-review-candidates.json"
            candidates.parent.mkdir(parents=True)
            _stage_queue(candidates, [review("09:15")])
            outsider = root / "outside-no-touch.txt"
            outsider.write_text("keep me", encoding="utf-8")
            worklist = root / PRIVATE_WORKLIST
            try:
                worklist.symlink_to(outsider)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks not available")
            with self.assertRaisesRegex(ValueError, "invalid_private_worklist"):
                execute_worklist(root, NOW, mode="stage")
            self.assertEqual(outsider.read_text(encoding="utf-8"), "keep me")

    def test_reject_invalid_options_and_allow_empty_queue(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            git_checkout(root)
            (root / "automation-intake/ptitesondes").mkdir(parents=True)
            output = execute_worklist(root, NOW, mode="preview")
            self.assertEqual(output["selected_sessions"], 0)
            self.assertFalse((root / PRIVATE_WORKLIST).exists())
            with self.assertRaises(ValueError):
                execute_worklist(root, NOW, mode="write")
            with self.assertRaises(ValueError):
                execute_worklist(root, NOW, mode="stage", limit=500)


if __name__ == "__main__":
    unittest.main()
