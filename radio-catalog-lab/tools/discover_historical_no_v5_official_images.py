#!/usr/bin/env python3
"""Open discovery of official logo evidence for historical stations missing v5.

Only public HTTPS official page metadata and exact first-party laut.fm API
identity are collected. No images are downloaded, no signed artwork produced,
and no radio/genre/domain/UUID allowlist is used. Legacy V64 logos and URLs
are retained byte-for-byte for rollback and editorial review.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from audit_open_radio_artwork_inventory import (
    discover_official_page, upgraded_https_homepage, validate_inventory,
)
from discover_official_laut_fm_logos import extract_slug, fetch_official

QUEUE_SCOPE = "GO_ARTWORK_V5_EDITORIAL_TRIAGE_ONLY"
REPORT_SCOPE = "GO_HISTORICAL_NO_V5_OFFICIAL_LOGO_DISCOVERY_REVIEW_ONLY"


class NoV5DiscoveryError(ValueError):
    pass


def require(check: bool, message: str) -> None:
    if not check:
        raise NoV5DiscoveryError(message)


def discover(queue: dict, inventory: dict, *,
             shard_index: int, shard_count: int, network: bool,
             page_reader=discover_official_page,
             api_reader=fetch_official) -> dict:
    require(queue.get("scope") == QUEUE_SCOPE
            and queue.get("discovery_is_open") is True
            and queue.get("publication_allowed") is False
            and queue.get("signed_catalog_created") is False,
            "Only unsigned v5 queue is eligible")
    require(type(shard_index) is int and type(shard_count) is int
            and 1 <= shard_count <= 16 and 0 <= shard_index < shard_count,
            "Invalid bounded shard")
    historical = validate_inventory(inventory)
    active = queue.get("historical_associations")
    require(isinstance(active, list), "Missing historical manifest associations")
    known_ids = {x["legacy_media_id"] for x in historical}
    associated_ids = set()
    for row in active:
        sid = row.get("legacy_media_id")
        require(isinstance(sid, str) and sid in known_ids
                and sid not in associated_ids
                and row.get("publication_allowed") is False,
                "Unknown, duplicated or publishable historical v5 association")
        associated_ids.add(sid)
    missing = [s for s in historical
               if s["legacy_media_id"] not in associated_ids]
    require(len(missing) > 0 and len(missing) <= 20000
            and len(historical) - len(active) == len(missing),
            "Invalid absent-association partition")
    # Stable sharding independent of the historical ordering and any provider
    # manifest. Newly discovered stations can join the process next run.
    selected = [s for s in missing
                if int(hashlib.sha256(s["legacy_media_id"].encode("ascii"))
                       .hexdigest()[:8],16) % shard_count == shard_index]
    require(not network or len(selected) <= 40,
            "Excessive per-run page requests")
    cache = {}
    records = []
    for item in selected:
        sid = item["legacy_media_id"]
        homepage = item.get("homepage", "")
        record = {
            "legacy_media_id":sid,
            "station_name":item["display_name"],
            "historical_homepage":homepage,
            "historical_logo_url_preserved":item["source_logo_url"],
            "had_historical_logo":bool(item["source_logo_url"]),
            "image_candidates":[],
            "identity_visual_approved":False,
            "replace_existing_logo":False,
            "publication_allowed":False,
            "discovery_status":"OFFLINE_NOT_REQUESTED" if not network
                               else "UNKNOWN",
        }
        if not network:
            records.append(record)
            continue
        slug = extract_slug(homepage)
        if slug is not None:
            if ("api",slug) not in cache:
                try:
                    cache[("api",slug)] = ("ok",api_reader(slug))
                except Exception as exc:
                    cache[("api",slug)] = ("error",type(exc).__name__)
            status, detail = cache[("api",slug)]
            if status == "ok":
                require(detail.get("station_slug") == slug
                        and detail.get("official_page") ==
                        "https://laut.fm/"+slug,
                        "Official API station mismatch")
                record["discovery_status"] = "FIRST_PARTY_STATION_API_IMAGE"
                record["official_source_url"] = detail["official_source"]
                record["image_candidates"] = [{
                    "url":detail["official_image"],
                    "source_meta":"laut_fm_verified_station_slug",
                    "identity_by_exact_station_slug":True,
                    "verified_image_bytes":False,
                    "identity_visual_approved":False,
                    "publication_allowed":False,
                }]
            else:
                record["discovery_status"] = "FIRST_PARTY_API_FAILED"
                record["error_type"] = detail
            records.append(record)
            continue

        upgraded = upgraded_https_homepage(homepage)
        if upgraded is None:
            record["discovery_status"] = "UNSAFE_OR_MISSING_HTTPS_HOMEPAGE"
            records.append(record)
            continue
        if upgraded not in cache:
            try:
                cache[upgraded] = ("ok",page_reader(homepage))
            except Exception as exc:
                cache[upgraded] = ("error",type(exc).__name__)
        status, detail = cache[upgraded]
        if status == "error":
            record["discovery_status"] = "HOMEPAGE_DISCOVERY_FAILED"
            record["error_type"] = detail
        else:
            images = detail.get("image_candidates", [])
            require(detail.get("publication_allowed") is False
                    and detail.get("logo_approved") is False
                    and isinstance(images,list) and len(images) <= 8,
                    "Homepage attempted approval or unlimited candidates")
            record["discovery_status"] = (
                "OFFICIAL_HOMEPAGE_METADATA_UNREVIEWED"
                if images else "OFFICIAL_HOMEPAGE_NO_IMAGE_OR_UNAVAILABLE"
            )
            record["homepage_discovery_reason"] = detail.get("reason")
            record["image_candidates"] = [{
                "url":c["url"],
                "source_meta":c["source_meta"],
                "identity_by_exact_station_slug":False,
                "verified_image_bytes":False,
                "identity_visual_approved":False,
                "publication_allowed":False,
            } for c in images]
        records.append(record)

    return {
        "schema_version":1,
        "scope":REPORT_SCOPE,
        "source_manifest_version":queue["source_manifest_version"],
        "historical_total":len(historical),
        "historical_with_v5":len(active),
        "historical_without_v5":len(missing),
        "shard_index":shard_index,
        "shard_count":shard_count,
        "selected":len(records),
        "network":network,
        "candidate_image_refs":sum(len(r["image_candidates"]) for r in records),
        "with_image_candidates":sum(bool(r["image_candidates"]) for r in records),
        "identity_visual_approved":False,
        "publication_allowed":False,
        "signed_catalog_created":False,
        "records":records,
    }


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue",type=Path,required=True)
    parser.add_argument("--inventory",type=Path,required=True)
    parser.add_argument("--shard-index",type=int,required=True)
    parser.add_argument("--shard-count",type=int,required=True)
    parser.add_argument("--network",action="store_true")
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    load=lambda f:json.loads(f.read_text(encoding="utf-8"))
    report=discover(load(args.queue),load(args.inventory),
                    shard_index=args.shard_index,
                    shard_count=args.shard_count,network=args.network)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(
        report,ensure_ascii=False,sort_keys=True,indent=2)+"\n",
        encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k!="records"},
                     ensure_ascii=False))


if __name__=="__main__":
    main()
