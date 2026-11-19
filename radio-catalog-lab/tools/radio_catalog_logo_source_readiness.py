#!/usr/bin/env python3
"""Read-only, offline inventory of REAL logo sources before any SHA migration.

Input is the historical UNVERIFIED staging catalog and V64 logo reuse map,
NOT a signed production catalog. No network, no image download, no approval,
no writes unless --out is supplied; existing outputs are never overwritten.

This is a source-selection and qualification queue, NOT a publication gate.
An HTTPS URL, a historical manifest byte length or an alleged SHA is not
proof that the artwork is official or matches the current remote bytes.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

GO_ID = re.compile(r"^go-station-[0-9]{6,}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
DIRECT_SUFFIX = re.compile(r"\.(png|jpe?g|webp)(?:$|[?#])", re.I)
FAVICON = re.compile(r"(?:favicon|apple-touch-icon|/icon\.(?:ico|png))", re.I)
BLOCKED_DOMAIN = ("radcap.ru",)
KNOWN_STATES = {"active", "quarantined", "retired"}


def _safe_https_source(url: str) -> bool:
    """Only classify a URL as a potential direct fetch, NEVER as approved."""
    if not isinstance(url, str) or any(ord(c) < 32 for c in url):
        return False
    try:
        u = urlsplit(url)
        if (u.scheme != "https" or not u.hostname or u.username or u.password
                or u.fragment or u.port not in (None, 443)
                or not u.netloc.endswith(u.hostname)):
            return False
        host = u.hostname.lower()
        if (host in {"localhost", "localhost.localdomain"}
                or host.endswith((".local", ".localhost"))):
            return False
        if any(host == d or host.endswith("." + d) for d in BLOCKED_DOMAIN):
            return False
        try:
            ipaddress.ip_address(host.strip("[]"))
        except ValueError:
            pass
        else:
            return False
        return True
    except (ValueError, TypeError):
        return False


def _categorize(urls: list[str]) -> tuple[str, list[str], list[str]]:
    """Return safe fetch candidates, manual-review sources and a reason code."""
    https = sorted({u for u in urls if _safe_https_source(u)})
    direct = [u for u in https if DIRECT_SUFFIX.search(urlsplit(u).path)
              and not FAVICON.search(urlsplit(u).path)]
    others = sorted(set(urls) - set(direct))
    if direct:
        return "https_image_candidate", direct, others
    if https:
        return "https_manual_review", [], others
    if urls:
        return "unsafe_or_http_only", [], others
    return "no_source", [], []


def inspect_source_readiness(
    staging: dict, reuse_map: dict, coverage: dict,
) -> dict:
    """Fail closed on inconsistent cross-file station identity or UUID counts."""
    if not isinstance(staging, dict) or not isinstance(reuse_map, dict) or not isinstance(coverage, dict):
        raise ValueError("Inputs must be JSON objects")
    stations = staging.get("stations")
    rows = reuse_map.get("station_logos")
    if (staging.get("schema_version") != 1 or
            reuse_map.get("schema_version") != 1 or
            not isinstance(stations, list) or not stations or
            not isinstance(rows, list) or not isinstance(coverage.get("missing_admissible_uuids"), list)):
        raise ValueError("Missing or invalid staging/reuse/coverage contract")
    if coverage.get("source_stage_file") and not str(coverage["source_stage_file"]).endswith(
        "bootstrap-stations-20261115.json"
    ):
        # Refuse stale reports referencing another staging snapshot.
        raise ValueError("Coverage references unexpected staging source")
    missing = coverage["missing_admissible_uuids"]
    if (len(missing) != coverage.get("missing_admissible_uuid_count") or
            len(set(missing)) != len(missing) or
            coverage.get("ready_to_publish") is not False or
            coverage.get("coverage_gate_passed") is not False):
        raise ValueError("Coverage preflight is missing or not the blocked baseline")

    station_by_id = {}
    for station in stations:
        if not isinstance(station, dict):
            raise ValueError("Invalid staging station")
        go_id = station.get("go_station_id")
        if not isinstance(go_id, str) or not GO_ID.fullmatch(go_id) or go_id in station_by_id:
            raise ValueError("Duplicate/invalid GO station identity")
        status = station.get("status")
        if not isinstance(status, dict) or status.get("state") not in KNOWN_STATES:
            raise ValueError("Invalid station status")
        station_by_id[go_id] = station

    map_by_id = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Invalid logo reuse record")
        go_id = row.get("go_station_id")
        if not isinstance(go_id, str) or go_id in map_by_id:
            raise ValueError("Invalid or duplicate logo reuse identity")
        aliases = row.get("legacy_station_ids")
        urls = row.get("logo_source_urls")
        if (not isinstance(aliases, list) or not isinstance(urls, list)
                or any(not isinstance(a, str) or not a for a in aliases)
                or any(not isinstance(u, str) or not u for u in urls)):
            raise ValueError("Malformed legacy logo source list")
        map_by_id[go_id] = row
    if set(map_by_id) != set(station_by_id):
        raise ValueError("Legacy source map does not cover exactly the staged GO IDs")

    results = []
    source_count = Counter()
    active_count = 0
    with_catalog_logo = 0
    candidate_direct = 0
    for go_id, station in sorted(station_by_id.items()):
        row = map_by_id[go_id]
        if not set(row["legacy_station_ids"]).issubset(set(station.get("legacy_aliases", []))):
            raise ValueError("Logo source map has foreign station alias: " + go_id)
        status = station["status"]["state"]
        source_urls = sorted(set(row["logo_source_urls"]))
        category, direct, manual = _categorize(source_urls)
        if status != "active":
            category, direct, manual = "inactive_excluded", [], source_urls
        else:
            active_count += 1
        stage_logo = station.get("logo")
        if stage_logo is not None:
            if not isinstance(stage_logo, dict):
                raise ValueError("Malformed staged logo descriptor")
            digest = stage_logo.get("sha256")
            if not isinstance(digest, str) or not SHA256.fullmatch(digest):
                raise ValueError("Malformed staged logo SHA-256")
            with_catalog_logo += 1
        if direct:
            candidate_direct += 1
        source_count[category] += 1
        streams = station.get("streams")
        if not isinstance(streams, list):
            raise ValueError("Malformed station streams")
        verified_streams = sum(
            1 for stream in streams
            if isinstance(stream, dict) and stream.get("state") == "verified"
        )
        if any(not isinstance(stream, dict) for stream in streams):
            raise ValueError("Malformed stream record")
        editorial = station.get("editorial")
        if not isinstance(editorial, dict):
            raise ValueError("Missing editorial state")
        results.append({
            "go_station_id": go_id,
            "display_name": station.get("display_name"),
            "state": status,
            "source_category": category,
            "candidate_https_image_urls": direct,
            "manual_review_urls": manual,
            "historical_manifest_revision_only": row.get("manifest_revisions", []),
            "staged_logo_metadata_present_not_verified": stage_logo is not None,
            "verified_stream_count": verified_streams,
            "editorial_state": editorial.get("admission_state"),
            "requires_independent_artwork_identity_and_byte_sha_review": True,
            "automatic_admission": False,
        })

    verified_stream_count = sum(x["verified_stream_count"] for x in results)
    return {
        "status": "READ_ONLY_LOGO_SOURCES_NOT_APPROVED",
        "catalog_id": staging.get("catalog_id"),
        "source_sequence": staging.get("release_sequence"),
        "staged_station_count": len(stations),
        "active_station_count": active_count,
        "stations_with_any_historical_source": sum(
            bool(row["logo_source_urls"]) for row in rows
        ),
        "direct_https_image_candidate_station_count": candidate_direct,
        "candidate_classes": dict(sorted(source_count.items())),
        "staged_logo_metadata_not_cryptographically_rechecked": with_catalog_logo,
        "verified_stream_count": verified_stream_count,
        "unresolved_admissible_uuid_count": len(missing),
        "unresolved_admissible_uuids": sorted(missing),
        "ready_to_publish": False,
        "auto_downloaded_count": 0,
        "publish_action_performed": False,
        "note": (
            "No source image bytes, station ownership, editorial approval, "
            "stream or SHA has been verified by this offline inventory. "
            "Only a future signed catalog with independently qualified "
            "image bytes can feed the persistent SHA cache."
        ),
        "stations": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staging", type=Path, required=True)
    parser.add_argument("--reuse-map", type=Path, required=True)
    parser.add_argument("--coverage", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.out is not None and args.out.exists():
        parser.error("Refusing to overwrite an existing report")
    data = inspect_source_readiness(
        json.loads(args.staging.read_text(encoding="utf-8")),
        json.loads(args.reuse_map.read_text(encoding="utf-8")),
        json.loads(args.coverage.read_text(encoding="utf-8")),
    )
    if args.out:
        args.out.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
    summary = {k: v for k, v in data.items()
               if k not in ("stations", "unresolved_admissible_uuids")}
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
