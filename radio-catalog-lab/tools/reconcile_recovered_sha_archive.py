#!/usr/bin/env python3
"""Reconcile exact original SHA assets with a recovered SAME-SHA retry.

Never promote a different bitmap to an existing SHA. New/rotated image bytes
stay in a distinct review artifact, not in the original trusted archive.
Offline only, never publishes GitHub Pages nor a catalog pointer.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil

from audit_open_radio_artwork_inventory import inspect_bytes
from stage_immutable_sha_artwork import normalized_assets, EXTENSIONS


def merge(original: Path, retry: Path, catalog: dict, output: Path) -> dict:
    if output.exists():
        raise ValueError("Immutable archive destination already exists")
    source = json.loads((original / "manifest-preview.json").read_text(encoding="utf-8"))
    retry_report = json.loads((retry / "unsigned-proposals.json").read_text(encoding="utf-8"))
    expected = {d["sha256"]: d for d in normalized_assets(catalog)}
    if (source.get("scope") != "UNPUBLISHED_RADIO_SHA_CONTENT_ADDRESS_ARCHIVE"
        or source.get("expected_unique_descriptors") != 89
        or source.get("immutable_objects_verified") != 86
        or retry_report.get("scope") != "UNSIGNED_NEW_SHA_ARTWORK_REVIEW_PROPOSALS_ONLY"
        or retry_report.get("signed_or_published") is not False):
        raise ValueError("Unrecognized original or retry provenance")
    if len(source.get("objects", [])) != len(expected):
        raise ValueError("Incomplete SHA archive manifest")

    retries = {p["old_sha256"]: p for p in retry_report["proposals"]}
    output.mkdir(parents=True)
    store = output / "sha256"
    store.mkdir()
    records = []
    recovered = []
    for record in source["objects"]:
        sha = record["sha256"]
        if sha not in expected:
            raise ValueError("Unexpected SHA object")
        descriptor = expected[sha]
        filename = sha + "." + EXTENSIONS[descriptor["mime_type"]]
        current = original / "sha256" / filename
        if record["ready_for_explicit_review"] is True:
            in_file = current
            status = "original_archive"
        else:
            item = retries.get(sha)
            if item and item.get("source_check") == "recovered_same_SHA":
                relative = item["verified_file"]
                if relative != "sha256/" + filename:
                    raise ValueError("Recovered SHA file path is not canonical")
                in_file = retry / relative
                status = "recovered_original_SHA"
            else:
                records.append({
                    "sha256": sha,
                    "stored": False,
                    "status": "unavailable_awaiting_quality_review",
                    "candidate_new_SHA_only": bool(item and
                        item.get("source_check") == "new_SHA_candidate_not_approved"),
                })
                continue
        if in_file.is_symlink() or not in_file.is_file():
            raise ValueError("Required historic exact SHA image file missing")
        data = in_file.read_bytes()
        verified = inspect_bytes(data, content_type=descriptor["mime_type"])
        for key in ("sha256", "byte_size", "width", "height", "mime_type"):
            if verified[key] != descriptor[key]:
                raise ValueError("SHA artwork bytes/metadata mismatch: " + key)
        (store / filename).write_bytes(data)
        records.append({"sha256": sha, "stored": True, "status": status})
        if status == "recovered_original_SHA":
            recovered.append(sha)

    count = len(list(store.iterdir()))
    if count != 87 or len(recovered) != 1:
        raise ValueError("Expected precisely 86+1 independently verified original SHA objects")
    result = {
        "scope": "UNPUBLISHED_ORIGINAL_SHA_ARCHIVE_WITH_ONE_RECOVERY",
        "expected_original_SHA_objects": 89,
        "original_SHA_objects_available": count,
        "recovered_original_SHA": recovered,
        "replacements_not_approved": 2,
        "remaining_unavailable": [r["sha256"] for r in records if not r["stored"]],
        "records": records,
        "pointer_updated": False,
        "images_published": False,
        "signed_or_published": False,
    }
    (output / "manifest-reconciled.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for field in ("original", "retry", "catalog", "output"):
        parser.add_argument("--"+field,required=True,type=Path)
    args=parser.parse_args()
    catalog=json.loads(args.catalog.read_text(encoding="utf-8"))
    r=merge(args.original,args.retry,catalog,args.output)
    print(json.dumps({
      "expected_original_SHA_objects":r["expected_original_SHA_objects"],
      "original_SHA_objects_available":r["original_SHA_objects_available"],
      "recovered_original_SHA":r["recovered_original_SHA"],
      "replacements_not_approved":r["replacements_not_approved"],
      "signed_or_published":False,
    },sort_keys=True))


if __name__=="__main__":
    main()
