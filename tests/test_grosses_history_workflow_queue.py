"""Read-only archive checks should not queue old PR commits ahead of the latest."""
from pathlib import Path
import unittest


class HistoryWorkflowQueueTests(unittest.TestCase):
    def test_pr_checks_are_sha_scoped_and_production_stays_serialized(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github/workflows/grossesondes-history-release.yml").read_text(
            encoding="utf-8")
        self.assertIn("github.event.pull_request.number, github.sha)", workflow)
        self.assertIn("|| 'ondes-cloud-publication'", workflow)
        self.assertIn("  queue: max", workflow)
        self.assertIn("  cancel-in-progress: false", workflow)
        self.assertIn("permissions:\n  contents: read", workflow)
        self.assertIn("runs-on: ubuntu-24.04", workflow)


if __name__ == "__main__":
    unittest.main()
