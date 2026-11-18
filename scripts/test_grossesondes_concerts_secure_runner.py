"""Offline regression for the public-runner -> private-repository Git handoff.

Never reads tokens, private state, GitHub APIs or actual user content.
"""
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/grossesondes-concerts-private-intake-on-public-runners.yml"


class PrivateIntakeHandoffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")
        cls.commit_step = cls.workflow.split(
            "      - name: Conserver uniquement le registre et les revues dans le dépôt privé",
            1,
        )[1]

    def test_private_checkout_never_persists_token(self):
        self.assertIn("repository: Sarogal/GrossesOndes", self.workflow)
        self.assertIn("persist-credentials: false", self.workflow)
        self.assertIn("sparse-checkout-cone-mode: false", self.workflow)
        self.assertNotIn("pull_request_target:", self.workflow)

    def test_trusted_main_rechecker_merges_trigger_intake_without_pr_secrets(self):
        trigger = self.workflow.split("on:\n", 1)[1].split("\npermissions:", 1)[0]
        self.assertIn("push:", trigger)
        self.assertIn("branches: [main]", trigger)
        for path in ("automation/concerts/official_recheck.py",
                     "automation/concerts/backstage_recheck.py",
                     ".github/workflows/grossesondes-concerts-private-intake-on-public-runners.yml"):
            self.assertIn("'" + path + "'", trigger)
        self.assertNotIn("pull_request:", trigger)
        self.assertNotIn("pull_request_target:", trigger)
        self.assertIn("github.ref == 'refs/heads/main'", self.workflow)
        self.assertIn("cancel-in-progress: false", self.workflow)

    def test_trusted_discovery_and_diagnostics_merges_trigger_fresh_intake(self):
        # A source/genre/fairness patch merged to main should be measured
        # immediately, not wait for the next potentially delayed cron.
        trigger = self.workflow.split("on:\n", 1)[1].split("\npermissions:", 1)[0]
        for path in (
            "automation/concerts/discover.py",
            "automation/concerts/official_rss_jsonld_bridge.py",
            "automation/concerts/structured_first_party_preflight.py",
            "automation/concerts/triage.py",
            "automation/concerts/feeds.py",
            "automation/concerts/sources.json",
        ):
            with self.subTest(path=path):
                self.assertIn("'" + path + "'", trigger)
        self.assertNotIn("pull_request:", trigger)
        self.assertNotIn("pull_request_target:", trigger)
        self.assertIn("    branches: [main]", trigger)

    def test_promisor_objects_auth_before_stage_and_push(self):
        step = self.commit_step
        self.assertIn("INTAKE_PUSH_TOKEN: ${{ secrets.GROSSES_ONDES_INTAKE_WRITE_TOKEN }}", step)
        self.assertIn("export GIT_CONFIG_COUNT=1", step)
        self.assertIn("export GIT_CONFIG_KEY_0='http.https://github.com/.extraheader'", step)
        self.assertIn('export GIT_CONFIG_VALUE_0="AUTHORIZATION: basic $HEADER"', step)
        self.assertLess(step.index("export GIT_CONFIG_COUNT=1"),
                        step.index("git add --sparse"))
        self.assertLess(step.index("git add --sparse"),
                        step.index("git commit -m"))
        self.assertLess(step.index("git commit -m"),
                        step.index("git push origin HEAD:main"))

    def test_preflight_failure_cannot_skip_private_registry_persistence(self):
        # Preflight failure no longer destroys today's discoveries; the
        # workflow must fail only AFTER the private commit.
        self.assertIn("id: publisher_preflight", self.workflow)
        self.assertIn('echo "outcome=blocked" >> "$GITHUB_OUTPUT"', self.workflow)
        self.assertIn('"status": "blocked"', self.workflow)
        self.assertIn('approval-preflight.json', self.workflow)
        self.assertIn(
            "steps.publisher_preflight.outputs.outcome == 'blocked'",
            self.workflow)
        self.assertIn('if [ "${{ steps.publisher_preflight.outputs.outcome }}" = "passed" ]; then',
                      self.commit_step)
        self.assertLess(
            self.workflow.index("git push origin HEAD:main"),
            self.workflow.index(
                "      - name: Refuser le cycle après archivage des pistes privées"))
        self.assertNotIn("cat \"$RUNNER_TEMP/concerts-private-logs/approval-preflight.log\"",
                         self.workflow)

    def test_approvals_still_disabled_by_default(self):
        step = self.commit_step
        self.assertIn('if [ "$GROSSES_ONDES_CONCERTS_AUTOREVIEW" = "enabled" ]; then', step)
        self.assertIn("git add -- automation/concerts/approved.json", step)
        self.assertIn("automation/concerts/intake/registry.json", step)
        self.assertIn("automation/concerts/intake/official-review.json", step)
        self.assertIn("automation/concerts/intake/published-watch.json", step)


    def test_concurrent_unrelated_main_commit_does_not_lose_intake(self):
        """Real offline Git: a workflow maintenance commit lands while scanning.

        The private intake commit must be rebased and pushed on top of that
        unrelated commit, preserving both. No real private data or network.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            remote = root / "remote.git"
            def git(*args, cwd=None, expect=0):
                result = subprocess.run(
                    ["git", *args], cwd=cwd, capture_output=True, text=True)
                if expect is not None:
                    self.assertEqual(result.returncode, expect,
                        result.stdout[-1200:] + result.stderr[-1200:])
                return result
            git("init", "--bare", "--initial-branch=main", str(remote))
            seed = root / "seed"
            git("clone", str(remote), str(seed))
            for d in (seed,):
                git("config", "user.email", "test@example.invalid", cwd=d)
                git("config", "user.name", "Safe Test", cwd=d)
            (seed / "registry.json").write_text('{"entries":0}\n', encoding="utf-8")
            (seed / "README.md").write_text("initial\n", encoding="utf-8")
            git("add", ".", cwd=seed)
            git("commit", "-m", "seed", cwd=seed)
            git("push", "origin", "HEAD:main", cwd=seed)
            worker = root / "worker"
            maintainer = root / "maintainer"
            git("clone", str(remote), str(worker))
            git("clone", str(remote), str(maintainer))
            for d in (worker, maintainer):
                git("config", "user.email", "test@example.invalid", cwd=d)
                git("config", "user.name", "Safe Test", cwd=d)
            (worker / "registry.json").write_text('{"entries":1}\n',
                                                  encoding="utf-8")
            git("add", "registry.json", cwd=worker)
            git("commit", "-m", "intake", cwd=worker)
            (maintainer / "README.md").write_text("new workflow\n",
                                                  encoding="utf-8")
            git("add", "README.md", cwd=maintainer)
            git("commit", "-m", "maintenance", cwd=maintainer)
            git("push", "origin", "HEAD:main", cwd=maintainer)

            # Execute the same retry code embedded in the workflow itself,
            # not a rewritten approximation of the rebase algorithm.
            step = self.commit_step
            self.assertIn("            pushed=false\n", step)
            tail = step.split("            pushed=false\n", 1)[1]
            tail = tail.split(
                '\n          fi\n          echo "Concerts : moteur public', 1)[0]
            commands = textwrap.dedent("            pushed=false\n" + tail)
            temp_logs = root / "logs"
            (temp_logs / "concerts-private-logs").mkdir(parents=True)
            env = {**__import__("os").environ, "RUNNER_TEMP": str(temp_logs)}
            ran = subprocess.run(["bash", "-euo", "pipefail", "-c", commands],
                                 cwd=worker, env=env,
                                 capture_output=True, text=True)
            self.assertEqual(ran.returncode, 0,
                             ran.stdout[-1200:] + ran.stderr[-1200:])
            final = root / "final"
            git("clone", str(remote), str(final))
            self.assertEqual((final / "registry.json").read_text(), '{"entries":1}\n')
            self.assertEqual((final / "README.md").read_text(), "new workflow\n")
            self.assertEqual(len(git("log", "--oneline", cwd=final)
                                 .stdout.strip().splitlines()), 3)

    def test_private_retry_is_bounded_and_fail_closed(self):
        step = self.commit_step
        self.assertIn("for attempt in 1 2 3; do", step)
        self.assertIn("git fetch --no-tags origin main", step)
        self.assertIn("git -c rebase.autoStash=false rebase --no-autostash origin/main", step)
        self.assertIn("git rebase --abort", step)
        self.assertNotIn("git push --force", step)
        self.assertNotIn("git push -f", step)
        self.assertIn('if [ "$pushed" != true ]; then', step)



if __name__ == "__main__":
    unittest.main()
