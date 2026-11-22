#!/usr/bin/env python3
"""Stage exact historical SHA artwork bytes as content-addressed TEST artifacts.

READ-ONLY network. Writes only to the selected temporary CI artifact directory;
never signs a pointer, modifies any Git branch, nor publishes to TEST current.
Every image must match the SHA-256, length, MIME, width and height declared in
the reviewed central catalog. Nonmatching images are rejected, never substituted.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

from audit_open_radio_artwork_inventory import (
    _request, inspect_bytes, MAX_IMAGE, public_https,
)

SHA = re.compile(r"^[0-9a-f]{64}$")
EXTENSIONS = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}
REQUIRED = {"sha256", "byte_size", "width", "height", "mime_type", "url", "asset_id"}


def normalized_assets(catalog: dict) -> list[dict]:
    if catalog.get("release_sequence") != 5:
        raise ValueError("unexpected catalog version")
    by_sha = {}
    if len(catalog.get("stations", [])) != 320:
        raise ValueError("expected the independently verified 320-station staging")
    for station in catalog["stations"]:
        logo = station.get("logo")
        if logo is None:
            continue
        if not isinstance(logo, dict) or not REQUIRED.issubset(logo):
            raise ValueError("incomplete SHA logo descriptor")
        digest = logo["sha256"]
        if not isinstance(digest, str) or not SHA.fullmatch(digest) or logo["asset_id"] != "sha256:" + digest:
            raise ValueError("invalid SHA or asset identity")
        if logo["mime_type"] not in EXTENSIONS or \
                type(logo["byte_size"]) is not int or not 0 < logo["byte_size"] <= MAX_IMAGE:
            raise ValueError("image exceeds bounded SHA artwork limits")
        if not public_https(logo["url"]):
            raise ValueError("unsafe historical source URL")
        old = by_sha.get(digest)
        if old is None:
            by_sha[digest] = dict(logo)
        else:
            for key in ("byte_size", "width", "height", "mime_type"):
                if old[key] != logo[key]:
                    raise ValueError("conflicting metadata for shared SHA digest")
    return [by_sha[sha] for sha in sorted(by_sha)]


def mirror(catalog: dict, *, index: int, count: int, destination: Path,
           fetcher=None, inspector=None) -> dict:
    if not 0 <= index < count <= 32:
        raise ValueError("invalid shard")
    assets = normalized_assets(catalog)
    selection = [record for n, record in enumerate(assets) if n % count == index]
    destination = Path(destination)
    if destination.exists():
        raise ValueError("refuse to overwrite existing mirror archive")
    destination.mkdir(parents=True)
    objects = destination / "sha256"
    objects.mkdir()
    fetcher = fetcher or _request
    inspector = inspector or inspect_bytes
    records = []
    counts = Counter()
    for item in selection:
        sha = item["sha256"]
        result = {"sha256": sha, "asset_id": item["asset_id"],
                  "fetched_and_decoded": False, "stored": False}
        try:
            body, mime, _ = fetcher(
                item["url"], max_bytes=MAX_IMAGE,
                accept="image/png,image/jpeg,image/webp")
            if not isinstance(body, bytes):
                raise ValueError("source did not provide bytes")
            inspected = inspector(body, content_type=mime)
            for field in ("sha256", "byte_size", "width", "height", "mime_type"):
                if inspected.get(field) != item[field]:
                    raise ValueError("mismatched_" + field)
            if hashlib.sha256(body).hexdigest() != sha:
                raise ValueError("mismatched_sha256")
            file_name = "sha256/" + sha + "." + EXTENSIONS[item["mime_type"]]
            (destination / file_name).write_bytes(body)
            result.update({"fetched_and_decoded": True, "stored": True,
                           "byte_size": len(body), "path": file_name,
                           "mime_type": item["mime_type"], "width": item["width"],
                           "height": item["height"]})
            counts["stored"] += 1
        except Exception as exc:
            # Protect the evidence pipeline against a single unavailable CDN.
            # Do not expose URLs, tokens or TLS details in public CI logs.
            reason = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
            result["error_code"] = reason[:70]
            counts[reason[:70]] += 1
        records.append(result)
    report = {
        "scope": "GO_RADIO_CONTENT_ADDRESSED_IMAGE_BYTES_TEST_STAGING_ONLY",
        "total_unique_descriptors": len(assets),
        "shard_index": index, "shard_count": count,
        "selected": len(selection),
        "stored": counts["stored"],
        "failed": len(selection) - counts["stored"],
        "reason_counts": dict(sorted(counts.items())),
        "records": records,
        "signed_or_published": False,
        "permission_to_replace_current_json": False,
    }
    (destination / "audit-report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--catalog",type=Path,required=True)
    p.add_argument("--shard-index",type=int,required=True)
    p.add_argument("--shard-count",type=int,default=16)
    p.add_argument("--output-dir",type=Path,required=True)
    a=p.parse_args()
    catalog=json.loads(a.catalog.read_text(encoding="utf-8"))
    report=mirror(catalog,index=a.shard_index,count=a.shard_count,
                  destination=a.output_dir)
    print(json.dumps({k:report[k] for k in
        ("shard_index","selected","stored","failed","reason_counts",
         "signed_or_published")},sort_keys=True))


if __name__=="__main__":
    main()
