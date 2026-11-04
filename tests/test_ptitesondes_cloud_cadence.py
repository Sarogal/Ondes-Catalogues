"""Cadence and no-change safety for the four P'tites Ondes cloud cycles."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1] / ".github" / "workflows"


def cron(name):
    text = (ROOT / name).read_text(encoding="utf-8")
    return re.findall(r"(?m)^\s+- cron: '([^']+)'$", text)


class OutingsFourDailyCycles(unittest.TestCase):
    def test_independent_evidence_review_four_times(self):
        self.assertEqual(cron("ptitesondes-evidence-preview.yml"),
                         ["40 08 * * *", "40 11 * * *",
                          "40 15 * * *", "40 19 * * *"])

    def test_secure_sync_four_times_after_review(self):
        self.assertEqual(cron("ptitesondes-cloud-sync.yml"),
                         ["20 09 * * *", "20 12 * * *",
                          "20 16 * * *", "20 20 * * *"])

    def test_empty_changes_cannot_deploy(self):
        sync = (ROOT / "ptitesondes-cloud-sync.yml").read_text(encoding="utf-8")
        preview = (ROOT / "ptitesondes-evidence-preview.yml").read_text(encoding="utf-8")
        self.assertIn('"$CHANGED" = "true"', sync)
        self.assertIn('"$CLOUD_ENABLED" = "enabled"', sync)
        self.assertIn("group: ondes-cloud-publication", sync)
        self.assertIn("cancel-in-progress: false", sync)
        self.assertNotIn("git push --force", sync)
        self.assertIn("contents: read", preview)
        self.assertIn("github.event_name != 'pull_request'", preview)


if __name__ == "__main__":
    unittest.main()
