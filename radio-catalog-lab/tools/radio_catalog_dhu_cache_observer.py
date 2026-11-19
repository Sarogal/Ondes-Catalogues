#!/usr/bin/env python3
"""Read-only verification of the isolated DHU diagnostic SHA cache on a real phone.

No adb install, shell mutation, run-as against the public app, network download,
device cleanup, or private PNG export to the PC. Baseline is written only on PC.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

DIAGNOSTIC = "fr.grossesondes.grosses_ondes.dhudiag"
PRODUCTION = "fr.grossesondes.grosses_ondes"
CACHE_DIR = "files/grosses_ondes_central_logos_v1"
SHA_FILE = re.compile(r"^[a-f0-9]{64}\.img$")
WIFI_SERIAL = re.compile(
    r"^(?:adb-[A-Za-z0-9_-]+\._adb-tls-connect\._tcp|"
    r"(?:\d{1,3}\.){3}\d{1,3}:\d+)$"
)
PNG_HEADER = b"\x89PNG\r\n\x1a\n"


class CacheObservationError(ValueError):
    pass


def default_adb() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        raise CacheObservationError("LOCALAPPDATA missing: use Windows PowerShell")
    path = Path(local) / "Android" / "Sdk" / "platform-tools" / "adb.exe"
    if not path.is_file():
        raise CacheObservationError(f"ADB executable not found at {path}")
    return path


def adb_read(adb: Path, serial: str, args: list[str]) -> bytes:
    """Read stdout only; command vector prevents shell injection on Windows."""
    try:
        result = subprocess.run(
            [str(adb), "-s", serial, *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=20,
        )
    except subprocess.TimeoutExpired as exc:
        raise CacheObservationError("ADB read timed out") from exc
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", "replace").strip()[:250]
        raise CacheObservationError(
            f"Read-only ADB query failed: {message or 'unknown error'}"
        )
    return result.stdout


def observe(serial: str, read) -> dict:
    """Collect a bounded SHA/size/mtime proof from the diagnostic sandbox only."""
    if not WIFI_SERIAL.fullmatch(serial) or serial.startswith("emulator-"):
        raise CacheObservationError("Expected one wireless physical-phone serial")

    def text(args: list[str]) -> str:
        return read(args).decode("utf-8", "replace").strip()

    if text(["get-state"]) != "device":
        raise CacheObservationError("Phone is not authorized as an ADB device")
    if text(["shell", "getprop", "ro.product.model"]) != "TANK 3":
        raise CacheObservationError("ADB device is not the confirmed TANK 3")
    if text(["shell", "getprop", "ro.kernel.qemu"]) == "1":
        raise CacheObservationError("Emulator detected; refusing cache inspection")
    if not text(["shell", "pm", "path", PRODUCTION]).startswith("package:"):
        raise CacheObservationError("Expected public app is not installed")
    if not text(["shell", "pm", "path", DIAGNOSTIC]).startswith("package:"):
        raise CacheObservationError("Isolated diagnostic APK is not installed")

    # Android run-as is available only for a debuggable app. Never run-as the
    # public package and never read its preferences, radios or private files.
    entries = text([
        "exec-out", "run-as", DIAGNOSTIC, "ls", "-1", CACHE_DIR,
    ]).splitlines()
    images = [name for name in entries if SHA_FILE.fullmatch(name)]
    if len(images) != 1:
        raise CacheObservationError(
            f"Expected one test SHA object, found {len(images)}; "
            "do not modify the phone cache"
        )
    filename = images[0]
    target = f"{CACHE_DIR}/{filename}"
    raw = read(["exec-out", "run-as", DIAGNOSTIC, "cat", target])
    if len(raw) < len(PNG_HEADER) or len(raw) > 8 * 1024 * 1024:
        raise CacheObservationError("Unexpected diagnostic PNG size")
    if not raw.startswith(PNG_HEADER):
        raise CacheObservationError("Diagnostic image is not a PNG")
    digest = hashlib.sha256(raw).hexdigest()
    if filename != f"{digest}.img":
        raise CacheObservationError("Stored image SHA-256 does not match filename")
    stat = text([
        "exec-out", "run-as", DIAGNOSTIC,
        "stat", "-c", "%i|%s|%y", target,
    ])
    fields = stat.split("|", 2)
    if len(fields) != 3 or not fields[0].isdigit() or not fields[1].isdigit():
        raise CacheObservationError(
            "Device stat format unsupported; cannot prove unchanged disk object"
        )
    if int(fields[1]) != len(raw):
        raise CacheObservationError("File size changed during inspection")
    return {
        "schema": 1,
        "target": "TANK 3 / GO Diagnostic SHA",
        "serial_tag": hashlib.sha256(serial.encode()).hexdigest()[:16],
        "package": DIAGNOSTIC,
        "sha256": digest,
        "byte_size": len(raw),
        "inode": fields[0],
        "modified": fields[2],
    }


def compare_baseline(baseline: dict, current: dict) -> None:
    # A wireless ADB endpoint is NOT a device identity: the phone keeps the
    # same disk cache when its Wi-Fi debugging port changes. Older baselines
    # already contain serial_tag, so retain that field for compatibility but
    # never use it as a persistence gate. The physical-phone/model/package
    # checks in observe() and the object bytes/inode/mtime remain mandatory.
    for field in (
        "schema", "target", "package",
        "sha256", "byte_size", "inode", "modified",
    ):
        if baseline.get(field) != current.get(field):
            raise CacheObservationError(
                f"Cache persistence NOT PROVEN: {field} changed; "
                "no phone files have been modified by this tool"
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("baseline", "compare"))
    parser.add_argument("--serial", required=True)
    parser.add_argument(
        "--baseline", type=Path,
        default=Path("build/dhu-diagnostic-cache-baseline.json"),
    )
    parser.add_argument("--adb", type=Path, default=None)
    args = parser.parse_args()
    try:
        adb = args.adb or default_adb()
        if not adb.is_file():
            raise CacheObservationError("ADB executable is missing")
        if args.mode == "baseline" and args.baseline.exists():
            raise CacheObservationError(
                f"Baseline already exists at {args.baseline}; refusing overwrite"
            )
        if args.mode == "compare":
            if not args.baseline.is_file():
                raise CacheObservationError(
                    "No existing baseline. Run baseline first."
                )
            previous = json.loads(args.baseline.read_text("utf-8"))
            if not isinstance(previous, dict):
                raise CacheObservationError("Baseline JSON must be an object")

        current = observe(
            args.serial,
            lambda cmd: adb_read(adb, args.serial, cmd),
        )
        if args.mode == "baseline":
            args.baseline.parent.mkdir(parents=True, exist_ok=True)
            with args.baseline.open("x", encoding="utf-8") as handle:
                json.dump(current, handle, indent=2)
                handle.write("\n")
            print(f"BASELINE OK: {args.baseline}")
        else:
            compare_baseline(previous, current)
            if previous.get("serial_tag") != current.get("serial_tag"):
                print("INFO: wireless ADB port changed; port is not a device identity")
            print("PASS: verified same SHA bytes, size, inode and mtime after restart")
        print(f"SHA-256: {current['sha256']}")
        print(f"Bytes: {current['byte_size']}")
        print("READ-ONLY PHONE: no install, network, cache deletion or app restart")
        return 0
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError,
            CacheObservationError) as exc:
        parser.exit(1, f"REFUS OBSERVATION SHA: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
