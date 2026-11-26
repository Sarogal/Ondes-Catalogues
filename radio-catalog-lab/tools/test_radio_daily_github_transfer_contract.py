"""Injected GitHub transport tests. No requests or credentials."""
import unittest
from dataclasses import replace

import test_radio_daily_git_lab_transport as fixture
from radio_daily_git_lab_transport import REF, ZERO, snapshot
from radio_daily_github_transfer_contract import DESTINATION, prepare, transmit
from radio_daily_v9_generator import digest


class GitHubTransferContractTests(unittest.TestCase):
    def setUp(self):
        self.f = fixture.GitLabTransportTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.source = self.f.transport
        self.store = self.f.f.store
        self.base = self.f.bootstrap()["commit"]
        self.f.f.publish()
        self.commit = self.f.successor(self.base)["commit"]
        self.args = dict(destination=DESTINATION, ref=REF, expected_commit=self.commit,
            expected_remote_head=self.base, expected_sequence=9,
            expected_sha=digest(self.f.f.f.body))
        self.plan = prepare(self.source, self.store, **self.args)
        self.remote = self.base
        self.trees = {self.base:snapshot(self.store,8), self.commit:snapshot(self.store,9)}
        self.executions = []

    def head(self, destination, ref):
        self.assertEqual((destination,ref),(DESTINATION,REF))
        return self.remote

    def tree(self, destination, commit):
        self.assertEqual(destination,DESTINATION)
        return self.trees[commit]

    def execute(self, args):
        self.executions.append(args)
        self.assertIn("--force-with-lease="+REF+":"+self.base,args)
        self.assertEqual(args[-2:],(DESTINATION,self.commit+":"+REF))
        if self.remote != self.base:
            raise ValueError("lease rejected")
        self.remote = self.commit

    def send(self, **kw):
        args = dict(read_head=self.head,read_tree=self.tree,execute=self.execute)
        args.update(kw)
        return transmit(self.source,self.store,self.plan,**args)

    def test_exact_successor_and_idempotent_retry(self):
        result = self.send()
        self.assertEqual(result["commit"],self.commit)
        self.assertFalse(result["publicationAllowed"])
        self.assertFalse(result["deploymentVerified"])
        self.assertTrue(self.send()["resumed"])
        self.assertEqual(len(self.executions),1)

    def test_wrong_destination_and_branch_refused(self):
        for patch in (dict(destination="https://github.com/other/repo.git"),
                      dict(ref="refs/heads/main"),
                      dict(ref="refs/heads/state/go-radio-discovery-preview")):
            with self.subTest(patch=patch),self.assertRaisesRegex(ValueError,"unauthorized"):
                prepare(self.source,self.store,**dict(self.args,**patch))
        self.assertFalse(self.executions)

    def test_wrong_parent_and_tampered_plan_refused(self):
        with self.assertRaisesRegex(ValueError,"non-fast-forward"):
            prepare(self.source,self.store,**dict(self.args,expected_remote_head="1"*40))
        self.plan=replace(self.plan,ref="refs/heads/main")
        with self.assertRaisesRegex(ValueError,"unauthorized"):
            self.send()
        self.assertFalse(self.executions)

    def test_concurrent_head_refused_without_write(self):
        self.remote="2"*40
        with self.assertRaisesRegex(ValueError,"concurrency"):
            self.send()
        self.assertFalse(self.executions)

    def test_remote_predecessor_corruption_refused(self):
        self.trees[self.base]=dict(self.trees[self.base],unexpected=b"bad")
        with self.assertRaisesRegex(ValueError,"tree readback"):
            self.send()
        self.assertFalse(self.executions)

    def test_lost_acknowledgement_recovers_exact_commit(self):
        def lost(args):
            self.execute(args)
            raise OSError("lost acknowledgement")
        self.assertEqual(self.send(execute=lost)["commit"],self.commit)
        self.assertTrue(self.send()["resumed"])

    def test_race_during_push_never_replaces_competing_commit(self):
        def race(args):
            self.remote="3"*40
            self.execute(args)
        with self.assertRaisesRegex(ValueError,"lease rejected"):
            self.send(execute=race)
        self.assertEqual(self.remote,"3"*40)

    def test_remote_success_without_complete_tree_refused(self):
        self.trees[self.commit]={}
        with self.assertRaisesRegex(ValueError,"tree readback"):
            self.send()
        self.assertEqual(self.remote,self.commit)
        self.assertEqual(len(self.executions),1)
