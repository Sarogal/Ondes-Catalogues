#!/usr/bin/env python3
"""QEMU-only real Flutter PNG -> immutable SHA -> Android ContentProvider probe.

This opt-in script builds a DEBUG diagnostic entrypoint, installs it ONLY on
one verified QEMU emulator, reads the exact image bytes through Kotlin
content://, removes script-created artifacts only after full verification,
then restores the ordinary DEBUG APK and emulator app. No production app,
real device, favorites, stream catalog, remote host or release key is used.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

PACKAGE = "fr.grossesondes.grosses_ondes"
AUTHORITY = f"{PACKAGE}.stationlogos"
BRANCH = "integration/radio-catalog-logo-reconciliation-20261116"
CENTRAL_DIR = "grosses_ondes_central_logos_v1"
SNAPSHOTS_DIR = "grosses_ondes_debug_probe_snapshots_v1"
TARGET = "lib/diagnostics/central_logo_emulator_probe.dart"
LOG_FILENAME = "reconciliation-flutter-provider-probe.log"
SERIAL_PATTERN = re.compile(r"emulator-[0-9]+\Z")
PASS_PATTERN = re.compile(
    r"GO_CENTRAL_PROBE PASS sha=([a-f0-9]{64}) requests=1 stations=2 "
    r"uri=(content://[^\s]+)"
)


class ProbeError(Exception):
    pass


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(
        list(args), stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).decode("utf-8", "replace")
        raise ProbeError(f"Command failed ({args[0]}): {detail[:700]}")
    return result


def cmd_text(*args: str) -> str:
    return run(*args).stdout.decode("utf-8", "replace").strip()


def adb(adb_path: str, serial: str, *args: str, check: bool = True):
    return run(adb_path, "-s", serial, *args, check=check)


def emulator_guard(adb_path: str, serial: str) -> None:
    if not SERIAL_PATTERN.fullmatch(serial):
        raise ProbeError("Only an explicit emulator-NNNN serial is allowed")
    raw = cmd_text(adb_path, "devices")
    registered = {
        fields[0]
        for line in raw.splitlines()
        if len(fields := line.split()) >= 2 and fields[1] == "device"
    }
    if serial not in registered:
        raise ProbeError("Selected emulator is not connected/ready")
    qemu = adb(adb_path, serial, "shell", "getprop", "ro.kernel.qemu")
    boot = adb(adb_path, serial, "shell", "getprop", "sys.boot_completed")
    if qemu.stdout.strip() != b"1" or boot.stdout.strip() != b"1":
        raise ProbeError("QEMU guard failed; refusing APK installation")
    print(f"Verified QEMU emulator: {serial}")


def probe_data_precheck(adb_path: str, serial: str, digest: str) -> None:
    pwd = adb(adb_path, serial, "shell", "run-as", PACKAGE, "pwd")
    root = pwd.stdout.decode("utf-8", "replace").strip()
    if not root.startswith("/data/") or PACKAGE not in root:
        raise ProbeError("Installed app is not debuggable (run-as refused)")
    for item in (
        f"files/{CENTRAL_DIR}/{digest}.img",
        f"files/{SNAPSHOTS_DIR}",
    ):
        exists = adb(
            adb_path, serial, "shell", "run-as", PACKAGE,
            "test", "-e", item, check=False,
        )
        if exists.returncode == 0:
            raise ProbeError(f"Refusing overwrite or deletion of existing {item}")
        if exists.returncode != 1:
            raise ProbeError(f"Cannot safely determine whether {item} exists")
    print("DEBUG sandbox is clean for this probe; no user cache overwritten")


def capture_probe_log(adb_path: str, serial: str, destination: Path) -> str:
    # Logcat is reset for this emulator only. Raw logs stay on the local PC.
    adb(adb_path, serial, "logcat", "-c")
    adb(adb_path, serial, "shell", "am", "force-stop", PACKAGE)
    adb(
        adb_path, serial, "shell", "monkey", "-p", PACKAGE,
        "-c", "android.intent.category.LAUNCHER", "1",
    )
    deadline = time.monotonic() + 120
    last = ""
    while time.monotonic() < deadline:
        time.sleep(2)
        result = adb(adb_path, serial, "logcat", "-d", "-s", "flutter:I", "*:S")
        last = result.stdout.decode("utf-8", "replace")
        if "GO_CENTRAL_PROBE PASS" in last or "GO_CENTRAL_PROBE FAIL" in last:
            break
    destination.write_text(last, encoding="utf-8")
    if "GO_CENTRAL_PROBE FAIL" in last:
        raise ProbeError(f"Flutter diagnostic target failed; see {destination}")
    if "GO_CENTRAL_PROBE PASS" not in last:
        raise ProbeError(f"Flutter diagnostic target did not finish; see {destination}")
    return last


def verify_content(adb_path: str, serial: str, log: str, expected: bytes) -> str:
    match = PASS_PATTERN.search(log)
    digest = hashlib.sha256(expected).hexdigest()
    expected_uri = f"content://{AUTHORITY}/central/{digest}.img"
    if not match or match.group(1) != digest or match.group(2) != expected_uri:
        raise ProbeError("Flutter debug success does not match expected SHA or URI")
    result = adb(
        adb_path, serial, "exec-out", "content", "read",
        "--uri", expected_uri,
    )
    if result.stdout != expected:
        raise ProbeError("Kotlin ContentProvider bytes differ from bundled PNG")
    print(f"PASS: Flutter signed catalog -> SHA cache -> native provider SHA={digest[:16]}")
    print("PASS: one injected fetch for two radios; offline cache hit on repeat")
    return digest


def cleanup_probe_data(adb_path: str, serial: str, digest: str) -> None:
    # Paths were checked ABSENT before launch; delete only exactly those
    # probe-created artifacts, not parent directories or any legacy cache.
    adb(
        adb_path, serial, "shell", "run-as", PACKAGE,
        "rm", "-f", f"files/{CENTRAL_DIR}/{digest}.img",
    )
    adb(
        adb_path, serial, "shell", "run-as", PACKAGE,
        "rm", "-r", f"files/{SNAPSHOTS_DIR}",
    )
    print("Removed only debug probe SHA and debug signed-snapshot directory")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--serial", default="emulator-5554",
        help="Verified QEMU serial, never a physical Android device",
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    os.chdir(root)

    if cmd_text("git", "branch", "--show-current") != BRANCH:
        raise ProbeError(f"Refusing non-isolated Git branch (need {BRANCH})")
    if cmd_text("git", "rev-parse", "HEAD") != cmd_text(
        "git", "rev-parse", f"origin/{BRANCH}",
    ):
        raise ProbeError("Fetch/pull this isolated branch before running the probe")

    local_appdata = os.environ.get("LOCALAPPDATA")
    sdk_adb = (
        Path(local_appdata) / "Android" / "Sdk" / "platform-tools" / "adb.exe"
        if local_appdata else None
    )
    adb_path = str(sdk_adb) if sdk_adb and sdk_adb.is_file() else shutil.which("adb")
    flutter = shutil.which("flutter")
    if not adb_path or not flutter:
        raise ProbeError("Flutter and Android SDK adb must be installed in PATH")

    source = root / "assets" / "genres" / "punk.png"
    if not source.is_file():
        raise ProbeError("Packaged Punk PNG is missing")
    expected = source.read_bytes()
    if not expected.startswith(b"\x89PNG\r\n\x1a\n") or not 0 < len(expected) <= 8 * 1024 * 1024:
        raise ProbeError("Invalid test PNG")
    digest = hashlib.sha256(expected).hexdigest()

    emulator_guard(adb_path, args.serial)
    apk = root / "build" / "app" / "outputs" / "flutter-apk" / "app-debug.apk"
    print("Building alternate diagnostic Flutter entrypoint (DEBUG only)")
    run(flutter, "build", "apk", "--debug", "--no-pub", "--target", TARGET)
    if not apk.is_file():
        raise ProbeError("No DEBUG diagnostic APK produced")

    installed = False
    verified = False
    try:
        adb(adb_path, args.serial, "install", "-r", str(apk))
        installed = True
        probe_data_precheck(adb_path, args.serial, digest)
        log = capture_probe_log(
            adb_path, args.serial, root / LOG_FILENAME,
        )
        verify_content(adb_path, args.serial, log, expected)
        verified = True
        cleanup_probe_data(adb_path, args.serial, digest)
    finally:
        if installed:
            print("Restoring normal DEBUG Flutter target and emulator app")
            try:
                run(
                    flutter, "build", "apk", "--debug", "--no-pub",
                    "--dart-define=GO_LOGO_AUDIT=true",
                )
                adb(adb_path, args.serial, "install", "-r", str(apk))
                print("Normal DEBUG APK and emulator installation restored")
            except ProbeError as error:
                print(f"RESTORE INCOMPLETE: {error}", file=sys.stderr)
                verified = False

    if not verified:
        raise ProbeError("Diagnostic did not complete; no public deployment was made")
    print("PREFLIGHT FLUTTER-TO-CONTENT-PROVIDER OK (QEMU only)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ProbeError) as error:
        print(f"NOT VALIDATED: {error}", file=sys.stderr)
        sys.exit(1)
