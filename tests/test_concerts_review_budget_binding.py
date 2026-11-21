"""Prevent a bash-scope regression in the private Concerts intake workflow."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/grossesondes-concerts-private-intake-on-public-runners.yml"

class ReviewBudgetBindingTest(unittest.TestCase):
    def test_review_limit_is_declared_in_the_same_shell_step_as_its_use(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        name = "      - name: Revérifier et approuver uniquement si le verrou existant le permet"
        self.assertEqual(source.count(name), 1)
        section = source.split(name, 1)[1].split("\n      - name:", 1)[0]
        self.assertIn("set -euo pipefail", section)
        self.assertIn('REVIEW_LIMIT=16', section)
        self.assertIn('REVIEW_LIMIT=24', section)
        self.assertIn('if [ "${{ github.event_name }}" = "push" ]; then', section)
        self.assertIn('--review-limit "$REVIEW_LIMIT"', section)
        self.assertLess(section.index("REVIEW_LIMIT=16"),
                        section.index('--review-limit "$REVIEW_LIMIT"'))
        self.assertEqual(source.count('REVIEW_LIMIT=16'), 1)
        osm_section = source.split("      - name: Découvrir",1)[1].split("\n      - name:",1)[0] if "      - name: Découvrir" in source else ""
        self.assertNotIn('REVIEW_LIMIT=16', osm_section)
    def test_source_and_cli_enforce_real_bound_without_approval_bypass(self):
        module=(ROOT / "automation/concerts/official_recheck.py").read_text(encoding="utf-8")
        self.assertIn('--review-limit', module)
        self.assertIn('choices=range(1, 41)', module)
        self.assertIn('limit=args.review_limit', module)
        self.assertIn('GROSSES_ONDES_CONCERTS_AUTOREVIEW', WORKFLOW.read_text(encoding="utf-8"))
if __name__ == "__main__":
    unittest.main()
