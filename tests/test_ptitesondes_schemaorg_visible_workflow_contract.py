"""Workflow guard: two separate opt-ins, private only, never PR secrets."""
from pathlib import Path
import unittest

WORKFLOW = (Path(__file__).resolve().parents[1] /
            ".github/workflows/ptitesondes-private-intake-on-public-runners.yml")


class SchemaOrgVisibleWorkflowContracts(unittest.TestCase):
    def test_both_optins_required_for_schemaorg_review(self):
        s = WORKFLOW.read_text(encoding="utf-8")
        label = "- name: Revérifier les pistes Schema.org visibles avant une revue privée (opt-in)"
        self.assertIn(label, s)
        section = s.split(label, 1)[1].split(
            "- name: Rechercher et qualifier les lieux permanents pour enfants", 1,
        )[0]
        self.assertIn("vars.PTITESONDES_SCHEMAORG_HINTS == 'enabled'", section)
        self.assertIn("vars.PTITESONDES_SCHEMAORG_RECHECK == 'enabled'", section)
        self.assertIn("--state-checkout state", section)
        self.assertIn("--mode \"$MODE\"", section)
        self.assertIn("automation-intake/ptitesondes/html-review-candidates.json", section)
        self.assertIn("push origin HEAD:automation/ptitesondes-intake", section)
        self.assertIn('if [[ "$RUN_MODE" == ', section)
        self.assertNotIn("git -C public add", section)
        self.assertNotIn("git -C public push", section)
        self.assertNotIn("deploy-pages", section)
        self.assertNotIn("HEAD:main", section)

    def test_shared_secure_runner_gate_remains_unchanged(self):
        s = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("github.ref == 'refs/heads/main'", s)
        self.assertIn("vars.PTITESONDES_PUBLIC_INTAKE != 'paused'", s)
        self.assertIn("persist-credentials: false", s)
        self.assertEqual(
            [x.strip() for x in s.splitlines()
             if x.strip().startswith("- cron:")],
            ["- cron: '17 07 * * *'", "- cron: '17 10 * * *'",
             "- cron: '17 14 * * *'", "- cron: '17 18 * * *'",
             "- cron: '37 21 * * *'"])


if __name__ == "__main__":
    unittest.main()
