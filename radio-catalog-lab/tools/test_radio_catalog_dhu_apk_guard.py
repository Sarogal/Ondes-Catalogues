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

    def test_host_platform_sdk_binary_names_are_recognized(self):
        with tempfile.TemporaryDirectory() as td:
            sdk = Path(td)
            target = sdk / "build-tools" / "36.0.0"
            target.mkdir(parents=True)
            aapt = target / ("aapt.exe" if guard.os.name == "nt" else "aapt")
            signer = target / (
                "apksigner.bat" if guard.os.name == "nt" else "apksigner"
            )
            aapt.write_bytes(b"fake")
            signer.write_bytes(b"fake")
            self.assertEqual(guard.find_tools(sdk), (aapt, signer))

    def test_https_profile_accepts_only_second_isolated_package(self):
        new_badging = self.badging.replace(
            "grosses_ondes.dhudiag", "grosses_ondes.dhunetdiag",
        ).replace("GO Diagnostic SHA", "GO HTTPS Diagnostic")
        new_manifest = self.manifest.replace(
            "grosses_ondes.dhudiag.stationlogos",
            "grosses_ondes.dhunetdiag.stationlogos",
        )
        guard.check_metadata(
            new_badging, new_manifest, self.signing, self.debug_digest,
            profile="https",
        )
        with self.assertRaises(guard.ApkGuardError):
            guard.check_metadata(
                new_badging, new_manifest, self.signing, self.debug_digest,
                profile="sha",
            )

    def test_https_profile_refuses_original_debug_and_public_app(self):
        with self.assertRaises(guard.ApkGuardError):
            guard.check_metadata(
                self.badging, self.manifest, self.signing, self.debug_digest,
                profile="https",
            )
        public = self.badging.replace("grosses_ondes.dhudiag",
                                      "grosses_ondes")
        with self.assertRaises(guard.ApkGuardError):
            guard.check_metadata(
                public, self.manifest, self.signing, self.debug_digest,
                profile="https",
            )

    def test_https_profile_rejects_wrong_authority_and_label(self):
        new_badging = self.badging.replace(
            "grosses_ondes.dhudiag", "grosses_ondes.dhunetdiag",
        ).replace("GO Diagnostic SHA", "GO HTTPS Diagnostic")
        new_manifest = self.manifest.replace(
            "grosses_ondes.dhudiag.stationlogos",
            "grosses_ondes.dhunetdiag.stationlogos",
        )
        with self.assertRaises(guard.ApkGuardError):
            guard.check_metadata(
                new_badging,
                new_manifest.replace(
                    "grosses_ondes.dhunetdiag.stationlogos",
                    "grosses_ondes.stationlogos",
                ),
                self.signing, self.debug_digest, profile="https",
            )
        with self.assertRaises(guard.ApkGuardError):
            guard.check_metadata(
                new_badging.replace("GO HTTPS Diagnostic", "Grosses Ondes"),
                new_manifest, self.signing, self.debug_digest,
                profile="https",
            )
        with self.assertRaises(guard.ApkGuardError):
            guard.check_metadata(
                new_badging, new_manifest, self.signing,
                "b" * 64, profile="https",
            )

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

    def test_observed_windows_v2_signer_format_is_supported(self):
        # Actual apksigner output on the Windows user workstation (2026-11-18).
        signer = (
            'V2 Signer: certificate SHA-256 digest: '
            f'{self.debug_digest}\n'
        )
        guard.check_metadata(
            self.badging, self.manifest, signer, self.debug_digest,
        )

    def test_versioned_v3_scheme_signer_format_is_supported(self):
        signer = (
            'V3.0 Signer: certificate SHA-256 digest: '
            f'{self.debug_digest}\n'
        )
        guard.check_metadata(
            self.badging, self.manifest, signer, self.debug_digest,
        )

    def test_mixed_v2_and_v3_scheme_labels_same_key_are_supported(self):
        signer = (
            f'V2 Signer: certificate SHA-256 digest: {self.debug_digest}\n'
            f'V3.0 Signer: certificate SHA-256 digest: {self.debug_digest}\n'
        )
        guard.check_metadata(
            self.badging, self.manifest, signer, self.debug_digest,
        )

    def test_mixed_scheme_different_certificate_is_rejected(self):
        signer = (
            f'V2 Signer: certificate SHA-256 digest: {self.debug_digest}\n'
            f'V3.0 Signer: certificate SHA-256 digest: {"b" * 64}\n'
        )
        self.assert_bad(signing=signer)

    def test_multiple_numbered_scheme_signers_are_rejected(self):
        signer = (
            f'V2 Signer: certificate SHA-256 digest: {self.debug_digest}\n'
            f'Signer #2 certificate SHA-256 digest: {self.debug_digest}\n'
        )
        self.assert_bad(signing=signer)

    def test_unknown_scheme_signer_format_remains_rejected(self):
        signer = (
            f'V9 Signer: certificate SHA-256 digest: {self.debug_digest}\n'
        )
        self.assert_bad(signing=signer)

    def test_aosp_sdk_range_signer_label_is_supported(self):
        # Android build tooling may print scheme-specific min/max SDK signers.
        scoped = self.signing.replace(
            'Signer #1 certificate SHA-256 digest:',
            'Signer (minSdkVersion=24, maxSdkVersion=32) '
            'certificate SHA-256 digest:',
        )
        guard.check_metadata(
            self.badging, self.manifest, scoped, self.debug_digest,
        )

    def test_same_cert_for_multiple_android_sdk_ranges_is_supported(self):
        scoped = (
            'Signer (minSdkVersion=24, maxSdkVersion=32) '
            f'certificate SHA-256 digest: {self.debug_digest}\n'
            'Signer (minSdkVersion=33, maxSdkVersion=35) '
            f'certificate SHA-256 digest: {self.debug_digest}\n'
        )
        guard.check_metadata(
            self.badging, self.manifest, scoped, self.debug_digest,
        )

    def test_mixed_signer_labels_one_cert_is_supported(self):
        scoped = self.signing + (
            'Signer (minSdkVersion=24, maxSdkVersion=32) '
            f'certificate SHA-256 digest: {self.debug_digest}\n'
        )
        guard.check_metadata(
            self.badging, self.manifest, scoped, self.debug_digest,
        )

    def test_different_certificate_in_second_sdk_range_is_rejected(self):
        scoped = self.signing + (
            'Signer (minSdkVersion=24, maxSdkVersion=32) '
            f'certificate SHA-256 digest: {"b" * 64}\n'
        )
        self.assert_bad(signing=scoped)

    def test_unrecognized_signer_label_must_fail_closed(self):
        scoped = self.signing.replace('Signer #1', 'Unrecognized Signer')
        with self.assertRaisesRegex(
            guard.ApkGuardError, 'Unrecognized apksigner certificate',
        ):
            guard.check_metadata(
                self.badging, self.manifest, scoped, self.debug_digest,
            )

    def test_no_matching_signer_line_reports_diagnostic_markers(self):
        with self.assertRaisesRegex(
            guard.ApkGuardError, 'No certificate SHA-256 digest found',
        ):
            guard.check_metadata(
                self.badging, self.manifest,
                'Signer unknown certificate SHA-1 digest: deadbeef',
                self.debug_digest,
            )

    def test_explicit_multiple_signer_count_is_rejected(self):
        self.assert_bad(signing=self.signing + 'Number of signers: 2\n')

    def test_uppercase_colon_separated_cert_fingerprint_is_supported(self):
        pairs = ':'.join(
            self.debug_digest[i:i + 2] for i in range(0, 64, 2)
        ).upper()
        value = self.signing.replace(self.debug_digest, pairs)
        guard.check_metadata(
            self.badging, self.manifest, value, self.debug_digest,
        )

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
