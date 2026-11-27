"""Synthetic-only persistence and restart tests for the SQLite lab backend."""
import copy
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import test_radio_daily_publication_simulator as fixture
from radio_daily_durable_lab_store import DurableLabStore
from radio_daily_lab_signing import EphemeralLabSigner
from radio_daily_publication_simulator import publish, verify_visible
from radio_daily_v9_generator import digest, encode


class DurableLabStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "lab.sqlite"
        self.f = fixture.PublicationSimulatorTests()
        self.f.setUp()
        self.signer = self.f.signer
        self.key = dict(public_key=self.signer.public_key, key_id=self.signer.key_id)
        self.store = DurableLabStore.initialize(
            self.path, self.f.prior, self.f.raw, legacy_logos={fixture.URL: fixture.OLD},
            **self.key)

    def reopen(self):
        return DurableLabStore(self.path, **self.key)

    def run_publish(self, store=None, body=None, **kw):
        body = self.f.body if body is None else body
        args = dict(expected_sha=digest(self.f.raw), expected_sequence=8,
                    expected_candidate_sha=digest(body), day=fixture.DAY,
                    objects={self.f.path: fixture.DATA})
        args.update(kw)
        return publish(store or self.store, self.signer, self.f.prior,
                       self.f.raw, body, **args)

    def test_reopen_baseline_and_legacy_artwork(self):
        store = self.reopen()
        self.assertEqual(store.current(), self.f.prior)
        self.assertEqual(store.logo(fixture.URL), fixture.OLD)
        verify_visible(store, self.f.prior, sha=digest(self.f.raw),
                       sequence=8, signer=self.signer)

    def test_restart_before_pointer_swap(self):
        def stop(phase):
            if phase == "before_pointer_swap":
                raise RuntimeError("interrupted")
        with self.assertRaises(RuntimeError):
            self.run_publish(checkpoint=stop)
        store = self.reopen()
        self.assertEqual(store.current(), self.f.prior)
        self.assertEqual(store.get("releases/" + digest(self.f.body) + ".json"), self.f.body)
        self.assertFalse(self.run_publish(store=store)["publicationAllowed"])
        verify_visible(self.reopen(), store.current(), sha=digest(self.f.body),
                       sequence=9, signer=self.signer)

    def test_restart_after_pointer_swap(self):
        def stop(phase):
            if phase == "after_pointer_swap":
                raise RuntimeError("interrupted")
        with self.assertRaises(RuntimeError):
            self.run_publish(checkpoint=stop)
        store = self.reopen()
        pointer = store.current()
        self.assertTrue(self.run_publish(store=store)["resumed"])
        self.assertEqual(self.reopen().current(), pointer)

    def test_missing_artwork_keeps_pointer(self):
        with self.assertRaises(KeyError):
            self.run_publish(objects={})
        self.assertEqual(self.reopen().current(), self.f.prior)

    def test_content_address_and_path_validation(self):
        path = "objects/sha256/" + self.f.path
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            self.store.put_immutable(path, fixture.OLD)
        with self.assertRaisesRegex(ValueError, "path"):
            self.store.put_immutable("../pointer", b"x")
        self.store.put_immutable(path, fixture.DATA)
        self.store.put_immutable(path, fixture.DATA)
        self.assertEqual(self.reopen().get(path), fixture.DATA)

    def test_corruption_detected_on_reopen(self):
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE objects SET data=? WHERE path=?",
                       (b"corrupt", "releases/" + digest(self.f.raw) + ".json"))
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            self.reopen()

    def test_wrong_key_and_reinitialization_refused(self):
        wrong = EphemeralLabSigner()
        with self.assertRaises(Exception):
            DurableLabStore(self.path, public_key=wrong.public_key, key_id=wrong.key_id)
        with self.assertRaisesRegex(ValueError, "laboratory key"):
            DurableLabStore(self.path, public_key=self.signer.public_key, key_id="production")
        with self.assertRaises(sqlite3.OperationalError):
            DurableLabStore.initialize(
                self.path, self.f.prior, self.f.raw,
                legacy_logos={fixture.URL: fixture.OLD}, **self.key)
        self.assertEqual(self.reopen().current(), self.f.prior)

    def test_competing_independent_handles(self):
        other = copy.deepcopy(self.f.new)
        other["stations"][0]["display_name"] = "Competing Radio"
        bodies = [self.f.body, encode(other)]
        barrier = Barrier(2)
        def run(body):
            store = self.reopen()
            def sync(phase):
                if phase == "before_pointer_swap":
                    barrier.wait(timeout=10)
            try:
                self.run_publish(store=store, body=body, checkpoint=sync)
                return digest(body)
            except ValueError as exc:
                self.assertIn("concurrency conflict", str(exc))
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(run, bodies))
        winners = [x for x in outcomes if x]
        self.assertEqual(len(winners), 1)
        store = self.reopen()
        verify_visible(store, store.current(), sha=winners[0], sequence=9,
                       signer=self.signer)

    def test_pointer_cannot_roll_back_by_cas(self):
        self.run_publish()
        store = self.reopen()
        pointer = store.current()
        with self.assertRaisesRegex(ValueError, "non-successor"):
            store.compare_and_swap(pointer, self.f.prior)
        self.assertEqual(self.reopen().current(), pointer)
