"""Public-only Git snapshot verification and resume (synthetic data)."""
import json
import unittest

import test_radio_daily_git_lab_transport as fixture
from radio_daily_git_lab_reader import read_snapshot, prepare_from_git
from radio_daily_git_lab_transport import REF
from radio_daily_lab_signing import EphemeralLabSigner
from radio_daily_v9_generator import digest


class GitLabReaderTests(unittest.TestCase):
    def setUp(self):
        self.f = fixture.GitLabTransportTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.transport = self.f.transport
        self.store = self.f.f.store
        self.base = self.f.bootstrap()["commit"]
        self.signer = self.f.f.f.signer
        self.sha = digest(self.f.f.f.raw)
        self.anchor = dict(bootstrap_sha=self.sha, expected_sha=self.sha,
                           expected_sequence=8, public_key=self.signer.public_key,
                           key_id=self.signer.key_id)

    def read(self, **kw):
        args = dict(self.anchor, expected_commit=self.transport.head())
        args.update(kw)
        return read_snapshot(self.transport, **args)

    def successor(self):
        self.f.f.publish()
        return self.f.successor(self.base)["commit"]

    def replace_tree(self, transform):
        from radio_daily_git_lab_transport import snapshot
        old = self.transport.head()
        sequence = json.loads(self.store.current())["release_sequence"]
        files = snapshot(self.store, sequence)
        transform(files)
        new = self.transport._stage(files, old)
        self.transport._git("update-ref", REF, new, old)
        return new

    def test_bootstrap_and_same_version_prepare(self):
        selected = self.read()
        self.assertEqual(selected["body"], self.f.f.f.raw)
        raw, report, migrated, context = prepare_from_git(self.transport,
            day=fixture.fixture.fixture.DAY, state={}, expected_commit=self.base, **self.anchor)
        self.assertEqual(raw, selected["body"])
        self.assertFalse(report["advanced"])
        self.assertEqual(migrated, {})
        self.assertEqual(context["gitCommit"], self.base)

    def test_select_successor_without_private_key(self):
        head = self.successor()
        selected = self.read(expected_commit=head)
        self.assertEqual(selected["sequence"], 9)
        self.assertEqual(selected["body"], self.f.f.f.body)
        self.assertEqual(selected["anchor_body"], self.f.f.f.raw)
        again = self.read(expected_sequence=9, expected_sha=digest(selected["body"]))
        self.assertEqual(again["anchor_body"], selected["body"])

    def test_advancement_requires_complete_migration_reports(self):
        head = self.successor()
        with self.assertRaisesRegex(ValueError, "complete predecessor evidence"):
            prepare_from_git(self.transport, day=fixture.fixture.fixture.DAY,
                state={}, expected_commit=head, **self.anchor)

    def test_wrong_head_and_equivocation_refused(self):
        self.successor()
        with self.assertRaisesRegex(ValueError, "head anchor"):
            self.read(expected_commit=self.base)
        with self.assertRaisesRegex(ValueError, "equivocation"):
            self.read(expected_sha="0"*64)

    def test_wrong_key_and_missing_history_refused(self):
        self.successor()
        other = EphemeralLabSigner()
        with self.assertRaises(ValueError):
            self.read(public_key=other.public_key, key_id=other.key_id)
        self.replace_tree(lambda files: files.pop("history/8.json"))
        with self.assertRaisesRegex(ValueError, "incomplete Git release history"):
            self.read()

    def test_corrupt_artwork_and_extra_files_refused(self):
        self.successor()
        path = "objects/sha256/" + self.f.f.f.path
        self.replace_tree(lambda files: files.update({path:b"x"}))
        with self.assertRaisesRegex(ValueError, "length mismatch"):
            self.read()
        self.replace_tree(lambda files: files.update({"private.pem":b"x"}))
        with self.assertRaisesRegex(ValueError, "unexpected"):
            self.read()

    def test_rollback_refused(self):
        with self.assertRaisesRegex(ValueError, "rollback"):
            self.read(expected_sequence=9)
