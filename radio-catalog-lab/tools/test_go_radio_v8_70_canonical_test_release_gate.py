#!/usr/bin/env python3
"""Non-publishing final preflight: v8 canonical TEST URLs, 70 immutable owner logos.

Confirms every canonical URL resolves to the exact SHA byte object already
published on the isolated TEST asset branch. Verifies signed v7 remains active,
285 radios/320 GO IDs/363 UUID owners/24 redirects, unchanged streams/names.
No signing seed is used, no APK/main/production/pointer is modified.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
from urllib.parse import urlsplit

from audit_open_radio_artwork_inventory import inspect_bytes
from radio_catalog_release_packager import (
    load_verified_predecessor, read_public_key, validate_release_content,
    create_bundle,
)
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from test_go_radio_v8_70_owner_sha_gate import main as verify_all_staged_70

ROOT = Path(__file__).resolve().parents[2]
ROOTDIR = ROOT / "grossesondes/radio-test-v2"
SOURCE = ROOT / "radio-catalog-lab/full-staging/UNSIGNED-radio-v8-70-official-sha-logos-20261123.json"
CANONICAL = ROOT / "radio-catalog-lab/full-staging/UNSIGNED-radio-v8-70-CANONICAL-TEST-SHA-20261123.json"
TEST_BRANCH = "feature/go-radio-test-v2-isolated-20261123"
TEST_REF = "refs/remotes/origin/" + TEST_BRANCH
TEST_PREFIX = ("https://raw.githubusercontent.com/Sarogal/Ondes-Catalogues/"
               + TEST_BRANCH + "/grossesondes/radio-test-v2/artwork/sha256/")
EXPECTED_V7_SHA = "f735884aa0841a86d88aaafe406e62b7a826cf9cd60f6a70285a0894326841aa"
EXT = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}


def git_show(path: str) -> bytes:
    if not path.startswith("grossesondes/radio-test-v2/") or ".." in path:
        raise ValueError("Unapproved TEST path")
    return subprocess.check_output(
        ["git", "show", TEST_REF + ":" + path], cwd=ROOT, timeout=30)


def preflight(remote: bool = False, prior_qa: bool = True) -> dict:
    if prior_qa:
        verify_all_staged_70()
    before = json.loads(SOURCE.read_bytes())
    after = json.loads(CANONICAL.read_bytes())
    signed = load_verified_predecessor(ROOTDIR, read_public_key(ROOTDIR / "TEST_PUBLIC_KEY.b64"))
    validate_release_content(CANONICAL.read_bytes(), previous=signed)
    # Exercise the exact REAL local packager with throwaway CI-only signing key.
    # No signed output or private seed is stored or published.
    synthetic = create_bundle(
        CANONICAL.read_bytes(), Ed25519PrivateKey.generate(),
        key_id="go-v8-ephemeral-ci-only-never-publish",
        published_at="2026-11-23T21:00:00Z",
        previous=signed,
    )
    assert synthetic.sequence == 8 and synthetic.station_count == 296
    assert signed["release_sequence"] == 7 and before["release_sequence"] == after["release_sequence"] == 8
    assert len(after["stations"]) == 296 and len(signed["stations"]) == 296
    assert after["tombstones"] == before["tombstones"] == signed["tombstones"]
    assert len(after["tombstones"]) == 24
    original_by_id = {s["go_station_id"]: s for s in before["stations"]}
    signed_by_id = {s["go_station_id"]: s for s in signed["stations"]}
    assert len(original_by_id) == len(signed_by_id) == 296
    sha_index = set()
    changed = 0
    for station in after["stations"]:
        sid = station["go_station_id"]
        earlier = original_by_id[sid]
        historical = signed_by_id[sid]
        expected = deepcopy(station)
        expected["logo"] = earlier["logo"]
        assert expected == earlier, "Non-logo metadata changed between v8 candidate and canonical: " + sid
        if historical["logo"] is None and station["logo"] is not None:
            changed += 1
            old_logo = earlier["logo"]
            logo = station["logo"]
            ext = EXT[logo["mime_type"]]
            sha = logo["sha256"]
            assert old_logo is not None and sha == old_logo["sha256"]
            original_without_url = deepcopy(old_logo)
            original_without_url.pop("url")
            candidate_without_url = deepcopy(logo)
            candidate_without_url.pop("url")
            assert original_without_url == candidate_without_url
            assert sha not in sha_index, "Duplicate original SHAs cannot count twice"
            sha_index.add(sha)
            assert logo["url"] == TEST_PREFIX + sha + "." + ext
            assert logo["asset_id"] == "sha256:" + sha
            if remote:
                raw = git_show("grossesondes/radio-test-v2/artwork/sha256/" + sha + "." + ext)
                assert len(raw) == logo["byte_size"]
                assert hashlib.sha256(raw).hexdigest() == sha
                assert inspect_bytes(raw, content_type=logo["mime_type"]) == {
                    k: logo[k] for k in ("sha256", "byte_size", "width", "height", "mime_type")
                }
        else:
            assert station["logo"] == earlier["logo"] == historical["logo"]
        assert station["status"] == historical["status"]
        assert station["streams"] == historical["streams"]

    assert changed == 70 and len(sha_index) == 70
    active = [s for s in after["stations"] if s["status"]["state"] == "active"]
    assert len(active) == 285 and sum(s["logo"] is not None for s in active) == 259
    assert sum(s["logo"] is None for s in active) == 26
    get_ids = lambda c: {s["go_station_id"] for s in c["stations"] + c["tombstones"]}
    get_aliases = lambda c: {
        alias: s["go_station_id"]
        for s in c["stations"] + c["tombstones"]
        for alias in s["legacy_aliases"]
    }
    assert len(get_ids(after)) == 320 and get_ids(after) == get_ids(signed)
    assert len(get_aliases(after)) == 363 and get_aliases(after) == get_aliases(signed)
    active_pointer = json.loads((ROOTDIR / "current.json").read_bytes())
    assert active_pointer["release_sequence"] == 7
    assert active_pointer["content_sha256"] == EXPECTED_V7_SHA
    if remote:
        remote_pointer = git_show("grossesondes/radio-test-v2/current.json")
        assert remote_pointer == (ROOTDIR / "current.json").read_bytes()
    return {
        "result": "GO_TEST_V8_70_CANONICAL_SIGNABLE_SHA_PREVIEW_QA_PASS",
        "current_signed_sequence": 7,
        "next_unsigned_sequence": 8,
        "active_radios": 285, "with_logo": 259, "without_logo": 26,
        "new_sha_objects_in_TEST": len(sha_index),
        "verified_test_sha_byte_objects": len(sha_index) if remote else 0,
        "go_ids_preserved": 320, "favorite_uuid_owners_preserved": 363,
        "redirects_preserved": 24,
        "signed_v8": False, "published_v8": False,
        "test_v7_pointer_unchanged": True,
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--verify-test-assets", action="store_true")
    args = p.parse_args()
    print(json.dumps(preflight(remote=args.verify_test_assets), sort_keys=True))


if __name__ == "__main__":
    main()
