"""Guard: HTML private queue stage never runs by default or on PR secret context."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / ".github/workflows/ptitesondes-private-intake-on-public-runners.yml"


class PrivateQueueWorkflowGateTests(unittest.TestCase):
    def test_stage_is_dormant_without_opt_in_and_private_only(self):
        s = BRIDGE.read_text(encoding="utf-8")
        self.assertIn("vars.PTITESONDES_HTML_QUEUE == 'enabled'", s)
        self.assertIn("if: github.repository == 'Sarogal/Ondes-Catalogues' && github.ref == 'refs/heads/main'", s)
        self.assertIn('--state-checkout state --mode "$MODE"', s)
        self.assertIn("automation-intake/ptitesondes/html-review-candidates.json", s)
        self.assertIn("push origin HEAD:automation/ptitesondes-intake", s)
        self.assertNotIn("git push origin HEAD:main", s)
        section = s.split(
            "- name: Préparer les séances HTML pour une file exclusivement privée (opt-in)", 1
        )[1].split(
            "- name: Rechercher et qualifier les lieux permanents pour enfants", 1
        )[0]
        self.assertIn("vars.PTITESONDES_HTML_QUEUE == 'enabled'", section)
        self.assertIn('if [[ "$RUN_MODE" == ', section)
        self.assertIn("git -C state add -- automation-intake/ptitesondes/html-review-candidates.json", section)
        self.assertNotIn('echo "$PRIVATE_WRITE_TOKEN"', section)
        self.assertNotIn('cat "$LOG/html-private-queue-summary.json"', section)
        self.assertNotIn("docs/ptitesondes/sorties.json", section)
        self.assertNotIn("deploy-pages", section)


if __name__ == "__main__":
    unittest.main()
