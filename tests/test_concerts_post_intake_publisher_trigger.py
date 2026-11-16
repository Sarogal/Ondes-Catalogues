"""Read-only safety contract for post-intake Concerts publisher dispatch.

No network, secrets or publishing. The new workflow_run trigger is limited to
successful default-branch collection runs. Scheduled and manual fallback remain.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
CLOUD = ROOT / ".github/workflows/grossesondes-concerts-cloud-sync.yml"
INTAKE = ROOT / ".github/workflows/grossesondes-concerts-private-intake-on-public-runners.yml"


class ConcertsPostIntakePublisherSafetyTests(unittest.TestCase):
    def test_triggers_only_completed_named_intake(self):
        wf = CLOUD.read_text(encoding="utf-8")
        intake = INTAKE.read_text(encoding="utf-8")
        workflow_name = intake.splitlines()[0].removeprefix("name: ").strip()
        self.assertIn("  workflow_run:\\n", wf.replace("\\n", "\n"))
        self.assertIn("    workflows:\n      - " + workflow_name + "\n", wf)
        self.assertIn("    types: [completed]", wf)
        self.assertNotIn("pull_request_target:", wf)
        self.assertNotIn("  pull_request:", wf)

    def test_no_untrusted_run_can_access_publisher_credentials(self):
        wf = CLOUD.read_text(encoding="utf-8")
        section = wf.split("jobs:\n  prepare:\n", 1)[1].split("    runs-on:", 1)[0]
        self.assertIn("if: ${{", section)
        for test in (
            "github.event_name != 'workflow_run'",
            "github.event.workflow_run.conclusion == 'success'",
            "github.event.workflow_run.head_branch == 'main'",
            "github.event.workflow_run.head_repository.full_name == github.repository",
        ):
            self.assertIn(test, section)
        self.assertIn("  contents: write", wf)
        self.assertNotIn("repository: Sarogal/GrossesOndes", wf)

    def test_existing_publication_gates_and_idempotent_lock_retained(self):
        wf = CLOUD.read_text(encoding="utf-8")
        self.assertIn("  workflow_dispatch:", wf)
        self.assertIn("default: preview", wf)
        self.assertIn("cron: '17 */3 * * *'", wf)
        self.assertIn("group: ondes-cloud-publication", wf)
        self.assertIn("cancel-in-progress: false", wf)
        self.assertIn("vars.GROSSES_ONDES_CONCERTS_CLOUD_SYNC", wf)
        self.assertIn('"$CLOUD_ENABLED" = "enabled"', wf)
        self.assertIn("steps.sync.outputs.changed == 'true'", wf)
        self.assertIn("scripts/concerts_cloud_sync.py --mode", wf)
        self.assertIn("github.event_name != 'workflow_dispatch' && 'publish'", wf)
        self.assertIn("git push origin HEAD:main", wf)


if __name__ == "__main__":
    unittest.main()
