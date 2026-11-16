"""Fail-closed cloud bridge contracts: overseas leads are private only.

The public runner reuses the existing schedule; no direct publishing and no
unreviewed PR branch may be checked out as the source of executable code.
"""
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / ".github/workflows/ptitesondes-private-intake-on-public-runners.yml"


class OverseasPrivateSidecarContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = FILE.read_text(encoding="utf-8")

    def test_no_extra_cron_or_private_runner(self):
        scheduled = [x.strip() for x in self.text.splitlines()
                     if x.strip().startswith("- cron:")]
        self.assertEqual(scheduled, [
            "- cron: '17 07 * * *'", "- cron: '17 10 * * *'",
            "- cron: '17 14 * * *'", "- cron: '17 18 * * *'",
            "- cron: '37 21 * * *'",
        ])
        self.assertIn("repository: Sarogal/PtitesOndes\n          ref: main", self.text)
        self.assertIn("ref: automation/ptitesondes-intake", self.text)

    def test_optional_probes_only_write_private_reports(self):
        begin = self.text.index("# Optional ultra-marine probes")
        end = self.text.index("# A single delayed scheduled run", begin)
        section = self.text[begin:end]
        self.assertIn("src/automation/municipal_gosier_discovery.py", section)
        self.assertIn("src/automation/resolve_cinor_agenda.py", section)
        self.assertIn('if [[ "$RUN_MODE" == "write" ]]', section)
        self.assertIn('"$STATE/reports/municipal-gosier-$GOSIER_DAY.json"', section)
        self.assertIn('"$STATE/reports/cinor-agenda-review.json"', section)
        self.assertIn('assert r["approved"]==r["published"]==0', section)
        self.assertIn('assert r["automatically_admitted"] is False', section)
        self.assertIn("push_private 'data(ptitesondes): conserver les sondes ultramarines", section)
        self.assertNotIn("docs/ptitesondes/sorties.json", section)
        self.assertNotIn("docs/ptitesondes/lieux.json", section)
        self.assertNotIn("git push origin HEAD:main", section)
        self.assertNotIn("merge_verified.py", section)
        self.assertNotIn("ptitesondes_candidate_promotion.py", section)

    def test_does_not_replace_original_private_review(self):
        self.assertLess(
            self.text.index("python src/automation/outings_intake.py"),
            self.text.index("# Optional ultra-marine probes"))
        self.assertLess(
            self.text.index("# A single delayed scheduled run"),
            self.text.index("python public/scripts/ptitesondes_candidate_promotion.py"))
        self.assertIn("public/docs/ptitesondes/sorties.json", self.text)
        self.assertIn("cancel-in-progress: false", self.text)


if __name__ == "__main__":
    unittest.main()
