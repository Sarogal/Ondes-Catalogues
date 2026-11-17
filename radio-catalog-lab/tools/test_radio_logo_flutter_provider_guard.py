"""Offline-only guard tests for QEMU Flutter -> ContentProvider probe."""
from __future__ import annotations

import hashlib
import subprocess
import unittest
from unittest.mock import patch

import radio_catalog_flutter_provider_emulator_probe as probe


def command(stdout: bytes, rc: int = 0) -> subprocess.CompletedProcess[bytes]:
    return subprocess.CompletedProcess([], rc, stdout, b"")


class FlutterProviderProbeGuardTests(unittest.TestCase):
    def test_flutter_build_streams_output_instead_of_capturing(self):
        with patch.object(probe.subprocess, "run", return_value=command(b"", 0)) as runner:
            probe.build_flutter_debug("flutter", "build", "apk", "--debug")
            args, kwargs = runner.call_args
            self.assertEqual(args[0], ["flutter", "build", "apk", "--debug"])
            self.assertEqual(kwargs["timeout"], probe.BUILD_TIMEOUT_SECONDS)
            self.assertNotIn("stdout", kwargs)
            self.assertNotIn("stderr", kwargs)

    def test_failed_flutter_build_is_reported(self):
        with patch.object(probe.subprocess, "run", return_value=command(b"", 1)):
            with self.assertRaisesRegex(probe.ProbeError, "exit code 1"):
                probe.build_flutter_debug("flutter", "build", "apk")

    def test_stalled_flutter_build_times_out_without_installing(self):
        timeout = subprocess.TimeoutExpired(cmd=["flutter", "build"], timeout=900)
        with patch.object(probe.subprocess, "run", side_effect=timeout):
            with self.assertRaisesRegex(probe.ProbeError, "timed out"):
                probe.build_flutter_debug("flutter", "build", "apk")

    def test_real_phone_is_refused_even_when_online(self):
        with self.assertRaises(probe.ProbeError):
            probe.emulator_guard("adb", "R58N123ABCD")
        with patch.object(probe, "cmd_text", return_value=(
            "List of devices attached\nemulator-5554 device\nR58N123ABCD device\n"
        )), patch.object(probe, "adb", side_effect=[
            command(b"0\n"), command(b"1\n"),
        ]):
            with self.assertRaises(probe.ProbeError):
                probe.emulator_guard("adb", "emulator-5554")

    def test_qemu_and_boot_are_required(self):
        with patch.object(probe, "cmd_text", return_value=(
            "List of devices attached\nemulator-5554 device\n"
        )), patch.object(probe, "adb", side_effect=[
            command(b"1\n"), command(b"0\n"),
        ]):
            with self.assertRaises(probe.ProbeError):
                probe.emulator_guard("adb", "emulator-5554")

    def test_existing_cache_object_refuses_overwrite(self):
        with patch.object(probe, "adb", side_effect=[
            command(b"/data/user/0/fr.grossesondes.grosses_ondes\n"),
            command(b"", 0),
        ]) as remote:
            with self.assertRaises(probe.ProbeError):
                probe.probe_data_precheck("adb", "emulator-5554", "a" * 64)
            self.assertEqual(remote.call_count, 2)

    def test_clean_sandbox_checks_both_test_paths_without_writing(self):
        with patch.object(probe, "adb", side_effect=[
            command(b"/data/user/0/fr.grossesondes.grosses_ondes\n"),
            command(b"", 1), command(b"", 1),
        ]) as remote:
            probe.probe_data_precheck("adb", "emulator-5554", "b" * 64)
            self.assertEqual(remote.call_count, 3)
            arguments = [call.args for call in remote.call_args_list]
            self.assertTrue(all("rm" not in parts for parts in arguments))

    def test_mediaitem_attestation_required_before_provider_reads(self):
        expected = b"synthetic-debug-image-bytes"
        digest = hashlib.sha256(expected).hexdigest()
        uri = f"content://{probe.AUTHORITY}/central/{digest}.img"
        log = f"GO_CENTRAL_PROBE PASS sha={digest} requests=1 stations=2 uri={uri}"
        with patch.object(probe, "adb") as remote:
            with self.assertRaises(probe.ProbeError):
                probe.verify_content("adb", "emulator-5554", log, expected)
            remote.assert_not_called()

    def test_provider_bytes_must_match_exact_test_png(self):
        expected = b"\x89PNG\r\n\x1a\n" + b"synthetic-debug-probe"
        digest = hashlib.sha256(expected).hexdigest()
        uri = f"content://{probe.AUTHORITY}/central/{digest}.img"
        log = (
            f"GO_CENTRAL_MEDIA_ITEM PASS sha={digest} "
            f"station=diagnostic-legacy-1 uri={uri}\n"
            f"GO_CENTRAL_PROBE PASS sha={digest} requests=1 stations=2 uri={uri}"
        )
        with patch.object(probe, "adb", return_value=command(expected)):
            self.assertEqual(
                probe.verify_content("adb", "emulator-5554", log, expected),
                digest,
            )
        with patch.object(probe, "adb", return_value=command(b"wrong")):
            with self.assertRaises(probe.ProbeError):
                probe.verify_content("adb", "emulator-5554", log, expected)


if __name__ == "__main__":
    unittest.main()
