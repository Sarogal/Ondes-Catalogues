"""Fail-closed workflow contract for a concurrent main update during publish."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / ".github/workflows/grossesondes-cloud-sync.yml"


class ConcurrentPublishRetryGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = FILE.read_text(encoding="utf-8")

    def test_retry_still_requires_full_independent_cloud_sync(self):
        w = self.workflow
        self.assertIn("gh workflow run grossesondes-cloud-sync.yml", w)
        self.assertIn("--ref main -f mode=publish -f retry_once=true", w)
        self.assertIn("retry_once:", w)
        self.assertIn('if [ "$RETRY_ONCE" = "true" ]; then', w)
        self.assertIn("python -m unittest discover -s tests -p 'test_grosses_*.py' -v", w)
        self.assertIn("python scripts/grossesondes_cloud_sync.py --mode", w)
        self.assertIn("GROSSES_ONDES_CLOUD_SYNC", w)

    def test_no_reuse_of_stale_candidate_or_second_nonfastforward_retry(self):
        w = self.workflow
        self.assertIn("git push origin HEAD:main", w)
        self.assertIn('retry_required=true', w)
        self.assertIn('echo "pushed=false"', w)
        self.assertNotIn("git push --force", w)
        self.assertNotIn("git rebase", w)
        self.assertNotIn("git pull --rebase", w)
        self.assertIn("Conflit répété ; arrêt fermé", w)

    def test_github_pages_is_always_guarded_by_real_git_push(self):
        w = self.workflow
        self.assertIn("deploy: ${{ steps.confirm.outputs.deploy }}", w)
        self.assertIn('if [ "$DECIDED" = "true" ] && [ "$PUSHED" = "true" ]; then', w)
        self.assertEqual(
            w.count("if: ${{ steps.confirm.outputs.deploy == 'true' }}"), 2)
        self.assertIn("steps.commit_published.outputs.pushed", w)
        self.assertIn("needs.prepare.outputs.deploy == 'true'", w)

    def test_no_secrets_or_extra_cron_enter_pull_request_job(self):
        w = self.workflow
        self.assertIn("if: github.event_name == 'pull_request'", w)
        self.assertIn("permissions:\n      contents: read", w)
        self.assertIn("if: ${{ github.event_name != 'pull_request'", w)
        self.assertIn("contents: write\n      actions: write", w)
        self.assertIn("cron: '47 10 * * *'", w)
        self.assertIn("cron: '45 17 * * *'", w)
        self.assertIn("default: preview", w)


if __name__ == "__main__":
    unittest.main()
