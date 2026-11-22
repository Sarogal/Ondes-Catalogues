"""Static proof ODS fallback cannot run by default or on PRs."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/ptitesondes-private-intake-on-public-runners.yml"


class OdsDirectMirrorWorkflowTests(unittest.TestCase):
    def test_dormant_direct_audit_is_private_only(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        name = "- name: Diagnostiquer en privé les UID absents du miroir ODS (opt-in)"
        self.assertIn(name, source)
        step = source.split(name, 1)[1].split(
            "- name: Rechercher et qualifier les lieux permanents pour enfants", 1,
        )[0]
        self.assertIn("vars.PTITESONDES_ODS_DIRECT_AUDIT == 'enabled'", step)
        self.assertIn("env.CYCLE != 'places'", step)
        self.assertIn('if [[ "$RUN_MODE" == ', step)
        self.assertIn("--state-checkout state", step)
        self.assertIn('--mode "$MODE"', step)
        self.assertIn("automation-intake/ptitesondes/reports/ods-direct-mirror-audit.json", step)
        self.assertIn("push origin HEAD:automation/ptitesondes-intake", step)
        self.assertNotIn("git -C public add", step)
        self.assertNotIn("HEAD:main", step)
        self.assertNotIn("deploy-pages", step)
        self.assertNotIn('cat "$LOG/ods-direct-mirror-aggregate-summary.json"', step)
        self.assertNotIn('echo "$OPENAGENDA_READ_KEY"', step)

    def test_only_existing_protected_runner_schedule_is_reused(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("github.ref == 'refs/heads/main'", source)
        self.assertIn("OPENAGENDA_READ_KEY: ${{ secrets.OPENAGENDA_READ_KEY }}",
                      source)
        self.assertEqual(
            [x.strip() for x in source.splitlines()
             if x.strip().startswith("- cron:")],
            ["- cron: '17 07 * * *'", "- cron: '17 10 * * *'",
             "- cron: '17 14 * * *'", "- cron: '17 18 * * *'",
             "- cron: '37 21 * * *'"])


if __name__ == "__main__":
    unittest.main()
