"""Real local Git object/ref tests using synthetic catalogues only."""
import json
import shutil
import subprocess
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import test_radio_daily_logo_recovery_plan as fixture
from radio_daily_git_lab_transport import LocalGitLabTransport, REF, ZERO
from radio_daily_v9_generator import digest


@unittest.skipUnless(shutil.which("git"), "git required")
class GitLabTransportTests(unittest.TestCase):
    def setUp(self):
        self.f = fixture.LogoRecoveryPlanTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.repo = Path(temp.name)/"remote.git"
        subprocess.run(["git", "init", "--bare", "--object-format=sha1", str(self.repo)],
                       check=True, capture_output=True)
        self.transport = LocalGitLabTransport(self.repo)

    def bootstrap(self, **kw):
        return self.transport.publish(self.f.store, expected_head=ZERO,
            expected_sequence=8, expected_sha=digest(self.f.f.raw), **kw)

    def successor(self, head, **kw):
        return self.transport.publish(self.f.store, expected_head=head,
            expected_sequence=9, expected_sha=digest(self.f.f.body), **kw)

    def test_bootstrap_and_successor_one_commit_each(self):
        first = self.bootstrap()
        self.f.publish()
        second = self.successor(first["commit"])
        self.assertFalse(second["publicationAllowed"])
        self.assertEqual(self.transport.head(), second["commit"])
        self.assertEqual(self.transport._git("rev-list", "--count", REF), b"2\n")
        self.assertEqual(self.transport._git("show", REF+":history/8.json"), self.f.f.prior)
        self.assertEqual(self.transport._git("show", REF+":pointer.json"), self.f.store.current())
        self.assertEqual(self.transport._git("show", REF+":releases/"+digest(self.f.f.body)+".json"), self.f.f.body)
        self.assertEqual(self.transport._git("show", REF+":objects/sha256/"+self.f.f.path), fixture.fixture.DATA)

    def test_interrupt_before_swap_and_retry(self):
        first = self.bootstrap()["commit"]
        self.f.publish()
        def stop(phase):
            if phase == "before_ref_swap":
                raise RuntimeError("interrupted")
        with self.assertRaises(RuntimeError):
            self.successor(first, checkpoint=stop)
        self.assertEqual(self.transport.head(), first)
        self.assertFalse(self.successor(first)["resumed"])

    def test_interrupt_after_swap_and_retry(self):
        first = self.bootstrap()["commit"]
        self.f.publish()
        def stop(phase):
            if phase == "after_ref_swap":
                raise RuntimeError("interrupted")
        with self.assertRaises(RuntimeError):
            self.successor(first, checkpoint=stop)
        head = self.transport.head()
        reopened = LocalGitLabTransport(self.repo)
        self.transport = reopened
        self.assertTrue(self.successor(first)["resumed"])
        self.assertEqual(reopened.head(), head)
        self.assertEqual(reopened._git("rev-list", "--count", REF), b"2\n")

    def test_wrong_anchor_and_skipped_bootstrap_refused(self):
        with self.assertRaisesRegex(ValueError, "anchor"):
            self.transport.publish(self.f.store, expected_head=ZERO,
                expected_sequence=8, expected_sha="0"*64)
        self.f.publish()
        with self.assertRaisesRegex(ValueError, "bootstrap"):
            self.successor(ZERO)
        self.assertEqual(self.transport.head(), ZERO)

    def test_two_writers_one_atomic_ref_swap(self):
        first = self.bootstrap()["commit"]
        self.f.publish()
        barrier = Barrier(2)
        def writer(_):
            local = LocalGitLabTransport(self.repo)
            def checkpoint(phase):
                if phase == "before_ref_swap":
                    barrier.wait(timeout=15)
            try:
                return local.publish(self.f.store, expected_head=first,
                    expected_sequence=9, expected_sha=digest(self.f.f.body),
                    checkpoint=checkpoint)["commit"]
            except ValueError as exc:
                self.assertIn("concurrency conflict", str(exc))
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(writer, range(2)))
        self.assertEqual(sum(x is not None for x in results), 1)
        self.assertEqual(self.transport._git("rev-list", "--count", REF), b"2\n")

    def test_unrelated_tree_never_overwritten(self):
        first = self.bootstrap()["commit"]
        self.f.publish()
        alien = self.transport._stage({"unexpected.txt":b"alien"}, first)
        self.transport._git("update-ref", REF, alien, first)
        with self.assertRaisesRegex(ValueError, "unexpected rehearsal"):
            self.successor(first)
        self.assertEqual(self.transport.head(), alien)
