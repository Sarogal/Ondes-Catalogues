"""Ensure real private-write bridge uses independent review batch rotation."""
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
sys.path.insert(0, str(ROOT / "scripts"))
from ptitesondes_schedule_catchup import OUTINGS_CRONS, MAX_SLOTS


class PrivateBridgeRotationTests(unittest.TestCase):
    def test_all_four_outings_cycles_use_distinct_bounded_slots(self):
        path = WORKFLOWS / "ptitesondes-private-intake-on-public-runners.yml"
        text = path.read_text(encoding="utf-8")
        scheduled = re.findall(r"(?m)^\s+- cron: '([^']+)'$", text)
        self.assertEqual(scheduled, [
            "17 07 * * *", "17 10 * * *",
            "17 14 * * *", "17 18 * * *",
            "37 21 * * *",
        ])
        # The cron → review slot map lives in one tested planner, not in a
        # shell case statement duplicated in the workflow.
        self.assertEqual([row[0] for row in OUTINGS_CRONS], scheduled[:4])
        self.assertEqual(len(OUTINGS_CRONS), MAX_SLOTS)
        self.assertEqual(MAX_SLOTS, 4)
        self.assertIn("REVIEW_CRON: ${{ github.event.schedule }}", text)
        self.assertIn("RUN_EVENT: ${{ github.event_name }}", text)
        self.assertIn("ptitesondes_schedule_catchup.py", text)
        self.assertIn('--event "$RUN_EVENT" --cron "$REVIEW_CRON"', text)
        self.assertIn('mapfile -t REVIEW_SLOTS', text)
        self.assertIn('for REVIEW_SLOT in "${REVIEW_SLOTS[@]}"', text)
        self.assertIn('--limit 15 --slot "$REVIEW_SLOT"', text)
        self.assertIn('[[ "$REVIEW_SLOT" =~ ^[0-3]$ ]]', text)
        self.assertIn("queue: max", text)
        self.assertNotIn("*) REVIEW_SLOT=0", text)

    def test_main_bridge_is_read_only_for_public_output(self):
        text = (WORKFLOWS / "ptitesondes-private-intake-on-public-runners.yml").read_text(
            encoding="utf-8")
        self.assertIn("automation/ptitesondes-intake", text)
        self.assertIn("ref: main", text)
        self.assertIn("persist-credentials: false", text)
        self.assertNotIn("deploy-pages", text)
        self.assertNotIn("git push origin HEAD:main", text)

    def test_independent_preview_uses_matching_review_windows(self):
        p = (WORKFLOWS / "ptitesondes-evidence-preview.yml").read_text(
            encoding="utf-8")
        matches = re.findall(r"(?m)^\s+'(40 \d\d \* \* \*)'\) SLOT=(\d) ;;$", p)
        self.assertEqual(matches, [
            ("40 08 * * *", "0"),
            ("40 11 * * *", "1"),
            ("40 15 * * *", "2"),
            ("40 19 * * *", "3"),
        ])


if __name__ == "__main__":
    unittest.main()
