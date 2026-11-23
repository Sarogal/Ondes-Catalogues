#!/usr/bin/env python3
"""Locally sign and optionally publish GO radio TEST v8, never production.

Usage (run from clean public Ondes-Catalogues v8 feature checkout):
  python radio-catalog-lab/tools/publish_go_radio_v8_test.py \
      --signing-key-file <PRIVATE_LOCAL_SEED_PATH> [--publish-test]

NO private key or seed bytes are uploaded. The only signed objects committed
are the immutable content-addressed radio release and the Ed25519 pointer.
The existing signed TEST v7 pointer is unchanged until release bytes are
uploaded and verified through the public raw HTTPS endpoint. No APK built.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
sys.dont_write_bytecode = True  # Never create pycache files in the user's checkout.
import tempfile
import time
import urllib.error
import urllib.request

from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from radio_catalog_release_packager import (
    create_bundle, load_verified_predecessor, read_private_seed,
    read_public_key, verify_bundle, write_staging,
)
from test_go_radio_v8_70_canonical_test_release_gate import (
    CANONICAL, ROOT, ROOTDIR, TEST_BRANCH, TEST_REF, EXPECTED_V7_SHA,
    preflight,
)

REPO_URL = "https://github.com/Sarogal/Ondes-Catalogues"
RAW_TEST = ("https://raw.githubusercontent.com/Sarogal/Ondes-Catalogues/"
            + TEST_BRANCH + "/grossesondes/radio-test-v2/")
KEY_ID = "go-apk-test-20261122-v2"
EXPECTED_TEST_ASSETS_COMMIT = "2e5cc9233439317401f0fba31d10065d89009c84"
PUBLISHER_NAME = "Grosses Ondes TEST signed publisher"
PUBLISHER_EMAIL = "go-test-signing@localhost.invalid"


def git(*args: str, cwd: Path = ROOT, capture: bool = False) -> str:
    command = ["git", *args]
    result = subprocess.run(command, cwd=cwd, check=True, text=True,
                            stdout=subprocess.PIPE if capture else None)
    return result.stdout.strip() if capture else ""


def clean_checkout() -> None:
    root = Path(git("rev-parse", "--show-toplevel", capture=True)).resolve()
    if root != ROOT.resolve():
        raise ValueError("Run this script from the expected public repository checkout")
    if git("status", "--porcelain", "--untracked-files=no", capture=True):
        raise ValueError("Local checkout is not clean; never overwrite existing user files")
    remote = git("remote", "get-url", "origin", capture=True)
    if not (remote.startswith(REPO_URL) or remote.startswith("git@github.com:Sarogal/Ondes-Catalogues")):
        raise ValueError("Unexpected origin, refusing publication")


def fetch_test_branch() -> str:
    git("fetch", "--no-tags", "origin",
        "+refs/heads/" + TEST_BRANCH + ":" + TEST_REF)
    sha = git("rev-parse", TEST_REF, capture=True)
    if len(sha) != 40:
        raise ValueError("Invalid TEST branch head")
    return sha


def fetch_exact_remote(url: str, expected: bytes, attempts: int = 12) -> bool:
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(
                url, headers={"Accept": "application/json",
                              "Cache-Control": "no-cache",
                              "User-Agent": "GrossesOndesRadioTestV8Release/1"})
            with urllib.request.urlopen(request, timeout=18) as response:
                if response.status != 200:
                    raise ValueError("Remote HTTP not 200")
                length = len(expected)
                body = response.read(length + 1)
                if len(body) == length and body == expected:
                    return True
        except (OSError, ValueError, urllib.error.URLError):
            pass
        if attempt < attempts - 1:
            time.sleep(2)
    return False


def commit_only(worktree: Path, expected_path: str, message: str) -> None:
    git("add", "--", expected_path, cwd=worktree)
    staged = git("diff", "--cached", "--name-only", capture=True, cwd=worktree)
    if staged != expected_path:
        raise ValueError("Unexpected staged files; release aborted")
    git("-c", "user.name=" + PUBLISHER_NAME,
        "-c", "user.email=" + PUBLISHER_EMAIL,
        "-c", "commit.gpgsign=false",
        "commit", "-m", message, cwd=worktree)
    # Never force-push, never write main or production.
    git("push", "origin", "HEAD:refs/heads/" + TEST_BRANCH, cwd=worktree)


def publish_test(bundle, old_pointer: bytes, expected_head: str) -> dict:
    if expected_head != EXPECTED_TEST_ASSETS_COMMIT:
        raise ValueError("TEST branch changed after SHA staging; manual review required")
    work_dir = Path(tempfile.mkdtemp(prefix="go-v8-test-promotion-"))
    worktree = work_dir / "isolated-test-worktree"
    added = False
    try:
        git("worktree", "add", "--detach", str(worktree), expected_head)
        added = True
        rel_root = worktree / "grossesondes/radio-test-v2"
        active_file = rel_root / "current.json"
        if active_file.read_bytes() != old_pointer:
            raise ValueError("Signed TEST v7 pointer changed")
        if json.loads(old_pointer)["content_sha256"] != EXPECTED_V7_SHA:
            raise ValueError("Wrong predecessor SHA")
        if json.loads(old_pointer)["release_sequence"] != 7:
            raise ValueError("TEST pointer already migrated; refusing overwrite")

        release_path = rel_root / bundle.release_path
        if release_path.exists():
            raise ValueError("Immutable v8 release already exists; inspect before retry")
        release_path.parent.mkdir(parents=True, exist_ok=True)
        release_path.write_bytes(bundle.catalog_bytes)
        if hashlib.sha256(release_path.read_bytes()).hexdigest() != bundle.digest:
            raise ValueError("Release bytes changed during staging")
        staged_release = "grossesondes/radio-test-v2/" + bundle.release_path
        commit_only(worktree, staged_release, "test(radio): add signed v8 immutable 70-logo release")
        print("GO_TEST_V8_IMMUTABLE_RELEASE_COMMITTED", bundle.release_path, flush=True)
        # Critical barrier: only flip the signed pointer after raw remote
        # release bytes are byte-for-byte accessible to an actual phone.
        if not fetch_exact_remote(RAW_TEST + bundle.release_path, bundle.catalog_bytes):
            raise ValueError(
                "Immutable release push complete but remote bytes are not yet accessible; "
                "current TEST v7 remains active. Do not force-retry."
            )
        print("GO_TEST_V8_IMMUTABLE_RELEASE_HTTPS_VERIFIED", flush=True)

        if active_file.read_bytes() != old_pointer:
            raise ValueError("TEST pointer changed before promotion")
        active_file.write_bytes(bundle.pointer_bytes)
        commit_only(worktree, "grossesondes/radio-test-v2/current.json",
                    "test(radio): promote verified Ed25519 v8 70 logos to TEST pointer")
        # The Git push is authoritative; GitHub Raw CDN may take time to
        # invalidate the old pointer, so do not force-push or rewrite.
        visible = fetch_exact_remote(RAW_TEST + "current.json", bundle.pointer_bytes, attempts=5)
        return {
            "result": "GO_TEST_V8_SIGNED_POINTER_PUSHED",
            "sequence": 8, "sha256": bundle.digest,
            "remote_pointer_visible": visible, "previous_signed_v7_still_in_history": True,
            "production_unchanged": True, "play_store_unchanged": True,
        }
    finally:
        if added:
            git("worktree", "remove", "--force", str(worktree))
        shutil.rmtree(work_dir, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--signing-key-file", type=Path, required=True,
                        help="Path to local TEST v2 private Ed25519 seed, NEVER upload")
    parser.add_argument("--publish-test", action="store_true",
                        help="Two-stage publish to TEST only after full validation")
    args = parser.parse_args()

    clean_checkout()
    remote_head = fetch_test_branch()
    if remote_head != EXPECTED_TEST_ASSETS_COMMIT:
        raise ValueError(
            "Unexpected TEST branch head; release must be re-reviewed before signing"
        )
    qa = preflight(remote=True)
    if qa["new_sha_objects_in_TEST"] != 70 or qa["current_signed_sequence"] != 7:
        raise ValueError("Release candidate failed full TEST SHA preflight")

    key = read_private_seed(args.signing_key_file)
    public = read_public_key(ROOTDIR / "TEST_PUBLIC_KEY.b64")
    trusted_public_bytes = base64.b64decode((ROOTDIR / "TEST_PUBLIC_KEY.b64").read_bytes().strip(), validate=True)
    actual = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    if actual != trusted_public_bytes:
        raise ValueError("LOCAL TEST signing seed does not match pinned v7 APK public key")
    old_pointer = (ROOTDIR / "current.json").read_bytes()
    predecessor = load_verified_predecessor(ROOTDIR, public)
    published_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    bundle = create_bundle(
        CANONICAL.read_bytes(), key, key_id=KEY_ID,
        published_at=published_at, previous=predecessor
    )
    verify_bundle(bundle.pointer_bytes, bundle.catalog_bytes, public, previous=predecessor)
    work = Path(tempfile.mkdtemp(prefix="go-v8-offline-signed-"))
    signed_stage = write_staging(work / "signed-preview", bundle)
    preview = json.loads((signed_stage / "release-preview.json").read_bytes())
    assert preview["publicationAllowed"] is False
    print("GO_TEST_V8_LOCAL_SIGNING_SUCCESS", json.dumps({
        "stage": str(signed_stage), "sequence": 8,
        "content_sha256": bundle.digest, "radio_records": bundle.station_count,
        "key_id": KEY_ID, "signature_matches_existing_apk": True,
        "publish_requested": args.publish_test,
    }, ensure_ascii=False), flush=True)
    if not args.publish_test:
        print("GO_TEST_V8_PREVIEW_ONLY_NOT_PUBLISHED")
        return 0

    result = publish_test(bundle, old_pointer, remote_head)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print("GO_TEST_V8_PROMOTION_ABORTED:", type(exc).__name__, str(exc), file=sys.stderr)
        raise SystemExit(1)
