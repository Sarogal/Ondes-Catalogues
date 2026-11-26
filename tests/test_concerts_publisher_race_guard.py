"""Fail-closed static contract of the guarded Concerts publisher push.

This does not access GitHub, secrets, websites or private approvals.
"""
from pathlib import Path
import os
import subprocess
import tempfile
import textwrap
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
            'git merge-base --is-ancestor "$CHECKED_BASE" "$REMOTE_HEAD"',
            'git diff --quiet "$CHECKED_BASE" "$REMOTE_HEAD" --',
            "scripts/ ",
            "automation/concerts/ ",
            ".github/workflows/grossesondes-concerts-cloud-sync.yml",
            'test "$(git rev-parse HEAD)" = "$CHECKED_BASE"',
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


    def test_real_git_retry_and_guard_against_protected_concurrent_commit(self):
        step = WF.read_text(encoding="utf-8").split(
            "      - name: Conserver le nouveau JSON approuvé dans Git", 1
        )[1].split("      - name: Préparer GitHub Pages", 1)[0]
        script = textwrap.dedent(step.split("        run: |\n", 1)[1])
        for mode in ("unrelated", "protected"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as root:
                root = Path(root)
                def git(*args, cwd=root):
                    return subprocess.run(["git", *args], cwd=cwd, check=True,
                                          capture_output=True, text=True).stdout.strip()
                git("init", "--bare", "--initial-branch=main", "origin.git")
                git("clone", "origin.git", "publisher")
                publisher = root / "publisher"
                git("config", "user.name", "Test", cwd=publisher)
                git("config", "user.email", "test@example.invalid", cwd=publisher)
                target = publisher / "docs/grossesondes/concerts.json"
                target.parent.mkdir(parents=True)
                target.write_text("old\n")
                git("add", ".", cwd=publisher)
                git("commit", "-m", "base", cwd=publisher)
                git("push", "origin", "main", cwd=publisher)
                checked = git("rev-parse", "HEAD", cwd=publisher)
                git("clone", "origin.git", "concurrent")
                concurrent = root / "concurrent"
                git("config", "user.name", "Test", cwd=concurrent)
                git("config", "user.email", "test@example.invalid", cwd=concurrent)
                other = (concurrent / "docs/grossesondes/concerts.json"
                         if mode == "protected" else concurrent / "unrelated.txt")
                other.write_text("concurrent\n")
                git("add", ".", cwd=concurrent)
                git("commit", "-m", "concurrent update", cwd=concurrent)
                target.write_text("new\n")
                # Inject the competing write immediately before the first push,
                # after the publisher has already fetched and validated.
                hook = publisher / ".git/hooks/pre-push"
                hook.write_text(
                    '#!/bin/sh\n'
                    'if [ ! -f .git/race-injected ]; then\n'
                    '  touch .git/race-injected\n'
                    '  git -C ../concurrent push origin main || exit 1\n'
                    '  exit 1\n'
                    'fi\n'
                )
                hook.chmod(0o755)
                output = root / "step-output"
                output.touch()
                run = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", script],
                                     cwd=publisher, env=dict(os.environ, CHECKED_BASE=checked,
                                                             GITHUB_OUTPUT=str(output)),
                                     capture_output=True, text=True, timeout=30)
                self.assertTrue((publisher / ".git/race-injected").exists())
                git("fetch", "origin", "main", cwd=publisher)
                public = git("show", "FETCH_HEAD:docs/grossesondes/concerts.json",
                             cwd=publisher)
                if mode == "unrelated":
                    self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                    self.assertEqual(public, "new")
                    self.assertEqual(output.read_text(), "")
                    self.assertEqual(git("show", "FETCH_HEAD:unrelated.txt",
                                         cwd=publisher), "concurrent")
                else:
                    self.assertNotEqual(run.returncode, 0)
                    self.assertEqual(public, "concurrent")
                    self.assertIn("garde-fous ont changé", run.stdout)
                    self.assertEqual(output.read_text(), "retry_race=true\n")


    def test_fresh_retry_is_explicit_bounded_and_has_no_publication_credentials(self):
        yml = WF.read_text(encoding="utf-8")
        self.assertIn("retry_race: ${{ steps.commit_catalogue.outputs.retry_race }}", yml)
        self.assertIn("retry_after_race:\n", yml)
        retry = yml.split("  retry-fresh:\n", 1)[1].split("  deploy:\n", 1)[0]
        for required in ("needs.prepare.result == 'failure'",
                         "needs.prepare.outputs.retry_race == 'true'",
                         "github.repository == 'Sarogal/Ondes-Catalogues'",
                         "github.ref == 'refs/heads/main'",
                         "inputs.mode == 'publish' && !inputs.retry_after_race",
                         "actions: write", "--ref main",
                         "-f mode=publish -f retry_after_race=true"):
            self.assertIn(required, retry)
        self.assertNotIn("contents: write", retry)
        self.assertNotIn("secrets.", retry)
        self.assertNotIn("checkout", retry)
        self.assertNotIn("git push", retry)


if __name__ == "__main__":
    unittest.main()
