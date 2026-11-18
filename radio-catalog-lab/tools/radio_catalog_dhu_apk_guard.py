#!/usr/bin/env python3
"""Offline APK identity and signing gate for the standalone Android Auto DHU DEBUG.

No adb calls, no network, no APK installation. All checks fail closed.
"""
from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

PRODUCTION = "fr.grossesondes.grosses_ondes"
DIAGNOSTIC = PRODUCTION + ".dhudiag"
AUTHORITY = DIAGNOSTIC + ".stationlogos"
LABEL = "GO Diagnostic SHA"


class ApkGuardError(ValueError):
    pass


def check_metadata(badging: str, manifest: str, signer: str) -> None:
    packages = re.findall(r"(?m)^package:\s+name='([^']+)'", badging)
    if packages != [DIAGNOSTIC]:
        raise ApkGuardError("APK is not the standalone diagnostic package; REFUSING")

    labels = re.findall(r"(?m)^application-label:'([^']*)'", badging)
    if labels != [LABEL]:
        raise ApkGuardError("Diagnostic app label is missing or ambiguous")

    authorities = re.findall(r'android:authorities(?:\([^)]*\))?="([^"]+)"', manifest)
    if authorities.count(AUTHORITY) != 1:
        raise ApkGuardError("The exact standalone artwork authority was not found once")
    if PRODUCTION + ".stationlogos" in authorities:
        raise ApkGuardError("Production ContentProvider authority is present")

    if "fr.grossesondes.grosses_ondes.StationLogoContentProvider" not in manifest:
        raise ApkGuardError("Native StationLogoContentProvider is missing")
    if "com.ryanheise.audioservice.AudioService" not in manifest:
        raise ApkGuardError("MediaBrowserService is missing")
    if "com.google.android.gms.car.application" not in manifest:
        raise ApkGuardError("Android Auto declaration is missing")
    if not re.search(
        r'android:debuggable[^\r\n]*(?:0xffffffff|0x00000001|\btrue\b)',
        manifest,
    ):
        raise ApkGuardError("Android debuggable=true not proven")

    if not re.search(
        r"Signer #1 certificate DN:.*CN=Android Debug", signer,
        flags=re.IGNORECASE,
    ):
        raise ApkGuardError("Certificate is not the standard Android DEBUG certificate")


def find_tools(sdk: Path) -> tuple[Path, Path]:
    build_tools = sdk / "build-tools"
    if not build_tools.is_dir():
        raise ApkGuardError("Android SDK build-tools directory missing")
    directories = sorted(
        (p for p in build_tools.iterdir() if p.is_dir()),
        key=lambda p: tuple(
            int(n) for n in re.findall(r"\d+", p.name)
        ),
        reverse=True,
    )
    for directory in directories:
        aapt = directory / "aapt.exe"
        signer = directory / "apksigner.bat"
        if aapt.is_file() and signer.is_file():
            return aapt, signer
    raise ApkGuardError("Missing aapt.exe or apksigner.bat")


def command(*args: str) -> str:
    result = subprocess.run(
        args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if result.returncode != 0:
        raise ApkGuardError(
            f"APK check failed ({Path(args[0]).name}): "
            + result.stderr.decode("utf-8", "replace")[:350]
        )
    return result.stdout.decode("utf-8", "replace")


def check_apk(apk: Path, sdk: Path) -> None:
    if not apk.is_file():
        raise ApkGuardError("Diagnostic APK was not built")
    aapt, signer = find_tools(sdk)
    badging = command(str(aapt), "dump", "badging", str(apk))
    manifest = command(str(aapt), "dump", "xmltree", str(apk), "AndroidManifest.xml")
    signature = command(str(signer), "verify", "--print-certs", str(apk))
    check_metadata(badging, manifest, signature)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apk", required=True, type=Path)
    parser.add_argument("--sdk", required=True, type=Path)
    args = parser.parse_args()
    try:
        check_apk(args.apk, args.sdk)
    except (OSError, ApkGuardError) as exc:
        parser.exit(1, f"REFUS APK DIAGNOSTIC: {exc}\n")
    print("PASS: isolated package, label, provider, MediaBrowser, Android Auto, DEBUG certificate")
    print("PASS: no APK installation attempted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
