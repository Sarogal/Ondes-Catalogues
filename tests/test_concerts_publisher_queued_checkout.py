"""A queued publisher must validate current trusted main, not a stale trigger."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/grossesondes-concerts-cloud-sync.yml"


class QueuedPublisherContractTests(unittest.TestCase):
    def test_main_checkout_and_actual_base_before_validation(self):
        w = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("github.ref == 'refs/heads/main'", w)
        self.assertIn("github.event.workflow_run.conclusion == 'success'", w)
        self.assertIn("github.event.workflow_run.head_repository.full_name == github.repository", w)
        self.assertIn("ref: refs/heads/main", w)
        self.assertIn("fetch-depth: 0", w)
        self.assertIn('sha=$(git rev-parse HEAD)', w)
        self.assertLess(w.index("id: checked_base"), w.index("python -m unittest"))
        self.assertLess(w.index("id: checked_base"), w.index("python scripts/concerts_cloud_sync.py"))
        self.assertIn("CHECKED_BASE: ${{ steps.checked_base.outputs.sha }}", w)
        self.assertIn('test "$(git rev-parse HEAD)" = "$CHECKED_BASE"', w)
        self.assertIn('git merge-base --is-ancestor "$CHECKED_BASE" "$REMOTE_HEAD"', w)
        self.assertIn('git diff --quiet "$CHECKED_BASE" "$REMOTE_HEAD"', w)
        self.assertNotIn('$GITHUB_SHA', w)

    def test_fail_closed_and_common_lock_preserved(self):
        w = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("group: ondes-cloud-publication", w)
        self.assertIn("queue: max", w)
        self.assertIn("cancel-in-progress: false", w)
        self.assertIn("docs/grossesondes/concerts.json ", w)
        self.assertIn("docs/grossesondes/concerts-reference.json;", w)
        self.assertIn("automation/concerts/ ", w)
        self.assertIn("scripts/ ", w)
        self.assertIn("tests/test_concerts_cloud_sync.py ", w)
        self.assertIn('git push origin HEAD:main', w)
        self.assertNotIn('git push --force', w)
        self.assertIn("Le catalogue ou ses garde-fous ont changé", w)


if __name__ == "__main__":
    unittest.main()
