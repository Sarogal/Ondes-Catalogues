"""Ensure real private-write bridge uses independent review batch rotation."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


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
        assignments = re.findall(
            r"(?m)^\s+'(17 \d\d \* \* \*)'\) REVIEW_SLOT=(\d) ;;$", text)
        self.assertEqual(assignments, [
            ("17 07 * * *", "0"),
            ("17 10 * * *", "1"),
            ("17 14 * * *", "2"),
            ("17 18 * * *", "3"),
        ])
        self.assertIn("REVIEW_CRON: ${{ github.event.schedule }}", text)
        self.assertIn("--limit 15 --slot \"$REVIEW_SLOT\"", text)
        self.assertIn("*) echo \"::error::Créneau de vérification inconnu", text)

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
