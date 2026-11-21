#!/usr/bin/env python3
"""Consolidate verified-byte logo EVIDENCE from all open-inventory shards.

No editorial promotion, no catalog writing/signing, no download. Source
stations are checked against exact historical media IDs to reject gaps or
duplicate/shifted shards. Novel names and domains remain admissible.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path


class EvidenceError(ValueError):
    pass


def consolidate(inventory: dict, reports: list[dict]) -> dict:
    from audit_open_radio_artwork_inventory import validate_inventory
    stations = validate_inventory(inventory)
    source_blob = inventory["source"]["blob_sha"]
    by_id = {s["legacy_media_id"]: s for s in stations}
    seen: dict[str, dict] = {}
    shard_count = None
    shard_indices = set()
    for report in reports:
        if (not isinstance(report, dict) or
                report.get("scope") != "UNREVIEWED_ARTWORK_EVIDENCE_ONLY" or
                report.get("publication_allowed") is not False or
                report.get("signed_catalog_created") is not False or
                report.get("source_blob_sha") != source_blob):
            raise EvidenceError("Unsupported or mismatched evidence source")
        count = report.get("shard_count")
        index = report.get("shard_index")
        if (type(count) is not int or not 1 <= count <= 64 or
                type(index) is not int or not 0 <= index < count or
                (shard_count is not None and count != shard_count) or
                index in shard_indices):
            raise EvidenceError("Duplicate, malformed or inconsistent shard")
        shard_count = count
        shard_indices.add(index)
        records = report.get("records")
        if not isinstance(records, list):
            raise EvidenceError("Missing evidence records")
        for row in records:
            if not isinstance(row, dict):
                raise EvidenceError("Malformed station evidence")
            id_ = row.get("legacy_media_id")
            station = by_id.get(id_)
            if station is None or id_ in seen or \
               row.get("source_logo_url") != station["source_logo_url"] or \
               row.get("station_logo_approved") is not False or \
               row.get("publication_allowed") is not False or \
               station["source_position"] % count != index:
                raise EvidenceError("Conflicting, unknown or shifted historical identity")
            seen[id_] = row

    if shard_count is None or len(shard_indices) != shard_count or \
       len(seen) != len(stations):
        raise EvidenceError("Incomplete historical inventory coverage")

    decoded_shas = defaultdict(list)
    for id_, row in seen.items():
        probe = row.get("probe", {})
        if probe.get("verified_bytes"):
            sha = probe.get("sha256")
            if not isinstance(sha, str) or len(sha) != 64 or \
               not all(x in "0123456789abcdef" for x in sha):
                raise EvidenceError("Invalid evidence SHA")
            decoded_shas[sha].append(id_)

    records = []
    summary = Counter()
    for station in stations:
        id_ = station["legacy_media_id"]
        row = seen[id_]
        kind = row["source_kind"]
        summary[kind] += 1
        probe = row.get("probe", {})
        possible_logo = probe.get("verified_bytes") is True
        flags = []
        if kind == "legacy_http":
            flags.append("http_original_https_upgrade_needs_review")
        source_url = (probe.get("final_source_url") or
                      probe.get("candidate_url") or station["source_logo_url"])
        if any(word in source_url.lower() for word in (
            "favicon", "logoq.", "tunein", "generic",
        )):
            flags.append("possible_favicon_or_aggregator_brand_logo")
        if possible_logo and min(probe["width"], probe["height"]) < 192:
            flags.append("small_image_quality_review")
        if possible_logo and len(decoded_shas[probe["sha256"]]) > 1:
            flags.append("identical_bytes_for_multiple_stations_review_identity")
        if not possible_logo:
            flags.append("source_missing_or_not_decodable")
        for candidate in row.get("discovery", {}).get("image_candidates", []):
            if candidate.get("editorial_status") != "needs_identity_review":
                raise EvidenceError("Homepage discovery tried auto-approval")
        state = "evidence_ready_for_manual_identity_review" if possible_logo \
            else "needs_more_discovery_or_source_repair"
        summary[state] += 1
        records.append({
            "legacy_media_id": id_,
            "display_name": station["display_name"],
            "primary_genre": station["primary_genre"],
            "homepage": station["homepage"],
            "source_kind": kind,
            "candidate_source_url": source_url,
            "bytes_verified_by_sha_and_decoder": possible_logo,
            "sha256": probe.get("sha256") if possible_logo else None,
            "byte_size": probe.get("byte_size") if possible_logo else None,
            "width": probe.get("width") if possible_logo else None,
            "height": probe.get("height") if possible_logo else None,
            "mime_type": probe.get("mime_type") if possible_logo else None,
            "source_reason": probe.get("reason") or row.get("discovery", {}).get("reason"),
            "unreviewed_homepage_candidates":
                row.get("discovery", {}).get("image_candidates", []),
            "review_flags": flags,
            "editorial_state": state,
            "station_logo_approved": False,
            "publication_allowed": False,
        })
    return {
        "schema_version": 1,
        "source_blob_sha": source_blob,
        "scope": "FULL_ARTWORK_EVIDENCE_UNREVIEWED",
        "historical_station_count": len(stations),
        "shards": shard_count,
        "summary": dict(sorted(summary.items())),
        "duplicate_sha_groups": [
            {"sha256": key, "legacy_media_ids": values}
            for key, values in sorted(decoded_shas.items()) if len(values) > 1
        ],
        "publication_allowed": False,
        "signed_catalog_created": False,
        "records": records,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
    paths = sorted(args.input_dir.glob("artwork-inventory-evidence-*.json"))
    report = consolidate(inventory, [
        json.loads(p.read_text(encoding="utf-8")) for p in paths
    ])
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2)+"\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status":"GO_ARTWORK_FULL_AUDIT_NOT_PUBLISHABLE",
        "stations":report["historical_station_count"],
        "shards":report["shards"],
        "summary":report["summary"],
        "duplicates_sha":len(report["duplicate_sha_groups"]),
        "publication_allowed":False,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
