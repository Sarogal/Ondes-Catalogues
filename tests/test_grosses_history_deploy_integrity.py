"""Regression: history release must never redeploy a stale festival calendar."""
from pathlib import Path
import json
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from grossesondes_cloud_sync import verify_published_head

WORKFLOW = ROOT / ".github/workflows/grossesondes-history-release.yml"


class HistoryPagesCurrentHeadTests(unittest.TestCase):
    def test_history_publisher_uses_fresh_main_and_checks_remote_twice(self):
        content = WORKFLOW.read_text(encoding="utf-8")
        published = content.split("\n  publish:\n", 1)[1]
        self.assertIn("ref: main", published)
        self.assertNotIn("ref: " + "$" + "{{ github.sha }}", published)
        self.assertGreaterEqual(published.count("git fetch --no-tags --depth=1 origin main"), 2)
        self.assertGreaterEqual(published.count("git rev-parse FETCH_HEAD"), 2)
        self.assertIn("verify_published_head(published)", published)
        self.assertIn("path: docs/", published)
        self.assertIn("ondes-cloud-publication", content)

    def test_push_only_data_or_workflow_can_trigger_archive_publish(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        pushed = workflow.split("\n  push:\n", 1)[1].split("\n  workflow_dispatch:", 1)[0]
        self.assertIn("festival-history.json", pushed)
        self.assertIn("grossesondes-history-release.yml", pushed)
        self.assertNotIn("scripts/grossesondes_cloud_sync.py", pushed)
        self.assertNotIn("scripts/grossesondes_stage.py", pushed)
        self.assertNotIn("scripts/grossesondes_preview.py", pushed)

    def test_full_current_calendar_is_signed_even_if_history_only_changes(self):
        calendar = json.loads((ROOT/"docs/grossesondes/festivals.json").read_text(encoding="utf-8"))
        registry = verify_published_head(calendar)
        self.assertEqual(registry["calendarCount"], len(calendar["festivals"]))
        self.assertEqual(registry["generatedAt"], calendar["generatedAt"])


if __name__ == "__main__":
    unittest.main()
