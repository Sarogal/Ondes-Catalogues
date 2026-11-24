#!/usr/bin/env python3
"""Verify 31 formerly feature-branch-only SHA blobs now copied to canonical TEST.

This audits the exact HTTPS bytes, content types and content SHA-256 of 31
immutable files mapped by 32 signed v8 radio descriptors, without altering v8.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
import json
from pathlib import Path
from test_go_radio_v8_70_https_delivery import TEST_PREFIX, verify

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "radio-catalog-lab/full-staging/UNSIGNED-radio-v8-70-CANONICAL-TEST-SHA-20261123.json"
SOURCE_PREFIXES = (
    "https://raw.githubusercontent.com/Sarogal/Ondes-Catalogues/"
    "feature/go-radio-v6-dedupe-logo-audit-20261123/",
    "https://raw.githubusercontent.com/Sarogal/Ondes-Catalogues/"
    "feature/go-radio-v7-13-dedupe-20261123/",
)
EXT = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}


def main():
    doc = json.loads(CATALOG.read_bytes())
    live = [s for s in doc["stations"] if s["status"]["state"] == "active"]
    staging = [s for s in live if s.get("logo") is not None and
               s["logo"]["url"].startswith(SOURCE_PREFIXES)]
    assert len(staging) == 32, "Expected precisely 32 original signed v8 references"
    selected = {}
    for station in staging:
        logo = station["logo"]
        sha = logo["sha256"]
        assert len(sha) == 64 and all(x in "0123456789abcdef" for x in sha)
        canonical = TEST_PREFIX + sha + EXT[logo["mime_type"]]
        candidate = deepcopy(station)
        candidate["logo"]["url"] = canonical
        if sha in selected:
            assert selected[sha]["logo"] == candidate["logo"]
        selected[sha] = candidate
    assert len(selected) == 31
    with ThreadPoolExecutor(max_workers=7) as pool:
        tasks = [pool.submit(verify, s) for s in selected.values()]
        results = [task.result() for task in as_completed(tasks)]
    failed = [x for x in results if x["result"] != "HTTPS_SHA_OK"]
    print(json.dumps({
        "result": "GO_V8_31_STAGING_BLOBS_CANONICAL_TEST_HTTPS_SHA_AUDIT",
        "v8_station_descriptors": len(staging),
        "immutable_sha_objects": len(selected),
        "verified_objects": len(results) - len(failed),
        "failed": failed,
        "signed_v8_pointer_unmodified": True,
        "notice": "Existing signed v8 still references old staging URLs; a subsequent signed release must repoint these 32 logos.",
    }, sort_keys=True))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
