"""Offline safety contract for a manual, main-only OpenAgenda v2 census.

Tests have no credentials, network, private config or publication authority.
"""
from pathlib import Path
import unittest


WORKFLOW = (
    Path(__file__).resolve().parents[1] /
    ".github/workflows/ptitesondes-oa2-trusted-census.yml"
)


class TrustedCensusWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.source = WORKFLOW.read_text(encoding="utf-8")

    def test_only_manual_dispatch_may_reach_the_trusted_job(self):
        self.assertRegex(self.source, r"(?m)^on:\n  workflow_dispatch:")
        for trigger in ("pull_request", "pull_request_target", "push",
                        "schedule", "workflow_run", "repository_dispatch"):
            # Comments can mention prohibited triggers for documentation.
            self.assertNotRegex(self.source, rf"(?m)^  {trigger}:")
        self.assertIn("github.ref == 'refs/heads/main'", self.source)
        self.assertIn("github.event_name == 'workflow_dispatch'", self.source)
        self.assertIn("github.repository == 'Sarogal/Ondes-Catalogues'", self.source)

    def test_public_runner_read_only_no_publish_or_artifact(self):
        self.assertIn("runs-on: ubuntu-24.04", self.source)
        self.assertIn("contents: read", self.source)
        self.assertNotIn("contents: write", self.source)
        self.assertNotIn("upload-artifact", self.source)
        self.assertNotIn("git push", self.source)
        self.assertNotIn("deploy-pages", self.source)
        self.assertIn("persist-credentials: false", self.source)
        self.assertIn("ref: ${{ github.sha }}", self.source)

    def test_private_repo_only_sparse_checkout_and_public_read_key(self):
        self.assertIn("repository: Sarogal/PtitesOndes", self.source)
        self.assertIn("sparse-checkout:", self.source)
        self.assertIn("automation/sources.json", self.source)
        self.assertIn("token: ${{ secrets.PRIVATE_INTAKE_READ_TOKEN }}",
                      self.source)
        self.assertNotIn("PTITESONDES_INTAKE_WRITE_TOKEN", self.source)
        self.assertIn("OPENAGENDA_READ_KEY: ${{ secrets.OPENAGENDA_READ_KEY }}",
                      self.source)
        self.assertIn("ptitesondes_openagenda_v2_agenda_census.py", self.source)
        self.assertIn("--sources private-source-config/automation/sources.json",
                      self.source)
        self.assertIn("rm -rf private-source-config", self.source)


if __name__ == "__main__":
    unittest.main()
