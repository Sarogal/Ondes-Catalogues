"""Offline safety regression: a Festival intake is not publisher authority."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import grossesondes_festival_intake_trust as source

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/grossesondes-cloud-sync.yml"


def trusted_payload():
    return {
        "repository": {"full_name": source.REPO},
        "workflow_run": {
            "id": 123456,
            "name": source.SOURCE_NAME,
            "event": "schedule",
            "status": "completed", "conclusion": "success",
            "head_branch": "main",
            "head_sha": "a" * 40,
            "head_repository": {"full_name": source.REPO},
        },
    }


class FestivalHandoffTrustTests(unittest.TestCase):
    def test_only_exact_successful_main_intake_is_authorized(self):
        self.assertTrue(source.trusted(trusted_payload()))
        item = trusted_payload()
        item["workflow_run"]["event"] = "workflow_dispatch"
        self.assertTrue(source.trusted(item))

    def test_rejects_untrusted_origin_and_untrusted_events(self):
        changes = [
            ("repository", {"full_name": "foreign/Ondes-Catalogues"}),
            ("workflow_run", None),
        ]
        for field, replacement in changes:
            payload = trusted_payload()
            payload[field] = replacement
            with self.subTest(field=field):
                self.assertFalse(source.trusted(payload))
        for name, invalids in {
            "name": ["Other workflow", "", None],
            "event": ["pull_request", "push", "workflow_run", "pull_request_target", None],
            "status": ["queued", "in_progress", None],
            "conclusion": ["failure", "cancelled", "skipped", None],
            "head_branch": ["feature/evil", "pull/123/merge", None],
            "head_sha": ["b" * 39, "b" * 41, "G" * 40, None],
            "id": [False, -1, None, "999"],
            "head_repository": [{"full_name": "fork/repo"}, None],
        }.items():
            for value in invalids:
                payload = trusted_payload()
                payload["workflow_run"][name] = value
                with self.subTest(field=name, value=value):
                    self.assertFalse(source.trusted(payload))

    def test_invalid_payload_structures_fail_closed(self):
        for payload in (None, {}, [], "untrusted", {"repository": None}, {"workflow_run": {}}):
            with self.subTest(payload=payload):
                self.assertFalse(source.trusted(payload))

    def test_workflow_handoff_has_no_direct_publication_authority(self):
        content = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("workflow_run:", content)
        self.assertIn(source.SOURCE_NAME, content)
        self.assertIn("github.event.workflow_run.status == 'completed'", content)
        self.assertIn("github.event.workflow_run.conclusion == 'success'", content)
        self.assertIn("github.event.workflow_run.event == 'workflow_dispatch'", content)
        self.assertIn("github.event.workflow_run.head_branch == 'main'", content)
        self.assertIn("github.event.workflow_run.head_repository.full_name == github.repository", content)
        self.assertIn("github.event_name != 'pull_request'", content)
        self.assertIn("scripts/grossesondes_festival_intake_trust.py --check-event", content)
        self.assertIn("vars.GROSSES_ONDES_CLOUD_SYNC == 'enabled'", content)
        self.assertIn("github.event_name == 'workflow_run') && vars.GROSSES_ONDES_CLOUD_SYNC", content)
        # A successful collector wakes the exact same independent publisher,
        # not an intake patch-to-catalogue copy.
        self.assertIn("python scripts/grossesondes_cloud_sync.py --mode", content)
        self.assertIn("git add -- docs/grossesondes/festivals.json reviews/grossesondes-published-head.json", content)
        first_guard = content.index("scripts/grossesondes_festival_intake_trust.py --check-event")
        first_publisher = content.index("python scripts/grossesondes_cloud_sync.py --mode")
        self.assertLess(first_guard, first_publisher)


if __name__ == "__main__":
    unittest.main()
