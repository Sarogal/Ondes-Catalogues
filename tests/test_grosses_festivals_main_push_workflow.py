"""Trusted push-based festival intake must never bypass private/publisher gates."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/grossesondes-festivals-private-intake-on-public-runners.yml"
PUBLISHER = ROOT / ".github/workflows/grossesondes-cloud-sync.yml"


class FestivalTrustedPushTests(unittest.TestCase):
    def test_engine_changes_only_wake_trusted_main_public_runner(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("  push:\n    branches: [main]\n    paths:", workflow)
        self.assertIn("scripts/grossesondes_archived_html_intake.py", workflow)
        self.assertIn("festival-automation/regional_festival_indexes.json", workflow)
        self.assertIn(".github/workflows/grossesondes-festivals-private-intake-on-public-runners.yml", workflow)
        self.assertIn("github.repository == 'Sarogal/Ondes-Catalogues' && github.ref == 'refs/heads/main'", workflow)
        self.assertIn("permissions:\n  contents: read", workflow)
        self.assertIn("cancel-in-progress: false", workflow)
        self.assertNotIn("pull_request:", workflow)
        self.assertNotIn("pull_request_target:", workflow)

    def test_optional_ocr_cache_is_private_and_cannot_publish(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        start = workflow.index("      - name: OCR statique et DOM transportés")
        finish = workflow.index("      - name: Enregistrer exclusivement", start)
        step = workflow[start:finish]
        self.assertIn("continue-on-error: true", step)
        self.assertIn("timeout-minutes: 5", step)
        self.assertIn("timeout 195s /usr/bin/python3", step)
        self.assertIn("timeout 75s sudo apt-get install", step)
        self.assertIn("--limit 4 --private-cache", step)
        self.assertIn("intake/automation-intake/grossesondes/official-poster-ocr-cache.json", step)
        self.assertIn("report['publication_authorized'] is False", step)
        self.assertNotIn("secrets.", step)
        self.assertNotIn("--browser", step)
        self.assertNotIn("upload-artifact", step)
        self.assertIn("--rendered-evidence", step)
        self.assertIn("POSTER_DOM_TICK", step)
        self.assertIn("report[\'review_only\'] is True", step)
        self.assertIn("git add -- automation-intake/grossesondes/official-poster-ocr-cache.json",
                      workflow[finish:])
        self.assertIn("push origin HEAD:automation/grossesondes-intake", workflow[finish:])
        self.assertNotIn("git add -- docs/", workflow)

    def test_dynamic_poster_dom_job_has_no_private_access(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        start = workflow.index("  poster_dom_readonly:\n")
        end = workflow.index("\n  watch:\n", start)
        browser = workflow[start:end]
        self.assertIn("contents: read", browser)
        self.assertIn("persist-credentials: false", browser)
        self.assertIn("continue-on-error: true", browser)
        self.assertIn("chromium_sandbox=True", browser)
        self.assertIn("--capture-rendered-evidence", browser)
        self.assertIn("--browser", browser)
        self.assertIn("retention-days: 1", browser)
        for forbidden in ("secrets.", "private-cache", "automation-intake/", "contents: write"):
            self.assertNotIn(forbidden, browser)
        self.assertIn("needs: [poster_dom_readonly]", workflow[end:])
        self.assertIn("!cancelled()", workflow[end:])
        self.assertIn("name: grossesondes-public-poster-dom", workflow[end:])

    def test_trusted_push_wakes_only_independent_publisher(self):
        publisher = PUBLISHER.read_text(encoding="utf-8")
        # A successful trusted main push can wake verification, not grant publication.
        self.assertIn("github.event.workflow_run.event == 'schedule'", publisher)
        self.assertIn("github.event.workflow_run.event == 'workflow_dispatch'", publisher)
        self.assertIn("github.event.workflow_run.event == 'push'", publisher)
        self.assertIn("github.event.workflow_run.head_branch == 'main'", publisher)
        self.assertIn("github.event.workflow_run.head_repository.full_name == github.repository", publisher)
        self.assertIn("github.event.workflow_run.conclusion == 'success'", publisher)
        self.assertIn("github.event.workflow_run.status == 'completed'", publisher)
        self.assertIn("github.event_name != 'pull_request'", publisher)
        self.assertLess(publisher.index("scripts/grossesondes_festival_intake_trust.py --check-event"),
                        publisher.index("python scripts/grossesondes_cloud_sync.py --mode"))
        self.assertIn("vars.GROSSES_ONDES_CLOUD_SYNC == 'enabled'", publisher)


if __name__ == "__main__":
    unittest.main()
