#!/usr/bin/env python3
"""Reconcile 16 read-only historical-logo SHAs against 310 original V64 UUIDs.

Only originally displayed logo source URLs are accepted as historical reuse.
New HTML discoveries remain candidates. This emits a new UNSIGNED staging
catalog with exact SHA, MIME, bytes, dimensions, and single canonical HTTPS
source, without making up source image bytes or silently overwriting a logo.
"""
from __future__ import annotations
import argparse
import copy
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlsplit

SHA = re.compile(r"^[0-9a-f]{64}$")
MIME = {"image/png", "image/jpeg", "image/webp"}


def build(inventory: dict, reports: list[dict], radio_catalog: dict):
    originals = inventory.get("stations")
    if not isinstance(originals, list) or len(originals) != 310:
        raise ValueError("must use exact 310-V64 historical artwork inventory")
    expected = {entry["legacy_media_id"]: entry for entry in originals}
    if len(expected) != 310:
        raise ValueError("duplicate historical media UUID")
    if len(reports) != 16 or sorted(r.get("shard_index") for r in reports) != list(range(16)):
        raise ValueError("all 16 provenance shards required exactly once")
    decoded = []
    source_errors = Counter()
    proposals = 0
    inspected = set()
    for report in reports:
        if report.get("source_blob_sha") != inventory["source"]["blob_sha"] or \
                report.get("shard_count") != 16 or \
                report.get("inventory_total") != 310 or \
                report.get("publication_allowed") is not False or \
                report.get("signed_catalog_created") is not False:
            raise ValueError("invalid historical logo evidence context")
        shard = report["shard_index"]
        positions = [pos for pos in range(310) if pos % 16 == shard]
        records = report.get("records")
        if not isinstance(records, list) or len(records) != len(positions):
            raise ValueError("shard must include every original station in order")
        for pos, record in zip(positions, records):
            original = originals[pos]
            uuid = record.get("legacy_media_id")
            if (uuid != original["legacy_media_id"] or
                record.get("display_name") != original["display_name"] or
                record.get("source_logo_url") != original["source_logo_url"] or
                uuid in inspected or
                record.get("publication_allowed") is not False or
                record.get("station_logo_approved") is not False):
                raise ValueError("tampered or duplicate historical logo identity")
            inspected.add(uuid)
            probe = record.get("probe", {})
            if not probe.get("verified_bytes"):
                source_errors[str(probe.get("reason") or
                    record.get("discovery", {}).get("reason") or "missing_historical_logo")] += 1
                proposals += len(record.get("discovery", {}).get("image_candidates", []))
                continue
            sha = probe.get("sha256")
            size, w, h = probe.get("byte_size"), probe.get("width"), probe.get("height")
            mime, source_url = probe.get("mime_type"), probe.get("candidate_url")
            actual_url = probe.get("final_source_url")
            if (not isinstance(sha, str) or not SHA.fullmatch(sha) or
                any(type(n) is not int or n < 1 for n in (size, w, h)) or
                size > 2*1024*1024 or w > 4096 or h > 4096 or mime not in MIME or
                not isinstance(actual_url, str) or
                urlsplit(actual_url).scheme != "https" or
                not isinstance(source_url, str)):
                raise ValueError("invalid byte-verified SHA evidence")
            historic = original["source_logo_url"]
            expected_request = ("https://" + historic[7:]) if historic.startswith("http://") else historic
            if expected_request != source_url:
                raise ValueError("image SHA was not calculated from historically sourced logo")
            if urlsplit(actual_url).username or urlsplit(actual_url).password:
                raise ValueError("HTTPS image credentials forbidden")
            decoded.append({
                "legacy_media_id": uuid,
                "display_name": original["display_name"],
                "source_original": historic,
                "sha256": sha,
                "byte_size": size,
                "width": w,
                "height": h,
                "mime_type": mime,
                "verified_https_url": actual_url,
            })
    if len(inspected) != 310:
        raise ValueError("partial historical logo evidence")
    candidate = copy.deepcopy(radio_catalog)
    if len(candidate.get("stations", [])) != 320:
        raise ValueError("expected full central staging")
    owners = {}
    for row in candidate["stations"]:
        for alias in row["legacy_aliases"]:
            if alias in owners:
                raise ValueError("duplicate staging UUID")
            owners[alias] = row
    groups = defaultdict(list)
    for item in decoded:
        owner = owners.get(item["legacy_media_id"])
        if owner is None:
            raise ValueError("historical logo UUID missing from central catalog")
        groups[owner["go_station_id"]].append(item)
    attached, preserved, conflict = [], [], []
    for s in candidate["stations"]:
        matches = groups.get(s["go_station_id"], [])
        if s.get("logo") is not None:
            if matches:
                preserved.append({"go_station_id":s["go_station_id"],
                    "reason":"previous_sha_logo_preserved",
                    "new_sha_candidates": [item["sha256"] for item in matches]})
            continue
        digests = {item["sha256"] for item in matches}
        if len(digests) > 1:
            conflict.append({"go_station_id":s["go_station_id"],
                "reason":"different_historical_quality_logos_need_review",
                "sha256_options":sorted(digests)})
            continue
        if not matches:
            continue
        item = matches[0]
        sha = item["sha256"]
        s["logo"] = {
            "asset_id":"sha256:" + sha,
            "sha256":sha,
            "revision":1,
            "url":item["verified_https_url"],
            "byte_size":item["byte_size"],
            "width":item["width"],
            "height":item["height"],
            "mime_type":item["mime_type"],
        }
        attached.append({"go_station_id":s["go_station_id"],
            "legacy_media_id":item["legacy_media_id"],"sha256":sha})
    return candidate, {
        "scope":"UNSIGNED_HISTORICAL_RADIO_ARTWORK_BYTES",
        "historical_inventory":len(originals),
        "sha_verified_historical_sources":len(decoded),
        "unique_sha_from_historical_sources":len({a["sha256"] for a in decoded}),
        "total_sha_descriptors_in_central_preview":sum(
            s.get("logo") is not None for s in candidate["stations"]),
        "new_historical_logo_associations":attached,
        "existing_sha_logo_preserved":preserved,
        "ambiguous_merged_station_logo_conflicts":conflict,
        "historical_sources_not_verified_reasons":dict(sorted(source_errors.items())),
        "discovery_image_candidates_unverified":proposals,
        "immutable_bytes_mirroring_required":True,
        "signed_publication_allowed":False,
        "existing_radio_content_changed":False,
    }


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--inventory",type=Path,required=True)
    p.add_argument("--reports-dir",type=Path,required=True)
    p.add_argument("--catalog",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--report",type=Path,required=True)
    args=p.parse_args()
    for path in (args.out,args.report):
        if path.exists():
            p.error("will not overwrite any existing staging file")
    files=sorted(args.reports_dir.rglob("go-logo-probe-*.json"))
    if len(files)!=16:
        raise ValueError(f"expected 16 complete artwork evidence shards, got {len(files)}")
    j=lambda path:json.loads(path.read_text(encoding="utf-8"))
    updated,summary=build(j(args.inventory),[j(f) for f in files],j(args.catalog))
    args.out.write_text(json.dumps(updated,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    args.report.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:summary[k] for k in (
        "historical_inventory","sha_verified_historical_sources",
        "total_sha_descriptors_in_central_preview",
        "discovery_image_candidates_unverified","signed_publication_allowed")}))
    print("Ambiguous duplicate channels:",len(summary["ambiguous_merged_station_logo_conflicts"]))


if __name__=="__main__":
    main()
