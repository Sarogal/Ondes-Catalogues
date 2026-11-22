"""Dormant, private-only Schema.org workflow contract; no production effects."""
from pathlib import Path
import unittest

BRIDGE = (Path(__file__).resolve().parents[1]
          / ".github/workflows/ptitesondes-private-intake-on-public-runners.yml")


class SchemaOrgPrivateWorkflowTest(unittest.TestCase):
    def test_schemaorg_source_only_private_stage_is_opt_in(self):
        s = BRIDGE.read_text(encoding="utf-8")
        name = "- name: Relever les pistes Schema.org institutionnelles en privé (opt-in)"
        self.assertIn(name, s)
        self.assertIn("github.ref == 'refs/heads/main'", s)
        step = s.split(name, 1)[1].split(
            "- name: Rechercher et qualifier les lieux permanents pour enfants", 1,
        )[0]
        self.assertIn("vars.PTITESONDES_SCHEMAORG_HINTS == 'enabled'", step)
        self.assertIn('if [[ "$RUN_MODE" == ', step)
        self.assertIn("--mode \"$MODE\"", step)
        self.assertIn("--state-checkout state", step)
        self.assertIn("ptitesondes_schemaorg_private_intake.py", step)
        self.assertIn("automation-intake/ptitesondes/html-schemaorg-hints.json", step)
        self.assertIn("push origin HEAD:automation/ptitesondes-intake", step)
        self.assertNotIn("git -C public add", step)
        self.assertNotIn("git -C public push", step)
        self.assertNotIn("HEAD:main", step)
        self.assertNotIn("deploy-pages", step)
        self.assertNotIn('cat "$LOG/schemaorg-private-hints-summary.json"', step)
        self.assertNotIn('echo "$PRIVATE_WRITE_TOKEN"', step)

    def test_no_new_cron_or_pr_access_to_secrets(self):
        s = BRIDGE.read_text(encoding="utf-8")
        self.assertEqual(
            [l.strip() for l in s.splitlines()
             if l.strip().startswith("- cron:")],
            ["- cron: '17 07 * * *'", "- cron: '17 10 * * *'",
             "- cron: '17 14 * * *'", "- cron: '17 18 * * *'",
             "- cron: '37 21 * * *'"])
        self.assertIn("github.repository == 'Sarogal/Ondes-Catalogues' && github.ref == 'refs/heads/main'", s)


if __name__ == "__main__":
    unittest.main()
