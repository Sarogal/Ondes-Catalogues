"""Real Git push/receive-pack with synthetic releases, no network."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import test_radio_daily_git_lab_transport as fixture
from radio_daily_git_lab_transport import LocalGitLabTransport, REF, ZERO
from radio_daily_git_lab_transfer import transmit
from radio_daily_git_lab_reader import read_snapshot
from radio_daily_v9_generator import digest


@unittest.skipUnless(shutil.which("git"), "git required")
class GitLabTransferTests(unittest.TestCase):
    def setUp(self):
        self.f = fixture.GitLabTransportTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name)/"receiver.git"
        subprocess.run(["git", "init", "--bare", "--object-format=sha1", str(path)],
                       check=True, capture_output=True)
        self.receiver = LocalGitLabTransport(path)
        self.source = self.f.transport
        self.store = self.f.f.store
        self.old_sha = digest(self.f.f.f.raw)
        self.new_sha = digest(self.f.f.f.body)
        self.base = self.f.bootstrap()["commit"]

    def send(self, commit=None, lease=ZERO, sequence=8, sha=None, **kw):
        return transmit(self.source, self.receiver, self.store,
            expected_commit=commit or self.base, expected_remote_head=lease,
            expected_sequence=sequence, expected_sha=sha or self.old_sha, **kw)

    def advance(self):
        self.send()
        self.f.f.publish()
        return self.f.successor(self.base)["commit"]

    def successor(self, commit, **kw):
        return self.send(commit, self.base, 9, self.new_sha, **kw)

    def test_bootstrap_and_successor_remote_readback(self):
        commit = self.advance()
        result = self.successor(commit)
        self.assertFalse(result["publicationAllowed"])
        self.assertEqual(self.receiver.head(), commit)
        self.assertEqual(self.receiver._git("rev-list", "--count", REF), b"2\n")
        signer = self.f.f.f.signer
        selected = read_snapshot(self.receiver, expected_commit=commit,
            bootstrap_sha=self.old_sha, expected_sha=self.old_sha,
            expected_sequence=8, public_key=signer.public_key, key_id=signer.key_id)
        self.assertEqual(selected["body"], self.f.f.f.body)

    def test_interrupt_before_push(self):
        commit = self.advance()
        def stop(phase):
            if phase == "before_push":
                raise RuntimeError("interrupted")
        with self.assertRaises(RuntimeError):
            self.successor(commit, checkpoint=stop)
        self.assertEqual(self.receiver.head(), self.base)
        self.assertFalse(self.successor(commit)["resumed"])

    def test_interrupt_after_push_and_retry(self):
        commit = self.advance()
        def stop(phase):
            if phase == "after_push":
                raise RuntimeError("interrupted")
        with self.assertRaises(RuntimeError):
            self.successor(commit, checkpoint=stop)
        self.assertEqual(self.receiver.head(), commit)
        self.assertTrue(self.successor(commit)["resumed"])
        self.assertEqual(self.receiver._git("rev-list", "--count", REF), b"2\n")

    def test_concurrent_receiver_change_rejects_actual_lease(self):
        commit = self.advance()
        rival = self.receiver._stage({"unrelated.txt":b"rival"}, self.base)
        def race(phase):
            if phase == "before_push":
                self.receiver._git("update-ref", REF, rival, self.base)
        with self.assertRaisesRegex(ValueError, "lease rejected"):
            self.successor(commit, checkpoint=race)
        self.assertEqual(self.receiver.head(), rival)

    def test_source_anchor_and_wrong_parent_refused(self):
        commit = self.advance()
        with self.assertRaisesRegex(ValueError, "source Git anchor"):
            self.send()
        with self.assertRaisesRegex(ValueError, "direct child"):
            self.send(commit, "1"*40, 9, self.new_sha)
        self.assertEqual(self.receiver.head(), self.base)

    def test_same_repository_and_nonlocal_target_refused(self):
        args = dict(expected_commit=self.base, expected_remote_head=ZERO,
                    expected_sequence=8, expected_sha=self.old_sha)
        with self.assertRaisesRegex(ValueError, "distinct"):
            transmit(self.source, self.source, self.store, **args)
        with self.assertRaisesRegex(ValueError, "two local"):
            transmit(self.source, "https://github.com/example/repo.git", self.store, **args)
        self.assertEqual(self.receiver.head(), ZERO)
