"""Offline tests for the standalone Android Auto DHU APK identity guard."""
from __future__ import annotations

import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import radio_catalog_dhu_apk_guard as guard


class StandaloneDhuGuardTests(unittest.TestCase):
    def setUp(self):
        self.badging = (
            "package: name='fr.grossesondes.grosses_ondes.dhudiag' "
            "versionCode='64' versionName='0.3.0'\n"
            "application-label:'GO Diagnostic SHA'\n"
        )
        self.manifest = (
            'A: android:debuggable(0x0101000f)=(type 0x12)0xffffffff\n'
            'A: android:name="fr.grossesondes.grosses_ondes.StationLogoContentProvider"\n'
            'A: android:authorities(0x01010018)="'
            'fr.grossesondes.grosses_ondes.dhudiag.stationlogos"\n'
            'A: android:name="com.ryanheise.audioservice.AudioService"\n'
            'A: android:name="com.google.android.gms.car.application"\n'
        )
        self.debug_digest = 'a' * 64
        self.signing = (
            'Signer #1 certificate DN: CN=Local Debug Build\n'
            f'Signer #1 certificate SHA-256 digest: {self.debug_digest}\n'
        )

    def assert_bad(self, *, badging=None, manifest=None, signing=None, expected=None):
        with self.assertRaises(guard.ApkGuardError):
            guard.check_metadata(
                self.badging if badging is None else badging,
                self.manifest if manifest is None else manifest,
                self.signing if signing is None else signing,
                self.debug_digest if expected is None else expected,
            )

    def test_exact_diagnostic_passes(self):
        guard.check_metadata(self.badging, self.manifest, self.signing,
                             self.debug_digest)

    def test_production_package_rejected(self):
        self.assert_bad(badging=self.badging.replace(
            "grosses_ondes.dhudiag", "grosses_ondes"))

    def test_missing_or_wrong_label_rejected(self):
        self.assert_bad(badging=self.badging.replace(
            "GO Diagnostic SHA", "Grosses Ondes"))

    def test_production_provider_rejected(self):
        self.assert_bad(manifest=self.manifest.replace(
            "grosses_ondes.dhudiag.stationlogos",
            "grosses_ondes.stationlogos"))

    def test_no_provider_rejected(self):
        self.assert_bad(manifest=self.manifest.replace(
            "StationLogoContentProvider", "NotAContentProvider"))

    def test_audio_service_or_auto_declaration_required(self):
        self.assert_bad(manifest=self.manifest.replace(
            "com.ryanheise.audioservice.AudioService", "invalid.Service"))
        self.assert_bad(manifest=self.manifest.replace(
            "com.google.android.gms.car.application", "invalid.car"))

    def test_debuggable_flag_required(self):
        self.assert_bad(manifest=self.manifest.replace(
            "0xffffffff", "0x00000000"))

    def test_signing_certificate_must_match_local_debug_fingerprint(self):
        self.assert_bad(signing=self.signing.replace('a' * 64, 'b' * 64))

    def test_cert_dn_is_not_used_as_an_unreliable_security_signal(self):
        value = self.signing.replace('Local Debug Build', 'Nonstandard Subject')
        guard.check_metadata(self.badging, self.manifest, value,
                             self.debug_digest)

    def test_missing_signer_digest_rejected(self):
        self.assert_bad(signing='Signer #1 certificate DN: CN=Android Debug')

    def test_second_certificate_rejected(self):
        self.assert_bad(signing=self.signing +
                        f'Signer #2 certificate SHA-256 digest: {"b" * 64}\n')

    def test_invalid_expected_debug_fingerprint_rejected(self):
        self.assert_bad(expected='unknown')

    def test_debug_keystore_public_certificate_hash(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            (home / 'debug.keystore').write_bytes(b'fake keystore')
            kt = home / 'keytool.exe'
            kt.touch()
            public_der = b'\x30' + b'x' * 192
            output = subprocess.CompletedProcess([], 0, public_der, b'')
            with patch.dict(guard.os.environ, {'ANDROID_USER_HOME': td},
                            clear=True), \
                 patch.object(guard.shutil, 'which', return_value=str(kt)), \
                 patch.object(guard.subprocess, 'run', return_value=output) as run:
                self.assertEqual(guard.local_debug_certificate_sha256(),
                                 hashlib.sha256(public_der).hexdigest())
                args = run.call_args.args[0]
                self.assertIn('-exportcert', args)
                self.assertIn('androiddebugkey', args)
                self.assertNotIn('-importkeystore', args)

    def test_missing_local_debug_keystore_refused(self):
        with tempfile.TemporaryDirectory() as td, \
             patch.dict(guard.os.environ, {'ANDROID_USER_HOME': td},
                        clear=True):
            with self.assertRaisesRegex(guard.ApkGuardError,
                                        'Debug keystore missing'):
                guard.local_debug_certificate_sha256()

    def test_duplicate_provider_authority_rejected(self):
        self.assert_bad(manifest=self.manifest + (
            'A: android:authorities="'
            'fr.grossesondes.grosses_ondes.dhudiag.stationlogos"\n'
        ))


if __name__ == "__main__":
    unittest.main()
