#!/usr/bin/env python3
"""Generic read-only groupings of failed v5 radio logo sources.

No hardcoded station, genre, provider, domain or endpoint whitelist. Accepts
only an unsigned, previously SHA-audited UUID queue and the exact historical
radio inventory. Does not retry a single network URL, sign, remove or publish.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
from urllib.parse import urlsplit

from audit_open_radio_artwork_inventory import validate_inventory


class UnverifiedSourceError(ValueError):
    pass


def _require(ok: bool, message: str) -> None:
    if not ok:
        raise UnverifiedSourceError(message)


def group_unverified_sources(queue: dict, inventory: dict) -> dict:
    _require(queue.get("scope") == "GO_ARTWORK_V5_EDITORIAL_TRIAGE_ONLY"
             and queue.get("publication_allowed") is False
             and queue.get("signed_catalog_created") is False
             and queue.get("discovery_is_open") is True,
             "Only unsigned SHA triage reports allowed")
    historical = validate_inventory(inventory)
    inventory_by_id = {x["legacy_media_id"]: x for x in historical}
    _require(len(inventory_by_id) == len(historical),
             "Duplicate historical identities")

    associations = queue.get("historical_associations")
    _require(isinstance(associations, list),
             "Missing v5 historical associations")
    by_id = {}
    groups = defaultdict(list)
    for row in associations:
        sid = row.get("legacy_media_id")
        _require(isinstance(sid, str) and sid in inventory_by_id
                 and sid not in by_id,
                 "Unknown or duplicated UUID in source evidence")
        _require(row.get("publication_allowed") is False
                 and row.get("replace_existing_logo") is False
                 and row.get("station_name") ==
                 inventory_by_id[sid]["display_name"],
                 "Suspicious signed/renamed historical radio record")
        url = row.get("source_url")
        _require(isinstance(url, str) and urlsplit(url).scheme == "https"
                 and bool(urlsplit(url).hostname),
                 "Missing or non-HTTPS v5 image source")
        by_id[sid] = row
        if row.get("probe_verified") is True:
            continue
        domain = urlsplit(url).hostname.lower()
        previous = inventory_by_id[sid]["source_logo_url"]
        groups[domain].append({
            "legacy_media_id": sid,
            "station_name": row["station_name"],
            "candidate_url": url,
            "reason": row.get("probe_failure") or "UNCLASSIFIED_TECHNICAL_FAILURE",
            "legacy_v64_has_logo_url": bool(previous),
            "legacy_v64_logo_url_preserved": previous,
            "legacy_v64_homepage": inventory_by_id[sid].get("homepage", ""),
            "remove_station": False,
            "remove_existing_logo": False,
            "publication_allowed": False,
        })
    _require(queue.get("summary", {}).get("historical_manifest_associations")
             == len(by_id),
             "Incorrect count of associations")

    grouped = []
    for host, records in groups.items():
        ordered = sorted(records, key=lambda x:
                         (x["station_name"].casefold(), x["legacy_media_id"]))
        unique = {x["candidate_url"] for x in ordered}
        grouped.append({
            "image_source_host": host,
            "historical_radio_count": len(ordered),
            "distinct_failed_image_urls": len(unique),
            "no_historical_logo_url": sum(
                not x["legacy_v64_has_logo_url"] for x in ordered),
            "historical_logo_url_retained": sum(
                x["legacy_v64_has_logo_url"] for x in ordered),
            "failure_reason_counts": dict(sorted(Counter(
                x["reason"] for x in {u: next(
                    r for r in ordered if r["candidate_url"]==u)
                    for u in sorted(unique)}.values()).items())),
            "records": ordered,
            "publication_allowed": False,
            "remove_any_radio": False,
        })
    grouped.sort(key=lambda x: (-x["historical_radio_count"],
                                -x["distinct_failed_image_urls"],
                                x["image_source_host"]))

    missing = defaultdict(list)
    for sid, original in inventory_by_id.items():
        if sid in by_id:
            continue
        page = original.get("homepage", "")
        hostname = urlsplit(page).hostname or "(homepage missing)"
        missing[hostname.lower()].append({
            "legacy_media_id": sid,
            "station_name": original["display_name"],
            "legacy_v64_logo_url_preserved": original["source_logo_url"],
            "legacy_v64_homepage": page,
            "publication_allowed": False,
        })
    missing_groups = [{
        "historical_homepage_host": domain,
        "count": len(items),
        "records": sorted(items, key=lambda a:a["legacy_media_id"]),
    } for domain, items in sorted(missing.items(),
                                  key=lambda x:(-len(x[1]),x[0]))]

    count_failed = sum(g["historical_radio_count"] for g in grouped)
    _require(count_failed + sum(r.get("probe_verified") is True
                               for r in associations) == len(associations),
             "Failed/successful source partition incomplete")
    return {
        "schema_version": 1,
        "scope": "GO_OPEN_V5_LOGO_SOURCE_FAILURE_GROUPS_REVIEW_ONLY",
        "source_manifest_version": queue["source_manifest_version"],
        "discovery_is_open": True,
        "publication_allowed": False,
        "signed_catalog_created": False,
        "summary": {
            "historical_radio_count": len(historical),
            "with_public_manifest_association": len(associations),
            "without_public_manifest_association": len(historical)-len(by_id),
            "failed_historical_associations": count_failed,
            "failed_source_hosts": len(grouped),
            "failed_distinct_urls": sum(
                g["distinct_failed_image_urls"] for g in grouped),
        },
        "failed_source_groups": grouped,
        "historical_without_manifest_by_homepage_host": missing_groups,
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--review", type=Path, required=True)
    p.add_argument("--inventory", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    q = json.loads(args.review.read_text(encoding="utf-8"))
    i = json.loads(args.inventory.read_text(encoding="utf-8"))
    result = group_unverified_sources(q, i)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,sort_keys=True,
                           ensure_ascii=False,indent=2)+"\n",
                           encoding="utf-8")
    print(json.dumps({"status":"GO_OPEN_PROVIDER_FAILURES_ONLY",
                      **result["summary"],
                      "top_failed_hosts":[
                          {"host":g["image_source_host"],
                           "radios":g["historical_radio_count"],
                           "urls":g["distinct_failed_image_urls"]}
                          for g in result["failed_source_groups"][:5]],
                      "publication_allowed":False},ensure_ascii=False))


if __name__=="__main__":
    main()
