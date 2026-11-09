"""Bridge contract: private-only stats, no new paid CI or public artifacts."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / ".github/workflows/ptitesondes-private-intake-on-public-runners.yml"
PRIVATE_LOGGER = ROOT / "scripts/ptitesondes_private_qualification_diagnostics.py"


class PrivateQualificationBridgeTests(unittest.TestCase):
    def test_private_runner_wires_redacted_report_after_independent_merge(self):
        body = BRIDGE.read_text(encoding="utf-8")
        self.assertIn("scripts/ptitesondes_private_qualification_diagnostics.py", body)
        self.assertIn('for REVIEW_SLOT in "${REVIEW_SLOTS[@]}"', body)
        self.assertIn('--reports-dir "$STATE/reports"', body)
        self.assertIn('--output "$VERIFIED/review-slots.txt"', body)
        self.assertIn("--slot \"$REVIEW_SLOT\"", body)
        self.assertIn('--report "$WORK/report.json"', body)
        self.assertIn('--output "$WORK/qualification-summary.json"', body)
        self.assertIn('if [[ "$RUN_MODE" == "write" ]]; then', body)
        self.assertIn('cp "$WORK/qualification-summary.json" "$STATE/reports/qualification-$DAY-slot$REVIEW_SLOT.json"', body)
        self.assertIn('git -C state add --', body)
        self.assertIn('automation/ptitesondes-intake', body)
        self.assertNotIn("git push origin HEAD:main", body)
        self.assertNotIn("deploy-pages", body)

    def test_no_original_private_report_is_emitted_as_public_output(self):
        body = BRIDGE.read_text(encoding="utf-8")
        self.assertNotIn('cat "$WORK/report.json" >>', body)
        self.assertNotIn('cat "$WORK/report.json" | tee', body)
        self.assertNotIn('upload-artifact', body)
        source = PRIVATE_LOGGER.read_text(encoding="utf-8")
        self.assertNotIn("print(json.dumps(summary", source)
        self.assertNotIn("print(json.dumps(data", source)


if __name__ == "__main__":
    unittest.main()
