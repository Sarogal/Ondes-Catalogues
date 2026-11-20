#!/usr/bin/env python3
"""Read-only central-catalog reconciliation of Radio Browser discovery results.

Requires a supplied catalog snapshot. The result is a review report, NEVER an
admission, approval, deleted station, new signed release or publication.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
import uuid
from pathlib import Path
from urllib.parse import urlsplit

MAX_INPUT_BYTES = 25_000_000


def normalized_name(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text.lower())).strip()


def checked_uuid(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Station identifier not a UUID")
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError) as error:
        raise ValueError("Invalid station UUID") from error


def load_json(path: Path) -> object:
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError("Input document exceeds size limit")
    return json.loads(path.read_text(encoding="utf-8"))


def _ids(record: dict) -> list[str]:
    ids = []
    for item in record.get("legacy_aliases", []):
        ids.append(checked_uuid(item))
    for item in record.get("radio_browser_uuids", []):
        ids.append(checked_uuid(item["uuid"] if isinstance(item, dict) else item))
    return ids


def index_catalog(catalog: dict) -> tuple[dict[str, str], dict[tuple[str, str], set[str]], dict[str, set[str]]]:
    if not isinstance(catalog, dict) or catalog.get("schema_version") != 1:
        raise ValueError("Expected v1 signed-catalog compatible schema")
    stations = catalog.get("stations")
    tombstones = catalog.get("tombstones", [])
    if not isinstance(stations, list) or not isinstance(tombstones, list):
        raise ValueError("Invalid central catalog shape")
    owners: dict[str, str] = {}
    by_name: dict[tuple[str, str], set[str]] = {}
    by_url: dict[str, set[str]] = {}
    for station in stations:
        if not isinstance(station, dict):
            raise ValueError("Invalid central station")
        go_id = station.get("go_station_id")
        if not isinstance(go_id, str) or not go_id:
            raise ValueError("Missing GO identity")
        for uid in _ids(station):
            previous = owners.setdefault(uid, go_id)
            if previous != go_id:
                raise ValueError("Conflicting UUID ownership in central catalog")
        name = normalized_name(station.get("display_name"))
        country = str(station.get("country_code") or "").strip().upper()
        if name:
            by_name.setdefault((name, country), set()).add(go_id)
        streams = station.get("streams", [])
        if not isinstance(streams, list):
            raise ValueError("Invalid stream list")
        for stream in streams:
            if isinstance(stream, dict):
                url = stream.get("url")
                if isinstance(url, str) and url.strip():
                    by_url.setdefault(url.strip(), set()).add(go_id)
    for tombstone in tombstones:
        if not isinstance(tombstone, dict):
            raise ValueError("Invalid tombstone")
        go_id = tombstone.get("go_station_id")
        if not isinstance(go_id, str) or not go_id:
            raise ValueError("Invalid tombstone GO id")
        for uid in _ids(tombstone):
            prior = owners.setdefault(uid, go_id)
            if prior != go_id:
                raise ValueError("Conflicting tombstone UUID ownership")
    return owners, by_name, by_url


def review_candidates(catalog: dict, discovery: dict,
                      extra_known_ids: set[str] | None = None) -> dict:
    owners, by_name, by_url = index_catalog(catalog)
    if not isinstance(discovery, dict) or discovery.get("schemaVersion") != 1 or (
        discovery.get("publicationAllowed") is not False
    ) or not isinstance(discovery.get("candidates"), list):
        raise ValueError("Candidate source is not a non-publishing discovery report")
    rows = []
    seen: set[str] = set()
    extra_known = extra_known_ids or set()
    for item in discovery["candidates"]:
        if not isinstance(item, dict):
            raise ValueError("Invalid candidate row")
        uid = checked_uuid(item.get("stationuuid"))
        if uid in seen:
            raise ValueError("Duplicate candidate UUID")
        seen.add(uid)
        name = str(item.get("name") or "").strip()
        country = str(item.get("countrycode") or "").strip().upper()
        status = item.get("status")
        if status not in {
            "candidate_requires_qualification", "needs_stream_check",
            "needs_duplicate_review",
        }:
            raise ValueError("Unrecognized candidate state")
        if not name:
            raise ValueError("Empty candidate name")
        owner = owners.get(uid)
        by_staged_name = sorted(by_name.get((normalized_name(name), country), ()))
        stream = item.get("streamUrl")
        by_staged_url = sorted(by_url.get(stream.strip(), ())) if isinstance(stream, str) else []
        if owner:
            classification = "already_mapped"
        elif uid in extra_known:
            classification = "known_legacy_not_yet_mapped"
        elif by_staged_url or by_staged_name or item.get("duplicateIdentityRisk"):
            classification = "possible_variant_or_duplicate"
        else:
            classification = "unmapped_candidate"
        rows.append({
            "stationuuid": uid,
            "name": name[:240],
            "classification": classification,
            "existingGoStationId": owner,
            "possibleGoStationIds": sorted(set(by_staged_name + by_staged_url)),
            "candidateStatus": status,
            "technicalVerificationNeeded": not bool(owner),
        })
    counts = {kind: sum(x["classification"] == kind for x in rows)
              for kind in (
                  "already_mapped", "known_legacy_not_yet_mapped",
                  "possible_variant_or_duplicate", "unmapped_candidate"
              )}
    return {
        "schemaVersion": 1,
        "scanDate": discovery.get("scanDate"),
        "catalogRecordCount": len(catalog["stations"]),
        "observedCandidateCount": len(rows),
        "counts": counts,
        "automaticAdmissionAllowed": False,
        "catalogChanged": False,
        "requiresCompleteDeviceBaselineForRelease": True,
        "candidates": sorted(rows, key=lambda row: row["stationuuid"]),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--discovery", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--legacy-ids", type=Path)
    args = parser.parse_args(argv)
    extra: set[str] = set()
    if args.legacy_ids:
        payload = load_json(args.legacy_ids)
        if not isinstance(payload, list):
            raise ValueError("Legacy ID supplement must be a JSON list")
        extra = {checked_uuid(x) for x in payload}
    report = review_candidates(load_json(args.catalog), load_json(args.discovery), extra)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                           encoding="utf-8")
    print("CENTRAL_RADIO_CANDIDATE_RECONCILIATION"
          f" observed={report['observedCandidateCount']}"
          f" catalog_stations={report['catalogRecordCount']}"
          f" classifications={report['counts']} published=false")
    return 0


if __name__ == "__main__":
    sys.exit(main())
