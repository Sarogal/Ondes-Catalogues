#!/usr/bin/env python3
"""Read-only triage of missing admitted radio UUIDs.

All proposed matches require editorial review. This tool never edits a catalog,
assigns a go_station_id, approves a station, or writes release files.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

UUID = re.compile(r"^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$")
POLICY = {
    "same_stream_and_name_review": ("proposed_existing_alias", "Verify station identity and ownership; approve alias separately"),
    "same_stream_different_name_review": ("ambiguous_shared_stream", "Confirm editorial identity; a common stream does not prove an alias"),
    "shared_homepage_only_no_merge": ("potentially_distinct_channel", "Keep separate unless independent station-level evidence proves otherwise"),
    "new_or_unlinked_candidate_review": ("unlinked_station_candidate", "Qualify a new station and its playback; do not auto-admit"),
    "not_found_directory_recheck": ("historical_uuid_unresolved", "Preserve UUID and recheck independent sources before any classification"),
}


def build_triage(coverage: dict, evidence: dict) -> dict:
    if not isinstance(coverage, dict) or not isinstance(evidence, dict):
        raise ValueError("coverage and evidence must be objects")
    uuids = coverage.get("missing_admissible_uuids")
    rows = evidence.get("rows")
    if not isinstance(uuids, list) or not isinstance(rows, list):
        raise ValueError("missing coverage UUIDs or evidence rows")
    if (coverage.get("ready_to_publish") is not False
            or coverage.get("coverage_gate_passed") is not False):
        raise ValueError("only blocked staging coverage can be triaged")
    if coverage.get("missing_historical_alias_count") != 0 or coverage.get("alias_collisions") != []:
        raise ValueError("baseline alias loss or collision: refuse triage")
    if len(uuids) != coverage.get("missing_admissible_uuid_count"):
        raise ValueError("coverage UUID count is inconsistent")
    if len(rows) != evidence.get("total_uuid_reviewed"):
        raise ValueError("evidence UUID count is inconsistent")
    if len(set(uuids)) != len(uuids) or any(not isinstance(u, str) or not UUID.fullmatch(u) for u in uuids):
        raise ValueError("invalid or duplicated UUID in coverage")
    seen = set()
    output = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("invalid evidence row")
        ident = row.get("uuid")
        if not isinstance(ident, str) or not UUID.fullmatch(ident) or ident in seen:
            raise ValueError("invalid or duplicate evidence UUID")
        seen.add(ident)
        category = row.get("classification")
        if category not in POLICY:
            raise ValueError(f"unknown review classification for {ident}")
        if (row.get("approval") != "HUMAN_REVIEW_REQUIRED"
                or row.get("auto_admit") is not False
                or row.get("auto_merge") is not False
                or row.get("delete_previous_alias") is not False):
            raise ValueError(f"unsafe editorial state for {ident}")
        matches = row.get("exact_stream_matches")
        if not isinstance(matches, list):
            raise ValueError(f"invalid matching records for {ident}")
        if category in ("same_stream_and_name_review", "same_stream_different_name_review") and not matches:
            raise ValueError(f"missing direct stream evidence for {ident}")
        if category == "same_stream_and_name_review" and not row.get("exact_name_matches"):
            raise ValueError(f"missing matching name for {ident}")
        if category == "not_found_directory_recheck" and row.get("directory_found") is not False:
            raise ValueError(f"directory absence not proven for {ident}")
        if category != "not_found_directory_recheck" and row.get("directory_found") is not True:
            raise ValueError(f"directory record missing for {ident}")
        mapped = []
        for match in matches:
            if not isinstance(match, dict) or not isinstance(match.get("go_station_id"), str):
                raise ValueError(f"invalid existing station match for {ident}")
            mapped.append(match["go_station_id"])
        if len(set(mapped)) != len(mapped):
            raise ValueError(f"duplicate existing station matches for {ident}")
        review_type, next_step = POLICY[category]
        output.append({
            "uuid": ident,
            "directory_name": row.get("directory_name"),
            "classification": category,
            "review_type": review_type,
            "possible_existing_go_station_ids": mapped,
            "punk_pilot_code_name": (row.get("punk_pilot_evidence") or {}).get("code_name"),
            "next_step": next_step,
            "review_status": "PENDING_HUMAN_REVIEW",
            "catalog_change_authorized": False,
        })
    if seen != set(uuids):
        raise ValueError("coverage and evidence UUID sets differ")
    counts = dict(sorted(Counter(r["classification"] for r in output).items()))
    if counts != evidence.get("classification_counts"):
        raise ValueError("evidence classification totals disagree")
    return {
        "status": "TRIAGE_ONLY_BLOCK_RELEASE",
        "total_missing_uuids": len(output),
        "classification_counts": counts,
        "catalog_change_authorized": False,
        "coverage_gate_passed": False,
        "ready_to_publish": False,
        "note": "UUID counts are not station counts. Suggestions are not merger approvals.",
        "rows": sorted(output, key=lambda r: r["uuid"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coverage", required=True, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("refusing to overwrite an existing triage file")
    result = build_triage(
        json.loads(args.coverage.read_text(encoding="utf-8")),
        json.loads(args.evidence.read_text(encoding="utf-8")),
    )
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "uuid_count": result["total_missing_uuids"],
                      "categories": result["classification_counts"]}))


if __name__ == "__main__":
    main()
