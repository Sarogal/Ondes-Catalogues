"""Remote acceptance contract; network adapters replaced by exact fixtures."""
import unittest
from unittest.mock import Mock, patch
from radio_daily_remote_acceptance import verify_remote
from radio_daily_github_readback import GitHubReadback
from radio_daily_git_lab_transport import snapshot
import test_radio_daily_deployment_verify as fixture


class RemoteAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.f = fixture.DeploymentVerifyTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.reader = GitHubReadback(lambda *args:None)
        self.reader.read_head = Mock(return_value=self.f.commit)
        self.reader.read_tree = Mock(return_value=snapshot(self.f.store,9))
        self.args = {k:v for k,v in self.f.args.items() if k not in
                     ("deployment_commit","deployment_status")}
        self.args.update(reader=self.reader,deployment_id=42,
                         environment="radio-lab-publisher-rehearsal")

    def verify(self, **kw):
        args = dict(self.args, **kw)
        with patch("radio_daily_remote_acceptance.PublicHTTPSReader",
                   side_effect=[Mock(),self.f.fetch]), \
             patch("radio_daily_remote_acceptance.deployment_status",
                   return_value={"deploymentId":42}):
            return verify_remote(**args)

    def test_remote_exact_history_and_public_bytes(self):
        report = self.verify()
        self.assertTrue(report["remoteReadbackVerified"])
        self.assertTrue(report["deploymentVerified"])
        self.assertFalse(report["simulated"])
        self.assertFalse(report["publicationAllowed"])
        self.assertEqual(report["selectedSequence"],9)

    def test_wrong_environment_and_ref_refused(self):
        with self.assertRaisesRegex(ValueError,"environment"):
            self.verify(environment="github-pages")
        self.reader.read_head.return_value = "a"*40
        with self.assertRaisesRegex(ValueError,"anchor"):
            self.verify()
        self.reader.read_tree.assert_not_called()

    def test_unreferenced_remote_blob_refused(self):
        self.reader.read_tree.return_value["history/99.json"]=b"{}"
        with self.assertRaises(ValueError):
            self.verify()
        self.assertEqual(self.f.calls,[])

    def test_stale_public_pointer_refused(self):
        from dataclasses import replace
        from radio_daily_deployment_verify import POINTER_URL
        self.f.responses[POINTER_URL]=replace(self.f.responses[POINTER_URL],
            body=self.f.store.historical(8)[0])
        with self.assertRaisesRegex(ValueError,"public pointer differs"):
            self.verify()
