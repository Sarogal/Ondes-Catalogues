"""Offline regression for the public-runner -> private-repository Git handoff.

Never reads tokens, private state, GitHub APIs or actual user content.
"""
from pathlib import Path
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

    def test_approvals_still_disabled_by_default(self):
        step = self.commit_step
        self.assertIn('if [ "$GROSSES_ONDES_CONCERTS_AUTOREVIEW" = "enabled" ]; then', step)
        self.assertIn("git add -- automation/concerts/approved.json", step)
        self.assertIn("automation/concerts/intake/registry.json", step)
        self.assertIn("automation/concerts/intake/official-review.json", step)
        self.assertIn("automation/concerts/intake/published-watch.json", step)


if __name__ == "__main__":
    unittest.main()
