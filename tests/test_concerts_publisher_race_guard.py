"""Fail-closed static contract of the guarded Concerts publisher push.

This does not access GitHub, secrets, websites or private approvals.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
WF = ROOT / ".github/workflows/grossesondes-concerts-cloud-sync.yml"


class CloudPublisherRaceSafetyTests(unittest.TestCase):
    def test_concurrent_unrelated_main_commit_can_be_rebased_only_after_guards(self):
        yml = WF.read_text(encoding="utf-8")
        step = yml.split("      - name: Conserver le nouveau JSON approuvé dans Git", 1)[1].split(
            "      - name: Préparer GitHub Pages", 1)[0]
        self.assertIn("steps.sync.outputs.changed == 'true'", step)
        for part in (
            "git fetch --no-tags origin main",
            'REMOTE_HEAD="$(git rev-parse FETCH_HEAD)"',
            'git merge-base --is-ancestor "$GITHUB_SHA" "$REMOTE_HEAD"',
            'git diff --quiet "$GITHUB_SHA" "$REMOTE_HEAD" --',
            "scripts/concerts_cloud_sync.py",
            "tests/test_concerts_cloud_sync.py",
            "docs/grossesondes/concerts.json",
            "docs/grossesondes/concerts-reference.json",
            'git rebase "$REMOTE_HEAD"',
            "git push origin HEAD:main",
        ):
            self.assertIn(part, step)
        self.assertLess(step.index("git diff --quiet"),
                        step.index('git rebase "$REMOTE_HEAD"'))
        self.assertLess(step.index('git rebase "$REMOTE_HEAD"'),
                        step.index("git push origin HEAD:main"))
        self.assertIn("exit 1", step)
        self.assertNotIn("pull_request_target:", yml)
        self.assertNotIn("pull_request:", yml.split("\non:", 1)[1].split("\npermissions:", 1)[0])


if __name__ == "__main__":
    unittest.main()
