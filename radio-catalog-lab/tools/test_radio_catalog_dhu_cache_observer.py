"""Offline, side-effect-free tests for the physical Android Auto SHA cache observer."""
from __future__ import annotations

import hashlib
import unittest
from unittest.mock import Mock

import radio_catalog_dhu_cache_observer as observer

SERIAL = "adb-TANKTEST12345-ABC._adb-tls-connect._tcp"
PNG = b"\x89PNG\r\n\x1a\n" + b"test-only-pixels" * 8
SHA = hashlib.sha256(PNG).hexdigest()


class CacheObserverTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.stat = "4321|136|2026-11-19 05:22:01.123456789 +0100"
        self.name = f"{SHA}.img"

    def reader(self, cmd: list[str]) -> bytes:
        self.calls.append(cmd)
        mapping = {
            ("get-state",): b"device\n",
            ("shell", "getprop", "ro.product.model"): b"TANK 3\n",
            ("shell", "getprop", "ro.kernel.qemu"): b"0\n",
            ("shell", "pm", "path", observer.PRODUCTION): b"package:/data/app/public/base.apk\n",
            ("shell", "pm", "path", observer.DIAGNOSTIC): b"package:/data/app/diag/base.apk\n",
            ("exec-out", "run-as", observer.DIAGNOSTIC, "ls", "-1",
             observer.CACHE_DIR): (self.name + "\n").encode(),
            ("exec-out", "run-as", observer.DIAGNOSTIC, "cat",
             f"{observer.CACHE_DIR}/{self.name}"): PNG,
            ("exec-out", "run-as", observer.DIAGNOSTIC, "stat", "-c",
             "%i|%s|%y", f"{observer.CACHE_DIR}/{self.name}"):
                self.stat.encode(),
        }
        key = tuple(cmd)
        if key not in mapping:
            raise AssertionError(f"Unexpected adb action {cmd!r}")
        return mapping[key]

    def test_expected_real_phone_object_is_verified_read_only(self):
        actual = observer.observe(SERIAL, self.reader)
        self.assertEqual(actual["sha256"], SHA)
        self.assertEqual(actual["byte_size"], len(PNG))
        self.assertEqual(actual["inode"], "4321")
        self.assertEqual(len(self.calls), 8)
        for cmd in self.calls:
            self.assertNotIn("install", cmd)
            self.assertNotIn("force-stop", cmd)
            self.assertNotIn("rm", cmd)
            self.assertNotIn("clear", cmd)
            self.assertNotIn("reboot", cmd)
            if "run-as" in cmd:
                self.assertEqual(cmd[cmd.index("run-as") + 1],
                                 observer.DIAGNOSTIC)

    def test_same_cache_after_restart_is_a_pass(self):
        earlier = observer.observe(SERIAL, self.reader)
        self.calls.clear()
        later = observer.observe(SERIAL, self.reader)
        observer.compare_baseline(earlier, later)

    def test_new_wifi_port_does_not_invalidate_same_phone_cache(self):
        """ADB IP:port is an ephemeral transport, never a device identity."""
        earlier = observer.observe(SERIAL, self.reader)
        later = observer.observe("192.168.1.30:39895", self.reader)
        self.assertNotEqual(earlier["serial_tag"], later["serial_tag"])
        observer.compare_baseline(earlier, later)

    def test_new_wifi_port_still_rejects_changed_disk_object(self):
        earlier = observer.observe(SERIAL, self.reader)
        later = observer.observe("192.168.1.30:39895", self.reader)
        later["modified"] = "2026-11-19 06:00:00 +0100"
        with self.assertRaisesRegex(
            observer.CacheObservationError, "modified changed"
        ):
            observer.compare_baseline(earlier, later)

    def test_rewritten_file_same_bytes_is_not_a_persistence_proof(self):
        earlier = observer.observe(SERIAL, self.reader)
        later = dict(earlier)
        later["modified"] = "2026-11-19 05:23:04 +0100"
        with self.assertRaisesRegex(
            observer.CacheObservationError, "modified changed"
        ):
            observer.compare_baseline(earlier, later)

    def test_replaced_inode_is_not_a_persistence_proof(self):
        earlier = observer.observe(SERIAL, self.reader)
        later = dict(earlier, inode="4322")
        with self.assertRaisesRegex(observer.CacheObservationError,
                                    "inode changed"):
            observer.compare_baseline(earlier, later)

    def test_serial_identifiers_are_hashed_not_saved_raw(self):
        actual = observer.observe(SERIAL, self.reader)
        self.assertNotIn(SERIAL, str(actual))
        self.assertEqual(len(actual["serial_tag"]), 16)

    def test_emulator_is_rejected_before_any_query(self):
        with self.assertRaises(observer.CacheObservationError):
            observer.observe("emulator-5554", self.reader)
        self.assertEqual(self.calls, [])

    def test_no_image_is_refused_without_writes(self):
        self.name = "status.retry.json"
        with self.assertRaisesRegex(
            observer.CacheObservationError, "Expected one test SHA"
        ):
            observer.observe(SERIAL, self.reader)

    def test_different_png_sha_is_not_accepted(self):
        self.name = "a" * 64 + ".img"
        with self.assertRaisesRegex(
            observer.CacheObservationError, "SHA-256 does not match"
        ):
            observer.observe(SERIAL, self.reader)

    def test_invalid_phone_model_refused_before_access_to_cache(self):
        def read(cmd):
            if cmd == ["shell", "getprop", "ro.product.model"]:
                return b"Pixel 7"
            return self.reader(cmd)
        with self.assertRaisesRegex(observer.CacheObservationError,
                                    "confirmed TANK 3"):
            observer.observe(SERIAL, read)
        self.assertFalse(any("run-as" in cmd for cmd in self.calls))

    def test_cache_size_change_during_read_is_rejected(self):
        self.stat = "4321|999|2026-11-19 05:22:01 +0100"
        with self.assertRaisesRegex(observer.CacheObservationError,
                                    "size changed"):
            observer.observe(SERIAL, self.reader)

    def test_stat_metadata_is_required(self):
        self.stat = "unknown"
        with self.assertRaisesRegex(observer.CacheObservationError,
                                    "stat format unsupported"):
            observer.observe(SERIAL, self.reader)

    def test_serial_ipv4_supported_but_shell_metacharacters_rejected(self):
        self.assertIsNotNone(observer.WIFI_SERIAL.fullmatch("192.168.1.30:44551"))
        for bad in ("adb-TANK;rm -rf /", "emulator-5572", "192.168.1.30:1234;id"):
            self.assertIsNone(observer.WIFI_SERIAL.fullmatch(bad))

    def test_absent_or_changed_public_package_blocks_observation(self):
        def read(cmd):
            if cmd == ["shell", "pm", "path", observer.PRODUCTION]:
                return b""
            return self.reader(cmd)
        with self.assertRaisesRegex(
            observer.CacheObservationError, "public app is not installed"
        ):
            observer.observe(SERIAL, read)


if __name__ == "__main__":
    unittest.main()
