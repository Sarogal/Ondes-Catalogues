#!/usr/bin/env python3
"""QEMU-only DEBUG native media-session probe. Never installs on real hardware.

Installs an alternate entrypoint on a verified QEMU emulator, checks the
bundled SHA provider and Android media-session dump, then restores the normal
DEBUG APK. It cannot by itself prove that Android Auto draws the artwork:
that requires an actual compatible DHU / media controller client.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import sys
import time
from pathlib import Path

import radio_catalog_flutter_provider_emulator_probe as base

TARGET = "lib/diagnostics/central_android_auto_session_emulator_probe.dart"
LOG_FILE = "reconciliation-auto-session-probe.log"
DUMP_FILE = "reconciliation-auto-session-dumpsys.txt"
READY = re.compile(
    r"GO_AUTO_SESSION_READY sha=([a-f0-9]{64}) "
    r"uri=(content://[^\s]+) fallback=(content://[^\s]+) "
    r"browse=2 playing=false"
)


def validate_dart_log(log: str, expected_digest: str) -> tuple[str, str]:
    match = READY.search(log)
    expected_uri = (
        f"content://{base.AUTHORITY}/central/{expected_digest}.img"
    )
    fallback = f"content://{base.AUTHORITY}/genre/go_genre_punk_v1"
    if not match or (match.group(1), match.group(2), match.group(3)) != (
        expected_digest, expected_uri, fallback,
    ):
        raise base.ProbeError("AudioService.init or signed SHA metadata not validated")
    return expected_uri, fallback


def validate_native_dump(dump: str, expected_uri: str) -> None:
    # Dumpsys is a secondary Android-framework observation; it is not a DHU
    # display check. We deliberately require the URI, not only the Dart log.
    if base.PACKAGE not in dump:
        raise base.ProbeError("Native MediaSession package not visible in dumpsys")
    if expected_uri not in dump:
        raise base.ProbeError(
            "Native MediaSession art URI not visible in dumpsys: "
            "native propagation UNCONFIRMED, inspect the saved dump"
        )


def capture_debug_session(adb_path: str, serial: str, log_file: Path) -> str:
    base.adb(adb_path, serial, "logcat", "-c")
    base.adb(adb_path, serial, "shell", "am", "force-stop", base.PACKAGE)
    base.adb(
        adb_path, serial, "shell", "monkey",
        "-p", base.PACKAGE, "-c",
        "android.intent.category.LAUNCHER", "1",
    )
    deadline = time.monotonic() + 120
    latest = ""
    while time.monotonic() < deadline:
        time.sleep(2)
        result = base.adb(
            adb_path, serial, "logcat", "-d", "-s", "flutter:I", "*:S",
        )
        latest = result.stdout.decode("utf-8", "replace")
        if "GO_AUTO_SESSION_READY" in latest or "GO_AUTO_SESSION_FAIL" in latest:
            break
    log_file.write_text(latest, encoding="utf-8")
    if "GO_AUTO_SESSION_FAIL" in latest:
        raise base.ProbeError(f"DEBUG AudioService failed; see {log_file}")
    if "GO_AUTO_SESSION_READY" not in latest:
        raise base.ProbeError(f"DEBUG AudioService did not report ready; see {log_file}")
    return latest


def verify_provider(adb_path: str, serial: str, uri: str, png: bytes) -> None:
    result = base.adb(
        adb_path, serial, "exec-out", "content", "read", "--uri", uri,
    )
    if result.stdout != png:
        raise base.ProbeError("Android ContentProvider did not serve the expected PNG")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", default="emulator-5554")
    parser.add_argument(
        "--hold-for-dhu", action="store_true",
        help="Keep the diagnostic APK active until ENTER, for optional DHU inspection",
    )
    options = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    os.chdir(root)
    if base.cmd_text("git", "branch", "--show-current") != base.BRANCH:
        raise base.ProbeError("Refusing to run outside the isolated branch")
    if base.cmd_text("git", "rev-parse", "HEAD") != base.cmd_text(
        "git", "rev-parse", f"origin/{base.BRANCH}",
    ):
        raise base.ProbeError("Fetch/pull isolated branch before QEMU probe")
    appdata = os.environ.get("LOCALAPPDATA")
    sdk_adb = (
        Path(appdata) / "Android" / "Sdk" / "platform-tools" / "adb.exe"
        if appdata else None
    )
    adb_path = str(sdk_adb) if sdk_adb and sdk_adb.is_file() else shutil.which("adb")
    flutter = shutil.which("flutter")
    if not adb_path or not flutter:
        raise base.ProbeError("Flutter and Android SDK adb required")
    png_path = root / "assets" / "genres" / "punk.png"
    if not png_path.is_file():
        raise base.ProbeError("Packaged diagnostic PNG missing")
    png = png_path.read_bytes()
    if not png.startswith(b"\x89PNG\r\n\x1a\n") or not 0 < len(png) <= 8 * 1024 * 1024:
        raise base.ProbeError("Invalid diagnostic PNG")
    digest = hashlib.sha256(png).hexdigest()
    base.emulator_guard(adb_path, options.serial)

    print("Building isolated AudioService diagnostic DEBUG APK", flush=True)
    base.build_flutter_debug(
        flutter, "build", "apk", "--debug", "--no-pub", "--target", TARGET,
    )
    apk = root / "build" / "app" / "outputs" / "flutter-apk" / "app-debug.apk"
    if not apk.is_file():
        raise base.ProbeError("DEBUG alternate APK not produced")

    installed = False
    success = False
    try:
        base.adb(adb_path, options.serial, "install", "-r", str(apk))
        installed = True
        base.probe_data_precheck(adb_path, options.serial, digest)
        log = capture_debug_session(
            adb_path, options.serial, root / LOG_FILE,
        )
        uri, _ = validate_dart_log(log, digest)
        verify_provider(adb_path, options.serial, uri, png)
        print("PASS: signed SHA image opened by native ContentProvider")

        dump_result = base.adb(
            adb_path, options.serial, "shell", "dumpsys", "media_session",
        )
        dump = dump_result.stdout.decode("utf-8", "replace")
        (root / DUMP_FILE).write_text(dump, encoding="utf-8")
        validate_native_dump(dump, uri)
        print("PASS: native MediaSession dump contains exact verified SHA URI")
        if options.hold_for_dhu:
            print("Diagnostic session active for DHU/manual inspection.")
            print("Press ENTER to restore the normal DEBUG APK.", flush=True)
            input()
        success = True
        # The preflight refused existing target/snapshot directory. Cleanup
        # only the one synthetic SHA file, never a user cache directory.
        base.adb(
            adb_path, options.serial, "shell", "run-as", base.PACKAGE,
            "rm", "-f", f"files/{base.CENTRAL_DIR}/{digest}.img",
        )
        print("Removed only the probe-created SHA object")
    finally:
        if installed:
            print("Restoring ordinary DEBUG Flutter APK", flush=True)
            try:
                base.build_flutter_debug(
                    flutter, "build", "apk", "--debug", "--no-pub",
                    "--dart-define=GO_LOGO_AUDIT=true",
                )
                base.adb(adb_path, options.serial, "install", "-r", str(apk))
                print("Normal DEBUG APK restored")
            except base.ProbeError as error:
                print(f"RESTORE INCOMPLETE: {error}", file=sys.stderr)
                success = False
    if not success:
        raise base.ProbeError(
            "Native session proof incomplete; no deployment. "
            "Diagnostic SHA preserved for investigation if installed."
        )
    print("PREFLIGHT ANDROID-AUTO-NATIVE-SESSION OK (QEMU only, no UI proof)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, base.ProbeError) as error:
        print(f"NOT VALIDATED: {error}", file=sys.stderr)
        sys.exit(1)
