#!/usr/bin/env python3
"""Read-only evidence inspector for a prior QEMU Android Auto session probe.

Never modifies emulator data, launches APKs, downloads anything or runs Flutter.
The MediaSession dump is advisory: Android may expose bitmaps instead of the
original artwork URI, and only a real external MediaController can prove what
a client actually receives.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import sys
from pathlib import Path

import radio_catalog_flutter_provider_emulator_probe as base

PACKAGE_DECLARATION = re.compile(
    r"(?<![A-Za-z])(?:package|ownerPackage)="
    + re.escape(base.PACKAGE)
    + r"(?![A-Za-z0-9_.])"
)
ARTWORK_HINTS = (
    "android.media.metadata.DISPLAY_ICON_URI",
    "android.media.metadata.DISPLAY_ICON",
    "android.media.metadata.ALBUM_ART",
    "android.media.metadata.ART",
    "DISPLAY_ICON_URI",
    "albumArt",
)
TEST_TITLE = "Diagnostic SHA"


def inspect_dump(dump: str, uri: str) -> dict[str, bool]:
    """Report evidence without assuming dumpsys serializes all metadata.

    No field constitutes independent confirmation of rendered art.
    """
    return {
        "native_session_package": bool(PACKAGE_DECLARATION.search(dump)),
        "exact_artwork_uri_visible": uri in dump,
        "metadata_artwork_hint": any(h in dump for h in ARTWORK_HINTS),
        "synthetic_station_title_visible": TEST_TITLE in dump,
    }


def check_existing_object(
    adb_path: str, serial: str, expected: bytes,
) -> str:
    """QEMU-only *read*: inspect the preserved SHA after a failed probe.

    Return absent / verified_exact_bytes / mismatch. Never remove the object.
    """
    base.emulator_guard(adb_path, serial)
    pwd = base.adb(adb_path, serial, "shell", "run-as", base.PACKAGE, "pwd")
    root = pwd.stdout.decode("utf-8", "replace").strip()
    if not root.startswith("/data/") or base.PACKAGE not in root:
        raise base.ProbeError("Cannot safely inspect app storage with run-as")
    digest = hashlib.sha256(expected).hexdigest()
    rel = f"files/{base.CENTRAL_DIR}/{digest}.img"
    exists = base.adb(
        adb_path, serial, "shell", "run-as", base.PACKAGE,
        "test", "-e", rel, check=False,
    )
    if exists.returncode == 1:
        return "absent"
    if exists.returncode != 0:
        raise base.ProbeError("Cannot determine whether diagnostic SHA exists")
    uri = f"content://{base.AUTHORITY}/central/{digest}.img"
    payload = base.adb(
        adb_path, serial, "exec-out", "content", "read", "--uri", uri,
        check=False,
    )
    if payload.returncode != 0:
        return "not_readable"
    return ("verified_exact_bytes" if payload.stdout == expected
            else "mismatch_do_not_modify")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dump", default="reconciliation-auto-session-dumpsys.txt")
    ap.add_argument("--serial", default=None, help="Optional QEMU-only read check")
    args = ap.parse_args()
    root = Path(__file__).resolve().parent.parent
    png_file = root / "assets" / "genres" / "punk.png"
    if not png_file.is_file():
        raise base.ProbeError("Original packaged Punk PNG missing")
    png = png_file.read_bytes()
    if not png.startswith(b"\x89PNG\r\n\x1a\n"):
        raise base.ProbeError("Invalid packaged PNG")
    digest = hashlib.sha256(png).hexdigest()
    uri = f"content://{base.AUTHORITY}/central/{digest}.img"
    dump_path = Path(args.dump)
    if not dump_path.is_absolute():
        dump_path = root / dump_path
    if dump_path.exists():
        findings = inspect_dump(dump_path.read_text(encoding="utf-8"), uri)
        print("== Previous native MediaSession snapshot (read-only) ==")
        for key, present in findings.items():
            print(f"{key}: {'YES' if present else 'NO'}")
        if not findings["exact_artwork_uri_visible"]:
            print("ARTWORK NATIVE PROPAGATION: UNCONFIRMED (dump is not conclusive)")
        else:
            print("ARTWORK URI: visible in dump; rendering remains UNCONFIRMED")
    else:
        print(f"Dumpsys snapshot absent: {dump_path}")
    if args.serial:
        appdata = __import__("os").environ.get("LOCALAPPDATA")
        sdk = (
            Path(appdata) / "Android" / "Sdk" / "platform-tools" / "adb.exe"
            if appdata else None
        )
        adb_path = str(sdk) if sdk and sdk.is_file() else shutil.which("adb")
        if not adb_path:
            raise base.ProbeError("adb is not available")
        status = check_existing_object(adb_path, args.serial, png)
        print(f"Previous diagnostic SHA status: {status}")
        print("No files were deleted or installed.")
    print("External Media Controller Test is required for client metadata/art.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, UnicodeError, base.ProbeError) as error:
        print(f"INSPECTION INCOMPLETE: {error}", file=sys.stderr)
        sys.exit(1)
