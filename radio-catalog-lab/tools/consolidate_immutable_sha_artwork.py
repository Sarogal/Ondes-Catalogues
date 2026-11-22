#!/usr/bin/env python3
"""Join 16 SHA-addressed image archives into ONE immutable, UNPUBLISHED package.

Every artifact is independently checked for station SHA metadata, exact bytes,
MIME and dimensions. The proposed URL has no status until a later, explicitly
reviewed blob-upload PR. This tool can neither sign nor publish a catalog.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

from audit_open_radio_artwork_inventory import inspect_bytes
from stage_immutable_sha_artwork import normalized_assets, EXTENSIONS

PROPOSED_BASE = (
    "https://sarogal.github.io/Ondes-Catalogues/"
    "grossesondes/radio-test-apk/artwork/sha256/"
)


def consolidate(catalog: dict, inputs: Path, output: Path) -> dict:
    expected = normalized_assets(catalog)
    dirs = list(inputs.rglob("audit-report.json"))
    if len(dirs) != 16 or output.exists():
        raise ValueError("requires 16 distinct reviewed shards and new output")
    by_index = {}
    for f in dirs:
        report = json.loads(f.read_text(encoding="utf-8"))
        index = report.get("shard_index")
        if (type(index) is not int or not 0 <= index < 16
            or index in by_index
            or report.get("shard_count") != 16
            or report.get("total_unique_descriptors") != len(expected)
            or report.get("signed_or_published") is not False
            or report.get("permission_to_replace_current_json") is not False):
            raise ValueError("untrusted/duplicate staging artifact")
        by_index[index] = (f.parent, report)
    if set(by_index) != set(range(16)):
        raise ValueError("missing SHA asset shard")
    results = []
    output.mkdir()
    store = output / "sha256"
    store.mkdir()
    nstored = 0
    for index, asset in enumerate(expected):
        directory, report = by_index[index % 16]
        shard_offset = index // 16
        records = report.get("records")
        if (not isinstance(records, list) or len(records) != report["selected"]
            or records[shard_offset].get("sha256") != asset["sha256"]):
            raise ValueError("object assigned to wrong SHA evidence shard")
        item = records[shard_offset]
        sha = asset["sha256"]
        if item.get("stored") is True:
            relative = "sha256/" + sha + "." + EXTENSIONS[asset["mime_type"]]
            if item.get("path") != relative or item.get("fetched_and_decoded") is not True:
                raise ValueError("archive path does not match content digest")
            source = directory / relative
            if source.is_symlink() or not source.is_file():
                raise ValueError("missing regular immutable image file")
            raw = source.read_bytes()
            observed = inspect_bytes(raw, content_type=asset["mime_type"])
            for field in ("sha256","byte_size","width","height","mime_type"):
                if observed[field] != asset[field]:
                    raise ValueError("staged image corruption detected")
            (store / source.name).write_bytes(raw)
            nstored += 1
            results.append({
                "sha256":sha, "relative_path":relative,
                "proposed_content_addressed_url":PROPOSED_BASE+source.name,
                "byte_size":len(raw), "ready_for_explicit_review":True,
                "already_published":False,
            })
        else:
            results.append({
                "sha256":sha,
                "ready_for_explicit_review":False,
                "already_published":False,
                "reason_code":str(item.get("error_code") or "unavailable"),
            })
    if nstored != len(list(store.iterdir())):
        raise ValueError("duplicate or missing content-addressed output files")
    summary = {
        "scope":"UNPUBLISHED_RADIO_SHA_CONTENT_ADDRESS_ARCHIVE",
        "catalog_release_sequence":5,
        "expected_unique_descriptors":len(expected),
        "immutable_objects_verified":nstored,
        "unavailable_or_drifted_objects":len(expected)-nstored,
        "requested_public_endpoint_write":False,
        "pointer_modified":False,
        "keys_written":False,
        "objects":results,
    }
    (output/"manifest-preview.json").write_text(
        json.dumps(summary,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    return summary


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--catalog",type=Path,required=True)
    p.add_argument("--input-dir",type=Path,required=True)
    p.add_argument("--output-dir",type=Path,required=True)
    a=p.parse_args()
    report=consolidate(json.loads(a.catalog.read_text(encoding="utf-8")),
                       a.input_dir,a.output_dir)
    print(json.dumps({k:report[k] for k in ("expected_unique_descriptors",
       "immutable_objects_verified","unavailable_or_drifted_objects",
       "requested_public_endpoint_write")},sort_keys=True))


if __name__=="__main__":
    main()
