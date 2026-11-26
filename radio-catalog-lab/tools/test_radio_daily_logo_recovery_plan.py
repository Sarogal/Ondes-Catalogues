"""Synthetic laboratory history and narrow rollback plan tests."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import test_radio_daily_publication_simulator as fixture
from radio_daily_durable_lab_store import DurableLabStore
from radio_daily_logo_recovery_plan import plan_logo_recovery
from radio_daily_publication_simulator import publish
from radio_daily_v9_generator import digest


class LogoRecoveryPlanTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "lab.sqlite"
        self.f = fixture.PublicationSimulatorTests()
        self.f.setUp()
        self.key = dict(public_key=self.f.signer.public_key, key_id=self.f.signer.key_id)
        self.store = DurableLabStore.initialize(
            self.path, self.f.prior, self.f.raw, legacy_logos={fixture.URL: fixture.OLD},
            **self.key)
        self.sid = self.f.new["stations"][0]["go_station_id"]

    def publish(self, checkpoint=None):
        return publish(self.store, self.f.signer, self.f.prior, self.f.raw, self.f.body,
                       expected_sha=digest(self.f.raw), expected_sequence=8,
                       expected_candidate_sha=digest(self.f.body), day=fixture.DAY,
                       objects={self.f.path: fixture.DATA}, checkpoint=checkpoint)

    def plan(self, **kw):
        args = dict(expected_current_sha=digest(self.f.body), historical_sequence=8,
                    station_ids=[self.sid], day=fixture.DAY)
        args.update(kw)
        return plan_logo_recovery(self.store, **args)

    def test_history_contains_only_activated_releases(self):
        def stop(phase):
            if phase == "before_pointer_swap":
                raise RuntimeError("interrupted")
        with self.assertRaises(RuntimeError):
            self.publish(stop)
        self.assertEqual(self.store.historical(8), (self.f.prior, self.f.raw))
        with self.assertRaises(KeyError):
            self.store.historical(9)
        self.publish()
        store = DurableLabStore(self.path, **self.key)
        self.assertEqual(store.historical(9), (store.current(), self.f.body))

    def test_recovery_is_monotonic_and_preserves_every_other_field(self):
        self.publish()
        pointer = self.store.current()
        raw, report = self.plan()
        expected = json.loads(self.f.body)
        prior = json.loads(self.f.raw)["stations"][0]["logo"]
        expected["stations"][0]["logo"] = dict(
            prior, revision=expected["stations"][0]["logo"]["revision"]+1)
        expected["release_sequence"] = 10
        self.assertEqual(json.loads(raw), expected)
        self.assertEqual(report["candidateSha256"], digest(raw))
        self.assertFalse(report["signed"])
        self.assertFalse(report["publicationAllowed"])
        self.assertEqual(self.store.current(), pointer)
        with self.assertRaises(KeyError):
            self.store.historical(10)

    def test_stale_anchor_and_unselected_station_refused(self):
        self.publish()
        with self.assertRaisesRegex(ValueError, "anchor"):
            self.plan(expected_current_sha=digest(self.f.raw))
        with self.assertRaisesRegex(ValueError, "station missing"):
            self.plan(station_ids=["not-in-catalogue"])
        with self.assertRaisesRegex(ValueError, "distinct"):
            self.plan(station_ids=[self.sid, self.sid])

    def test_invalid_sequence_refused(self):
        self.publish()
        for seq in (7, 9, 10, True):
            with self.subTest(seq=seq), self.assertRaisesRegex(ValueError, "older"):
                self.plan(historical_sequence=seq)

    def test_old_artwork_corruption_refuses_recovery(self):
        self.publish()
        old_sha = json.loads(self.f.raw)["stations"][0]["logo"]["sha256"]
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE objects SET data=? WHERE path LIKE ?",
                       (b"corrupt", "objects/sha256/"+old_sha+".%"))
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            self.plan()
        self.assertEqual(json.loads(self.store.current())["release_sequence"], 9)

    def test_silent_pointer_regression_detected_on_reopen(self):
        self.publish()
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE pointer SET data=? WHERE id=1", (self.f.prior,))
        with self.assertRaisesRegex(ValueError, "history mismatch"):
            DurableLabStore(self.path, **self.key)
