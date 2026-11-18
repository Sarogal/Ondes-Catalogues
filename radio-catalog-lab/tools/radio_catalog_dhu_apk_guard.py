#!/usr/bin/env python3
"""Offline APK identity and signing gate for the standalone Android Auto DHU DEBUG.

No adb calls, no network, no APK installation. All checks fail closed.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
from pathlib import Path

PRODUCTION = "fr.grossesondes.grosses_ondes"
DIAGNOSTIC = PRODUCTION + ".dhudiag"
AUTHORITY = DIAGNOSTIC + ".stationlogos"
LABEL = "GO Diagnostic SHA"


class ApkGuardError(ValueError):
    pass


def check_metadata(
    badging: str, manifest: str, signer: str, expected_debug_sha256: str,
) -> None:
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

    # Subject / DN text is unreliable; compare the public X.509 cert digest
    # with the certificate stored in the local Android debug keystore.
    digest_lines = re.findall(
        r"(?im)^Signer\s+#(\d+)\s+certificate SHA-256 digest:\s*"
        r"([0-9a-f:]{64,95})\s*$", signer,
    )
    if len(digest_lines) != 1 or digest_lines[0][0] != "1":
        raise ApkGuardError("Exactly one APK signing certificate is required")
    actual = digest_lines[0][1].replace(":", "").lower()
    expected = expected_debug_sha256.replace(":", "").lower()
    if not re.fullmatch(r"[0-9a-f]{64}", actual):
        raise ApkGuardError("Cannot parse APK signer SHA-256 digest")
    if not re.fullmatch(r"[0-9a-f]{64}", expected) or actual != expected:
        raise ApkGuardError(
            "APK signer differs from local androiddebugkey certificate "
            f"(APK={actual}, debug.keystore={expected})"
        )


def local_debug_certificate_sha256() -> str:
    """Hash the DER public certificate exported from Android debug.keystore.

    Never exports a private key. Missing or unusual keystores fail closed.
    """
    android_home = os.environ.get("ANDROID_USER_HOME")
    home = Path(android_home) if android_home else Path.home() / ".android"
    keystore = home / "debug.keystore"
    if not keystore.is_file():
        raise ApkGuardError(
            f"Debug keystore missing at {keystore}. "
            "Check Gradle signingReport; do not bypass signature verification."
        )
    candidates = []
    java_home = os.environ.get("JAVA_HOME")
    if java_home:
        candidates.extend([
            Path(java_home) / "bin" / "keytool.exe",
            Path(java_home) / "bin" / "keytool",
        ])
    installed = shutil.which("keytool")
    if installed:
        candidates.append(Path(installed))
    if os.name == "nt":
        candidates.append(
            Path(os.environ.get("ProgramFiles", "C:/Program Files"))
            / "Android" / "Android Studio" / "jbr" / "bin" / "keytool.exe"
        )
    keytool = next((str(p) for p in candidates if p.is_file()), None)
    if keytool is None:
        raise ApkGuardError(
            "keytool not found; set JAVA_HOME to a JDK, then check the "
            "already-built APK without a Flutter rebuild."
        )
    result = subprocess.run(
        [keytool, "-exportcert", "-alias", "androiddebugkey",
         "-keystore", str(keystore), "-storepass", "android"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        check=False, timeout=25,
    )
    if result.returncode or len(result.stdout) < 128 or result.stdout[:1] != b"\x30":
        raise ApkGuardError(
            "Cannot export local androiddebugkey public certificate; "
            "inspect the debug signing configuration."
        )
    return hashlib.sha256(result.stdout).hexdigest()


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
    check_metadata(
        badging, manifest, signature, local_debug_certificate_sha256(),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apk", required=True, type=Path)
    parser.add_argument("--sdk", required=True, type=Path)
    args = parser.parse_args()
    try:
        check_apk(args.apk, args.sdk)
    except (OSError, subprocess.TimeoutExpired, ApkGuardError) as exc:
        parser.exit(1, f"REFUS APK DIAGNOSTIC: {exc}\n")
    print("PASS: isolated package, label, provider, MediaBrowser, Android Auto, matched local debug certificate SHA-256")
    print("PASS: no APK installation attempted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
