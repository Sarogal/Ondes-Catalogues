"""Synthetic tests only. No real key material, environment or remote access."""
import os
import secrets
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import test_radio_daily_publication_simulator as fixture
from radio_daily_durable_lab_signer import DurableLabSigner
from radio_daily_durable_lab_store import DurableLabStore
from radio_daily_lab_signing import EphemeralLabSigner
from radio_daily_publication_simulator import publish, verify_visible
from radio_daily_v9_generator import digest


@unittest.skipUnless(os.name == "posix", "private POSIX key storage")
class DurableLabSignerTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.path = self.root / "key.pem"
        self.password = secrets.token_bytes(32)
        self.signer = DurableLabSigner.create(self.path, self.password)
        self.pin = dict(expected_public_key=self.signer.public_key,
                        expected_key_id=self.signer.key_id)

    def reopen(self):
        return DurableLabSigner.reopen(self.path, self.password, **self.pin)

    def test_encrypted_file_and_private_permissions(self):
        self.assertTrue(self.path.read_bytes().startswith(b"-----BEGIN ENCRYPTED PRIVATE KEY-----"))
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.reopen().key_id, self.signer.key_id)
        self.assertEqual(self.reopen().public_key, self.signer.public_key)

    def test_wrong_password_or_pin_refused(self):
        with self.assertRaisesRegex(ValueError, "decrypt"):
            DurableLabSigner.reopen(self.path, secrets.token_bytes(32), **self.pin)
        other = EphemeralLabSigner()
        with self.assertRaisesRegex(ValueError, "pin mismatch"):
            DurableLabSigner.reopen(self.path, self.password,
                expected_public_key=other.public_key, expected_key_id=other.key_id)

    def test_existing_key_never_overwritten(self):
        before = self.path.read_bytes()
        with self.assertRaises(FileExistsError):
            DurableLabSigner.create(self.path, self.password)
        self.assertEqual(self.path.read_bytes(), before)

    def test_concurrent_initialization_has_one_winner(self):
        path = self.root / "second.pem"
        def create(_):
            try:
                return DurableLabSigner.create(path, self.password)
            except FileExistsError:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            winners = [x for x in pool.map(create, range(2)) if x is not None]
        self.assertEqual(len(winners), 1)
        signer = winners[0]
        loaded = DurableLabSigner.reopen(path, self.password,
            expected_public_key=signer.public_key, expected_key_id=signer.key_id)
        self.assertEqual(loaded.public_key, signer.public_key)

    def test_public_permissions_and_symlink_refused(self):
        self.path.chmod(0o644)
        with self.assertRaisesRegex(ValueError, "unsafe"):
            self.reopen()
        self.path.chmod(0o600)
        link = self.root / "link.pem"
        link.symlink_to(self.path)
        with self.assertRaises(OSError):
            DurableLabSigner.reopen(link, self.password, **self.pin)
        self.root.chmod(0o755)
        try:
            with self.assertRaisesRegex(ValueError, "private POSIX"):
                self.reopen()
        finally:
            self.root.chmod(0o700)

    def test_weak_passphrase_and_corrupted_file_refused(self):
        with self.assertRaisesRegex(ValueError, "passphrase"):
            DurableLabSigner.create(self.root / "weak.pem", b"weak")
        self.path.write_bytes(b"corrupt")
        with self.assertRaisesRegex(ValueError, "encrypted"):
            self.reopen()

    def test_restarted_signer_and_store_publish_and_resume(self):
        f = fixture.PublicationSimulatorTests()
        f.setUp()
        anchor = dict(expected_sha=digest(f.raw), expected_sequence=8,
                      public_key=f.signer.public_key, key_id=f.signer.key_id)
        prior = self.signer.reanchor_verified_baseline(f.prior, f.raw, anchor=anchor)
        db = self.root / "lab.sqlite"
        key = dict(public_key=self.signer.public_key, key_id=self.signer.key_id)
        DurableLabStore.initialize(db, prior, f.raw, legacy_logos={fixture.URL: fixture.OLD}, **key)
        def run(checkpoint=None):
            return publish(DurableLabStore(db, **key), self.reopen(), prior, f.raw,
                           f.body, expected_sha=digest(f.raw), expected_sequence=8,
                           expected_candidate_sha=digest(f.body), day=fixture.DAY,
                           objects={f.path: fixture.DATA}, checkpoint=checkpoint)
        def stop(phase):
            if phase == "after_pointer_swap":
                raise RuntimeError("interrupted")
        with self.assertRaises(RuntimeError):
            run(stop)
        result = run()
        self.assertTrue(result["resumed"])
        self.assertFalse(result["publicationAllowed"])
        store = DurableLabStore(db, **key)
        verify_visible(store, store.current(), sha=digest(f.body),
                       sequence=9, signer=self.reopen())
