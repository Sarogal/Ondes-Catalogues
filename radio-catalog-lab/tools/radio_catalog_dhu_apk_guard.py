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

    # apksigner exposes several signer labels depending on SDK/build tools:
    # "Signer #1", "Signer (minSdkVersion=..., maxSdkVersion=...)",
    # "V2 Signer:" and "V3.0 Signer:". Check EVERY certificate digest,
    # never just the first one, and require the local debug key's public cert.
    expected = expected_debug_sha256.replace(":", "").lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ApkGuardError("Invalid local debug certificate SHA-256")
    certificate_lines = [
        line.strip() for line in signer.splitlines()
        if re.search(r"certificate\s+SHA-256\s+digest\s*:", line, re.I)
    ]
    if not certificate_lines:
        markers = [
            line.strip()[:170] for line in signer.splitlines()
            if re.search(r"signer|certificate|signatures", line, re.I)
        ][:6]
        raise ApkGuardError(
            "No certificate SHA-256 digest found in apksigner output "
            f"(signing lines: {markers!r}); refusing installation"
        )
    format_pattern = re.compile(
        r"(?:V[1-4](?:\.\d+)?\s+Signer:\s*|"
        r"Signer\s+(?:#(?P<number>[1-9]\d*)|"
        r"\(minSdkVersion\s*=\s*\d+\s*,\s*maxSdkVersion\s*=\s*\d+\))"
        r"\s+)"
        r"certificate\s+SHA-256\s+digest:\s*"
        r"(?P<digest>[0-9a-fA-F:]+)",
        re.IGNORECASE,
    )
    numbers = set()
    fingerprints = set()
    for line in certificate_lines:
        match = format_pattern.fullmatch(line)
        if not match:
            raise ApkGuardError(
                "Unrecognized apksigner certificate SHA-256 line: "
                f"{line[:170]!r}; refusing installation"
            )
        if match.group("number"):
            numbers.add(int(match.group("number")))
        fingerprint = match.group("digest").replace(":", "").lower()
        if not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
            raise ApkGuardError("Malformed certificate SHA-256 digest")
        fingerprints.add(fingerprint)

    if numbers and numbers != {1}:
        raise ApkGuardError(
            f"APK contains unexpected numbered signers {sorted(numbers)}"
        )
    declared_signers = re.findall(
        r"(?im)^\s*Number of signers:\s*(\d+)\s*$", signer
    )
    if declared_signers and (
        len(declared_signers) != 1 or declared_signers[0] != "1"
    ):
        raise ApkGuardError("APK must have exactly one declared signer")
    if len(fingerprints) != 1 or fingerprints != {expected}:
        raise ApkGuardError(
            "APK certificate SHA-256 differs from local androiddebugkey "
            f"(APK={sorted(fingerprints)}, debug.keystore={expected})"
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
