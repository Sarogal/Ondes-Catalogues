"""Offline adapter tests: real isolated init, simulated network push only."""
import base64
import os
import subprocess
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import test_radio_daily_github_transfer_contract as fixture
from radio_daily_github_executor import transmit_github
from radio_daily_git_lab_transport import REF


class GitHubExecutorTests(unittest.TestCase):
    def setUp(self):
        self.f = fixture.GitHubTransferContractTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.calls = []
        self.token = "fake_test_token_123"
        self.header = "Authorization: Basic "+base64.b64encode(
            ("x-access-token:"+self.token).encode()).decode()
        self.run = subprocess.run

    def run_stub(self, args, **kw):
        self.calls.append((args, kw))
        if args[1] == "init":
            return self.run(args, **kw)
        self.assertEqual(tuple(args[2:]), self.f.plan.push_args())
        self.assertIn("--force-with-lease="+REF+":"+self.f.base, args)
        self.assertNotIn(self.token, " ".join(args))
        self.assertNotIn(self.header, " ".join(args))
        env = kw["env"]
        self.assertNotIn("HTTPS_PROXY",env)
        self.assertNotIn("GIT_TRACE",env)
        self.assertEqual(env["GIT_CONFIG_GLOBAL"],os.devnull)
        self.assertEqual(env["GIT_CONFIG_VALUE_0"],"true")
        self.assertEqual(env["GIT_CONFIG_VALUE_1"],"false")
        self.assertEqual(env["GIT_CONFIG_VALUE_5"],self.header)
        repo = Path(args[1].split("=",1)[1])
        self.assertNotEqual(repo,self.f.source.repository)
        self.assertEqual((repo/"objects/info/alternates").read_text().strip(),
                         str(self.f.source.repository/"objects"))
        self.assertNotIn(self.token,(repo/"config").read_text())
        self.f.remote=self.f.commit
        return subprocess.CompletedProcess(args,0)

    def send(self, **kw):
        args = dict(read_head=self.f.head,read_tree=self.f.tree,
                    write_token=self.token,authorized=True)
        args.update(kw)
        return transmit_github(self.f.source,self.f.store,self.f.plan,**args)

    def test_isolated_push_and_retry(self):
        def dispatch(args,**kw):
            if len(args)>1 and (args[1]=="init" or
                    (args[1].startswith("--git-dir=") and "radio-github-transfer-" in args[1])):
                return self.run_stub(args,**kw)
            return self.run(args,**kw)
        with patch.dict(os.environ,{"HTTPS_PROXY":"http://invalid:123"}), \
             patch("radio_daily_github_executor.subprocess.run",side_effect=dispatch):
            self.assertEqual(self.send()["commit"],self.f.commit)
            self.assertTrue(self.send()["resumed"])
        self.assertEqual(len(self.calls),2)
        self.assertFalse(Path(self.calls[1][0][1].split("=",1)[1]).exists())

    def test_authorization_and_invalid_credentials_fail_closed(self):
        for patch_args in (dict(authorized=False),dict(authorized=1),
                           dict(write_token="bad\nheader"),dict(timeout=0)):
            with self.subTest(patch_args=patch_args), self.assertRaises(ValueError):
                self.send(**patch_args)
        self.assertFalse(self.calls)

    def test_wrong_ref_and_concurrent_head_never_push(self):
        original=self.f.plan
        self.f.plan=replace(original,ref="refs/heads/main")
        with self.assertRaisesRegex(ValueError,"unauthorized"):
            self.send()
        self.f.plan=original
        self.f.remote="2"*40
        with self.assertRaisesRegex(ValueError,"concurrency"):
            self.send()
        self.assertFalse(self.calls)

    def test_failed_push_is_sanitized_and_ref_rechecked(self):
        def dispatch(args,**kw):
            if len(args)>1 and args[1].startswith("--git-dir=") and "radio-github-transfer-" in args[1]:
                self.calls.append((args,kw))
                raise subprocess.TimeoutExpired(args,1)
            return self.run(args,**kw)
        with patch("radio_daily_github_executor.subprocess.run",side_effect=dispatch):
            with self.assertRaisesRegex(ValueError,"lease rejected or transfer failed") as error:
                self.send()
        self.assertNotIn(self.token,str(error.exception))
        self.assertEqual(self.f.remote,self.f.base)
        self.assertEqual(len(self.calls),1)
