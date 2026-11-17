"""Pure host-side guards for the opt-in Android Auto MediaSession QEMU probe."""
from __future__ import annotations

import hashlib
import unittest
import subprocess
from unittest.mock import patch

import radio_catalog_android_auto_session_probe as session
import radio_catalog_flutter_provider_emulator_probe as base


class SessionProbeGuards(unittest.TestCase):
    def setUp(self):
        self.digest = hashlib.sha256(b"qemu-debug-example").hexdigest()
        self.uri = (
            f"content://{base.AUTHORITY}/central/{self.digest}.img"
        )
        self.fallback = (
            f"content://{base.AUTHORITY}/genre/go_genre_punk_v1"
        )
        self.log = (
            f"GO_AUTO_SESSION_READY sha={self.digest} uri={self.uri} "
            f"fallback={self.fallback} browse=2 playing=false"
        )

    @staticmethod
    def _cmd(content=b"", returncode=0):
        return subprocess.CompletedProcess([], returncode, content, b"")

    def test_strict_mode_refuses_preexisting_sha_without_read_or_delete(self):
        with patch.object(base, "adb", side_effect=[
            self._cmd(f"/data/user/0/{base.PACKAGE}".encode()),
            self._cmd(returncode=1),
            self._cmd(returncode=0),
        ]) as adb:
            with self.assertRaisesRegex(base.ProbeError, "existing SHA"):
                session.precheck_session_artwork(
                    "adb", "emulator-5554", self.digest, b"test",
                    allow_verified_existing=False,
                )
            self.assertEqual(adb.call_count, 3)
            self.assertTrue(all("rm" not in str(c) for c in adb.call_args_list))

    def test_mct_mode_reuses_only_exact_existing_sha(self):
        png = b"synthetic-test-PNG"
        with patch.object(base, "adb", side_effect=[
            self._cmd(f"/data/user/0/{base.PACKAGE}".encode()),
            self._cmd(returncode=1),
            self._cmd(returncode=0),
            self._cmd(png),
        ]) as adb:
            self.assertTrue(session.precheck_session_artwork(
                "adb", "emulator-5554", self.digest, png,
                allow_verified_existing=True,
            ))
            self.assertEqual(adb.call_count, 4)
            self.assertTrue(all("rm" not in str(c) for c in adb.call_args_list))

    def test_mct_mode_rejects_mismatched_sha_and_does_not_delete(self):
        with patch.object(base, "adb", side_effect=[
            self._cmd(f"/data/user/0/{base.PACKAGE}".encode()),
            self._cmd(returncode=1),
            self._cmd(returncode=0),
            self._cmd(b"different"),
        ]) as adb:
            with self.assertRaisesRegex(base.ProbeError, "refusing reuse"):
                session.precheck_session_artwork(
                    "adb", "emulator-5554", self.digest, b"trusted",
                    allow_verified_existing=True,
                )
            self.assertTrue(all("rm" not in str(c) for c in adb.call_args_list))

    def test_absent_sha_is_not_preemptively_modified(self):
        with patch.object(base, "adb", side_effect=[
            self._cmd(f"/data/user/0/{base.PACKAGE}".encode()),
            self._cmd(returncode=1),
            self._cmd(returncode=1),
        ]) as adb:
            self.assertFalse(session.precheck_session_artwork(
                "adb", "emulator-5554", self.digest, b"trusted",
                allow_verified_existing=True,
            ))
            self.assertEqual(adb.call_count, 3)
            self.assertTrue(all("rm" not in str(c) for c in adb.call_args_list))

    def test_debug_snapshot_directory_is_never_overwritten(self):
        with patch.object(base, "adb", side_effect=[
            self._cmd(f"/data/user/0/{base.PACKAGE}".encode()),
            self._cmd(returncode=0),
        ]) as adb:
            with self.assertRaisesRegex(base.ProbeError, "snapshot directory"):
                session.precheck_session_artwork(
                    "adb", "emulator-5554", self.digest, b"trusted",
                    allow_verified_existing=True,
                )
            self.assertEqual(adb.call_count, 2)

    def test_signed_sha_and_genre_attestation(self):
        self.assertEqual(
            session.validate_dart_log(self.log, self.digest),
            (self.uri, self.fallback),
        )

    def test_missing_or_tampered_attestation_rejected(self):
        for log in ("", self.log.replace("browse=2", "browse=0"),
                    self.log.replace(self.uri, "https://unsafe.example/x.png"),
                    self.log.replace(self.fallback, "content://wrong/genre/x")):
            with self.assertRaises(base.ProbeError):
                session.validate_dart_log(log, self.digest)

    def test_native_session_requires_exact_sha_and_app_package(self):
        good = f"MediaSessionRecord{{package={base.PACKAGE}}}\nmetadata={self.uri}"
        session.validate_native_dump(good, self.uri)
        for bad in (
            f"metadata={self.uri}",  # package is absent
            f"MediaSessionRecord{{package={base.PACKAGE}}} metadata=other",
            f"MediaSessionRecord{{package={base.PACKAGE}}} "
            f"metadata={self.uri.replace('.img', '.jpg')}",
        ):
            with self.assertRaises(base.ProbeError):
                session.validate_native_dump(bad, self.uri)


if __name__ == "__main__":
    unittest.main()
