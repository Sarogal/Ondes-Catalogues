"""Offline tests for the standalone Android Auto DHU APK identity guard."""
from __future__ import annotations

import unittest

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
        self.signing = (
            'Signer #1 certificate DN: C=US, O=Android, CN=Android Debug\n'
        )

    def assert_bad(self, *, badging=None, manifest=None, signing=None):
        with self.assertRaises(guard.ApkGuardError):
            guard.check_metadata(
                self.badging if badging is None else badging,
                self.manifest if manifest is None else manifest,
                self.signing if signing is None else signing,
            )

    def test_exact_diagnostic_passes(self):
        guard.check_metadata(self.badging, self.manifest, self.signing)

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

    def test_android_debug_certificate_required(self):
        self.assert_bad(signing=self.signing.replace(
            "CN=Android Debug", "CN=Grosses Ondes Production"))

    def test_duplicate_provider_authority_rejected(self):
        self.assert_bad(manifest=self.manifest + (
            'A: android:authorities="'
            'fr.grossesondes.grosses_ondes.dhudiag.stationlogos"\n'
        ))


if __name__ == "__main__":
    unittest.main()
