"""Synthetic unit tests for read-only QEMU media-session dump inspector."""
from __future__ import annotations

import hashlib
import subprocess
import unittest
from unittest.mock import patch

import radio_catalog_android_auto_dump_inspector as inspect
import radio_catalog_flutter_provider_emulator_probe as base


def command(data: bytes = b"", rc: int = 0):
    return subprocess.CompletedProcess([], rc, data, b"")


class AndroidAutoDumpInspectorTests(unittest.TestCase):
    def setUp(self):
        self.png = b"\x89PNG\r\n\x1a\n" + b"synthetic-test-image"
        self.digest = hashlib.sha256(self.png).hexdigest()
        self.uri = f"content://{base.AUTHORITY}/central/{self.digest}.img"

    def test_dump_can_show_package_without_serializing_artwork_uri(self):
        dump = f"MediaSessionRecord{{package={base.PACKAGE}}}\nmetadata: MediaMetadata"
        result = inspect.inspect_dump(dump, self.uri)
        self.assertTrue(result["native_session_package"])
        self.assertFalse(result["exact_artwork_uri_visible"])

    def test_uri_alone_cannot_count_as_native_session_registration(self):
        result = inspect.inspect_dump(self.uri, self.uri)
        self.assertTrue(result["exact_artwork_uri_visible"])
        self.assertFalse(result["native_session_package"])

    def test_distinct_native_evidence_with_uri(self):
        dump = (
            f"MediaSessionRecord{{ownerPackage={base.PACKAGE}}} "
            f"DISPLAY_ICON_URI={self.uri} Diagnostic SHA"
        )
        self.assertEqual(inspect.inspect_dump(dump, self.uri), {
            "native_session_package": True,
            "exact_artwork_uri_visible": True,
            "metadata_artwork_hint": True,
            "synthetic_station_title_visible": True,
        })

    def test_read_only_inspector_finds_no_previous_probe(self):
        with patch.object(base, "emulator_guard"), patch.object(
            base, "adb", side_effect=[
                command(f"/data/user/0/{base.PACKAGE}\n".encode()),
                command(rc=1),
            ],
        ) as adb:
            self.assertEqual(
                inspect.check_existing_object("adb", "emulator-5554", self.png),
                "absent",
            )
            self.assertTrue(all("rm" not in str(c) for c in adb.call_args_list))

    def test_exact_existing_sha_is_identified_not_deleted(self):
        with patch.object(base, "emulator_guard"), patch.object(
            base, "adb", side_effect=[
                command(f"/data/user/0/{base.PACKAGE}\n".encode()),
                command(rc=0),
                command(self.png),
            ],
        ) as adb:
            self.assertEqual(
                inspect.check_existing_object("adb", "emulator-5554", self.png),
                "verified_exact_bytes",
            )
            self.assertTrue(all("rm" not in str(c) for c in adb.call_args_list))

    def test_wrong_sha_is_not_trusted_or_cleaned(self):
        with patch.object(base, "emulator_guard"), patch.object(
            base, "adb", side_effect=[
                command(f"/data/user/0/{base.PACKAGE}\n".encode()),
                command(rc=0),
                command(b"bad PNG"),
            ],
        ) as adb:
            self.assertEqual(
                inspect.check_existing_object("adb", "emulator-5554", self.png),
                "mismatch_do_not_modify",
            )
            self.assertTrue(all("rm" not in str(c) for c in adb.call_args_list))

    def test_unknown_existence_result_fails_closed(self):
        with patch.object(base, "emulator_guard"), patch.object(
            base, "adb", side_effect=[
                command(f"/data/user/0/{base.PACKAGE}\n".encode()),
                command(rc=2),
            ],
        ):
            with self.assertRaises(base.ProbeError):
                inspect.check_existing_object("adb", "emulator-5554", self.png)


if __name__ == "__main__":
    unittest.main()
