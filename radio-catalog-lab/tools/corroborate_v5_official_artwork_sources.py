#!/usr/bin/env python3
"""Independent first-party corroboration of SHA-checked v5 logo candidates.

Read-only. The existing logo bytes are *not* downloaded here. A channel's
homepage may embed generic images, so even matching metadata or a provider's
official API is evidence for a reviewer, NEVER editorial approval or authority
to sign artwork. No station/domain/genre allowlist.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from audit_open_radio_artwork_inventory import (
    discover_official_page, public_https, upgraded_https_homepage,
    validate_inventory,
)
from discover_official_laut_fm_logos import extract_slug, fetch_official

SCOPE = "GO_ARTWORK_V5_EDITORIAL_TRIAGE_ONLY"
PROVENANCE_SCOPE = "GO_V5_OFFICIAL_SOURCE_CORROBORATION_REVIEW_ONLY"
SHA = re.compile(r"^[a-f0-9]{64}$")


class CorroborationError(ValueError):
    pass


def require(ok: bool, message: str) -> None:
    if not ok:
        raise CorroborationError(message)


def same_asset_path(first: str, second: str) -> bool:
    """Match only exact HTTPS host + resource path, ignoring cache query.

    A match is a *hint*, NOT a proof that URLs with different query parameters
    produce identical bytes. The prior byte SHA remains the sole byte evidence.
    """
    if not public_https(first) or not public_https(second):
        return False
    a, b = urlsplit(first), urlsplit(second)
    return ((a.hostname or "").lower() == (b.hostname or "").lower()
            and a.path == b.path and bool(a.path))


def _classify(row: dict, homepage: str, network: bool,
              page_reader, api_reader) -> dict:
    result = {
        "legacy_media_id": row["legacy_media_id"],
        "station_name": row["station_name"],
        "candidate_url": row["source_url"],
        "candidate_sha256": row["sha256"],
        "candidate_width": row["width"],
        "candidate_height": row["height"],
        "homepage_as_historical": homepage,
        "homepage_https_candidate": upgraded_https_homepage(homepage),
        "identity_visual_approved": False,
        "publication_allowed": False,
        "replace_existing_logo": False,
        "source_status": "UNTESTED_NO_NETWORK",
        "source_evidence": [],
    }
    if not network:
        return result

    if result["homepage_https_candidate"] is None:
        result["source_status"] = "HISTORICAL_HOMEPAGE_UNSAFE_OR_MISSING"
        return result

    slug = extract_slug(homepage)
    if slug is not None:
        # API checks *exact* slug, canonical page and official stream, not names
        # or a curated list. The returned asset path is independently compared.
        try:
            info = api_reader(slug)
            url = info["official_image"]
            matched = same_asset_path(url, row["source_url"])
            result["source_status"] = (
                "OFFICIAL_API_EXACT_ASSET_PATH" if matched
                else "OFFICIAL_API_DIFFERENT_ASSET_PATH")
            result["source_evidence"].append({
                "kind": "laut_fm_exact_station_slug_api",
                "station_slug": slug,
                "official_station_page": info["official_page"],
                "official_image_url": url,
                "source_path_matches_candidate": matched,
                "query_may_affect_bytes": True,
            })
        except Exception as error:
            result["source_status"] = "OFFICIAL_API_UNAVAILABLE"
            result["error_type"] = type(error).__name__
        return result

    try:
        checked = page_reader(homepage)
        # A fetched homepage's metadata is just an untrusted site claim.
        images = checked.get("image_candidates", [])
        if not isinstance(images, list):
            raise CorroborationError("Malformed official homepage evidence")
        metadata_matches = [
            {"image_url": item["url"], "source_meta": item["source_meta"]}
            for item in images
            if isinstance(item, dict) and isinstance(item.get("url"), str)
            and same_asset_path(item["url"], row["source_url"])
        ]
        homepage_host = urlsplit(result["homepage_https_candidate"]).hostname
        candidate_host = urlsplit(row["source_url"]).hostname
        same_host = homepage_host == candidate_host
        result["source_evidence"].append({
            "kind": "historical_homepage_metadata",
            "homepage_probe_state": checked.get("reason"),
            "exact_asset_path_matches": metadata_matches[:8],
            "same_exact_hostname_as_homepage": same_host,
            "total_homepage_metadata_images": len(images),
        })
        result["source_status"] = (
            "HOMEPAGE_METADATA_ASSET_PATH_MATCH"
            if metadata_matches else
            "SAME_HOST_ONLY_NO_METADATA_MATCH" if same_host
            else "NO_FIRST_PARTY_IMAGE_CORROBORATION")
        if checked.get("reason") not in (
                "homepage_metadata_candidates_not_approved",
                "homepage_no_image_metadata"):
            result["source_status"] = "HOMEPAGE_UNAVAILABLE_OR_UNVERIFIED"
    except Exception as error:
        result["source_status"] = "HOMEPAGE_PROBE_FAILED"
        result["error_type"] = type(error).__name__
    return result


def corroborate(queue: dict, inventory: dict, *,
                shard_index: int, shard_count: int, network: bool,
                page_reader=discover_official_page,
                api_reader=fetch_official) -> dict:
    require(queue.get("scope") == SCOPE
            and queue.get("publication_allowed") is False
            and queue.get("signed_catalog_created") is False
            and queue.get("discovery_is_open") is True,
            "Source must be an unsigned open-discovery queue")
    require(type(shard_index) is int and type(shard_count) is int
            and 1 <= shard_count <= 16 and 0 <= shard_index < shard_count,
            "Invalid or excessive source scan shard")
    histories = validate_inventory(inventory)
    ids = {h["legacy_media_id"]: h for h in histories}
    queue_rows = queue.get("priority_no_initial_logo")
    require(isinstance(queue_rows, list) and len(queue_rows) <= 500,
            "Invalid priority queue")
    selected = []
    seen = set()
    for row in queue_rows:
        sid = row.get("legacy_media_id")
        require(isinstance(sid, str) and sid not in seen and sid in ids,
                "Unknown/duplicate historical UUID")
        seen.add(sid)
        entry = ids[sid]
        require(row.get("station_name") == entry["display_name"]
                and entry["source_logo_url"] == ""
                and row.get("publication_allowed") is False
                and row.get("replace_existing_logo") is False,
                "Invalid historical identity or publishability")
        if row.get("editorial_review_status") != "IDENTITY_VISUAL_REVIEW_REQUIRED":
            continue
        require(row.get("probe_verified") is True
                and isinstance(row.get("sha256"), str)
                and SHA.fullmatch(row["sha256"])
                and isinstance(row.get("source_url"), str)
                and public_https(row["source_url"]),
                "Not SHA-checked HTTPS artwork")
        # Stable allocation across newly found stations. Does not depend on a
        # fixed station set, order, provider or genre.
        shard = int(hashlib.sha256(sid.encode()).hexdigest()[:8], 16) % shard_count
        if shard == shard_index:
            selected.append((row, entry["homepage"]))
    require(not network or len(selected) <= 32,
            "Too many official sources in one bounded network shard")
    results = [
        _classify(row, homepage, network, page_reader, api_reader)
        for row, homepage in selected
    ]
    return {
        "schema_version": 1,
        "scope": PROVENANCE_SCOPE,
        "source_blob_sha": inventory["source"]["blob_sha"],
        "source_manifest_version": queue["source_manifest_version"],
        "shard_index": shard_index, "shard_count": shard_count,
        "network_enabled": network,
        "candidate_count": len(results),
        "official_api_exact_asset_path": sum(
            x["source_status"] == "OFFICIAL_API_EXACT_ASSET_PATH"
            for x in results),
        "homepage_metadata_asset_path_matches": sum(
            x["source_status"] == "HOMEPAGE_METADATA_ASSET_PATH_MATCH"
            for x in results),
        "same_host_only": sum(
            x["source_status"] == "SAME_HOST_ONLY_NO_METADATA_MATCH"
            for x in results),
        "identity_visual_approved": False,
        "publication_allowed": False,
        "signed_catalog_created": False,
        "records": results,
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--queue", type=Path, required=True)
    p.add_argument("--inventory", type=Path, required=True)
    p.add_argument("--shard-index", type=int, required=True)
    p.add_argument("--shard-count", type=int, required=True)
    p.add_argument("--network", action="store_true")
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    load = lambda file: json.loads(file.read_text(encoding="utf-8"))
    report = corroborate(load(args.queue), load(args.inventory),
                         shard_index=args.shard_index,
                         shard_count=args.shard_count,
                         network=args.network)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(
        report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "records"},
                     sort_keys=True))


if __name__ == "__main__":
    main()
