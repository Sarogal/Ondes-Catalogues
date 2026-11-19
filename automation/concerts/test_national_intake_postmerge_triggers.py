"""Permanent regression: every generic concert module must retrigger intake.

Only the Concerts national engine is inspected. No secrets or network.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/grossesondes-concerts-private-intake-on-public-runners.yml"


class ConcertsPostMergeTriggerTests(unittest.TestCase):
    def test_generic_verifiers_and_manifest_trigger_private_intake_from_main(self):
        raw = WORKFLOW.read_text(encoding="utf-8")
        push = raw.split("  push:\n", 1)[1].split("  workflow_dispatch:", 1)[0]
        self.assertIn("    branches: [main]", push)
        entries = re.findall(r"^      - '([^']+)'$", push, re.M)
        self.assertEqual(len(entries), len(set(entries)))
        for path in (
            "automation/concerts/discover.py",
            "automation/concerts/generic_music_event.py",
            "automation/concerts/generic_visible_bill.py",
            "automation/concerts/generic_first_party_venue_specs_v1.json",
            "automation/concerts/official_html_evidence.py",
            "automation/concerts/official_recheck.py",
            "automation/concerts/verifier_contract.py",
            "automation/concerts/published_watch.py",
            "automation/concerts/triage.py",
        ):
            with self.subTest(path=path):
                self.assertIn(path, entries)
                self.assertTrue((ROOT / path).is_file())


if __name__ == "__main__":
    unittest.main()
