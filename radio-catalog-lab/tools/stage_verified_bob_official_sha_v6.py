#!/usr/bin/env python3
"""Stage a separate UNSIGNED v6 draft with official RADIO BOB! SHA images.

The 14 channel tiles were independently observed on the first-party dynamic
pages and separately SHA-verified from the broadcaster CDN (Actions run
45113298003). Consume the immutable pinned artifact, verify EVERY byte and
image dimension, then stage 14 SHA objects and an unsigned draft. Never sign,
update current.json, or promote any TEST branch from this script.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

from audit_open_radio_artwork_inventory import inspect_bytes
from probe_bob_official_channel_tile_sha_v6 import OFFICIAL_CHANNELS, target_rows

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "radio-catalog-lab/full-staging/UNSIGNED-radio-v6-radcap-3-duplicate-families-20261123.json"
OUTPUT = ROOT / "radio-catalog-lab/full-staging/UNSIGNED-radio-v6-radcap-bob-3-duplicate-families-20261123.json"
OBJECT_DIR = ROOT / "grossesondes/radio-test-v2/artwork/staging-unpublished"
RAW_BASE = ("https://raw.githubusercontent.com/Sarogal/Ondes-Catalogues/"
            "feature/go-radio-v6-dedupe-logo-audit-20261123/"
            "grossesondes/radio-test-v2/artwork/staging-unpublished/")
EXPECTED_OLD_LOGOS = 171
EXPECTED_NEW_LOGOS = 190


def checked_artifact(root: Path) -> tuple[dict, dict[str, bytes]]:
    manifests = [p for p in root.rglob("bob-official-channel-tile-evidence.json")
                 if p.is_file() and not p.is_symlink()]
    if len(manifests) != 1:
        raise ValueError("Expected exactly one official BOB artifact manifest")
    manifest_file = manifests[0]
    artifact_root = manifest_file.parent
    if manifest_file.stat().st_size > 128 * 1024:
        raise ValueError("BOB image evidence oversized")
    report = json.loads(manifest_file.read_text(encoding="utf-8"))
    if (report.get("scope") != "BOB_FIRST_PARTY_SQUARE_TILE_SHA_UNPUBLISHED"
            or report.get("candidate_release_sequence") != 6
            or report.get("unique_official_channel_pages") != 14
            or report.get("station_ids_with_missing_logo") != 19
            or report.get("publication_allowed") is not False
            or report.get("images_do_not_become_signed_until_separate_review") is not True):
        raise ValueError("Wrong unsigned official logo evidence")
    rows = report.get("records", [])
    if not isinstance(rows, list) or len(rows) != 14:
        raise ValueError("Incomplete BOB image artifact evidence")
    images: dict[str, bytes] = {}
    seen_names = set()
    for item in rows:
        code = item.get("channel_stream_slug")
        if code not in OFFICIAL_CHANNELS or code in seen_names:
            raise ValueError("Unexpected/duplicated BOB official channel")
        seen_names.add(code)
        page, asset = OFFICIAL_CHANNELS[code]
        if (item.get("verified_first_party_page") != "https://www.radiobob.de/" + page
                or item.get("official_square_tile_url")
                != "https://images.radiobob.de/files/" + asset + "?width=360&height=360"):
            raise ValueError("Official channel image URL changed")
        # The dynamically rendered browser association is reviewed separately;
        # never infer identity merely from a Radio Browser favicon.
        if (item.get("download_verified_sha") is not True
                or item.get("editorial_identity_review_complete") is not False
                or item.get("publication_allowed") is not False):
            raise ValueError("BOB image unverified or incorrectly marked approved")
        meta = item.get("sha_evidence")
        if not isinstance(meta, dict) or meta.get("mime_type") not in {
                "image/jpeg", "image/png", "image/webp"}:
            raise ValueError("No image byte verification")
        digest = meta.get("sha256")
        path = item.get("staged_object_name", "")
        if (not isinstance(digest, str) or len(digest) != 64
                or path != "objects/" + digest + "." + {
                    "image/jpeg":"jpg", "image/png":"png",
                    "image/webp":"webp"}[meta["mime_type"]]):
            raise ValueError("Untrusted staged SHA object path")
        raw_path = artifact_root / path
        if raw_path.is_symlink() or not raw_path.is_file() or raw_path.stat().st_size > 2*1024*1024:
            raise ValueError("Missing original SHA object bytes")
        raw = raw_path.read_bytes()
        exact = inspect_bytes(raw, content_type=meta["mime_type"])
        if exact != meta or hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError("Image bytes no longer match pinned evidence")
        images[code] = raw
    if seen_names != set(OFFICIAL_CHANNELS) or len(images) != 14:
        raise ValueError("Missing official channel evidence")
    return report, images


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=ROOT)
    args = parser.parse_args()
    report, images = checked_artifact(args.artifact_root)
    original = json.loads(SOURCE.read_text(encoding="utf-8"))
    target = target_rows(original)
    if original["release_sequence"] != 6 or len(original["stations"]) != 315:
        raise ValueError("Incorrect base v6 draft")
    if sum(s.get("logo") is not None for s in original["stations"]) != EXPECTED_OLD_LOGOS:
        raise ValueError("Unexpected existing signed logo references")
    record = {entry["channel_stream_slug"]: entry for entry in report["records"]}
    assert set(target) == set(images)
    output_root = args.output_root.resolve()
    if output_root != ROOT.resolve():
        raise ValueError("Only checked-out development tree may be used as output")
    if OUTPUT.exists():
        raise ValueError("Refusing to overwrite existing unsigned follow-up draft")
    if OBJECT_DIR.exists():
        raise ValueError("Refusing to overwrite existing staged SHA objects")
    byid = {s["go_station_id"]: s for s in original["stations"]}
    from copy import deepcopy
    draft = deepcopy(original)
    changed = {}
    for code, ids in target.items():
        entry = record[code]
        if set(entry["go_station_ids"]) != set(ids):
            raise ValueError("Verified image/station identity changed since audit")
        meta = entry["sha_evidence"]
        digest = meta["sha256"]
        descriptor = {
            "asset_id": "sha256:" + digest,
            "sha256": digest,
            "revision": 1,
            "url": RAW_BASE + digest + ".webp",
            "byte_size": meta["byte_size"],
            "width": meta["width"],
            "height": meta["height"],
            "mime_type": meta["mime_type"],
        }
        if descriptor["mime_type"] != "image/webp":
            raise ValueError("Exact staged BOB image extension unexpectedly changed")
        for goid in ids:
            old = byid[goid]
            if old["logo"] is not None:
                raise ValueError("Cannot overwrite previous station logo")
            replacement = next(s for s in draft["stations"] if s["go_station_id"] == goid)
            replacement["logo"] = descriptor.copy()
            changed[goid] = code

    if len(changed) != 19:
        raise ValueError("Expected exactly 19 previously missing logos")
    if sum(s.get("logo") is not None for s in draft["stations"]) != EXPECTED_NEW_LOGOS:
        raise ValueError("Unexpected final logo count")
    if (len(draft["tombstones"]) != 5
            or sum(s["status"]["state"] == "active" for s in draft["stations"]) != 304):
        raise ValueError("Unexpected merges or active radio counts")

    # Store objects only in the new DEVELOPMENT branch, never in main or the
    # public TEST v5 branch. No pointer is written/changed.
    for code, data in images.items():
        digest = record[code]["sha_evidence"]["sha256"]
        path = OBJECT_DIR / (digest + ".webp")
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            raise ValueError("Refusing to overwrite a SHA object")
        path.write_bytes(data)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(draft, ensure_ascii=False, indent=2)+"\n",
                      encoding="utf-8")
    print(json.dumps({
        "result":"GO_RADIO_V6_BOB_OFFICIAL_SHA_STAGING_ONLY",
        "radio_rows":len(draft["stations"]),
        "active_radio_rows":304,
        "new_official_image_sha_objects":len(images),
        "new_logo_references":len(changed),
        "total_logo_references":EXPECTED_NEW_LOGOS,
        "signed":False,"publication_allowed":False,
        "active_TEST_v5_pointer_unchanged":True,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
