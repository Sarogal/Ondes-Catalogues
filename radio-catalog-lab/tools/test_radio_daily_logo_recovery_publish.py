"""Synthetic signed logo recovery and restart coverage."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import test_radio_daily_logo_recovery_plan as fixture
from radio_daily_durable_lab_store import DurableLabStore
from radio_daily_lab_signing import EphemeralLabSigner
from radio_daily_logo_recovery_publish import publish_logo_recovery
from radio_daily_publication_simulator import verify_visible
from radio_daily_v9_generator import digest, encode


class SignedLogoRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.f = fixture.LogoRecoveryPlanTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.f.publish()
        self.store = self.f.store
        self.signer = self.f.f.signer
        self.prior = self.store.current()
        self.body, _ = self.f.plan()
        self.args = dict(expected_current_sha=digest(self.f.f.body),
            expected_current_sequence=9, historical_sequence=8,
            station_ids=[self.f.sid], day=fixture.fixture.DAY)

    def reopen(self):
        return DurableLabStore(self.f.path, **self.f.key)

    def recover(self, *, body=None, signer=None, store=None, **kw):
        args = dict(self.args, **kw)
        return publish_logo_recovery(store or self.store, signer or self.signer,
            self.body if body is None else body, **args)

    def test_signed_successor_and_verified_history(self):
        report = self.recover()
        self.assertTrue(report["signed"])
        self.assertFalse(report["publicationAllowed"])
        store = self.reopen()
        pointer = store.current()
        self.assertNotEqual(pointer, self.prior)
        verify_visible(store, pointer, sha=digest(self.body), sequence=10, signer=self.signer)
        self.assertEqual(store.historical(10), (pointer, self.body))
        self.assertEqual(store.historical(9)[0], self.prior)
        self.assertTrue(self.recover(store=store)["resumed"])

    def test_modified_candidate_refused_before_writes(self):
        doc = json.loads(self.body)
        doc["stations"][0]["display_name"] = "Unauthorized alteration"
        bad = encode(doc)
        with self.assertRaisesRegex(ValueError, "unauthorized recovery"):
            self.recover(body=bad)
        self.assertEqual(self.store.current(), self.prior)
        with self.assertRaises(KeyError):
            self.store.get("releases/" + digest(bad) + ".json")

    def test_wrong_signer_refused(self):
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            self.recover(signer=EphemeralLabSigner())
        self.assertEqual(self.store.current(), self.prior)

    def test_before_swap_interruption_resumes(self):
        def stop(phase):
            if phase == "before_pointer_swap":
                raise RuntimeError("interrupted")
        with self.assertRaises(RuntimeError):
            self.recover(checkpoint=stop)
        store = self.reopen()
        self.assertEqual(store.current(), self.prior)
        with self.assertRaises(KeyError):
            store.historical(10)
        self.assertFalse(self.recover(store=store)["resumed"])

    def test_after_swap_interruption_resumes_without_new_version(self):
        def stop(phase):
            if phase == "after_pointer_swap":
                raise RuntimeError("interrupted")
        with self.assertRaises(RuntimeError):
            self.recover(checkpoint=stop)
        store = self.reopen()
        pointer = store.current()
        self.assertTrue(self.recover(store=store)["resumed"])
        self.assertEqual(store.current(), pointer)
        with self.assertRaises(KeyError):
            store.historical(11)

    def test_stale_expected_digest_refused(self):
        with self.assertRaisesRegex(ValueError, "anchor"):
            self.recover(expected_current_sha="0"*64)
        self.assertEqual(self.store.current(), self.prior)
