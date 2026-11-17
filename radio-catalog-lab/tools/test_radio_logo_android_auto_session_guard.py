"""Pure host-side guards for the opt-in Android Auto MediaSession QEMU probe."""
from __future__ import annotations

import hashlib
import unittest

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
