#!/usr/bin/env python3
"""Reconcile old V64 UUIDs with public logo manifests, WITHOUT publishing.

Inputs are untrusted associations, not SHA-verified objects. Identity joins
use exact historical UUIDs, never station names or a known-host whitelist.
This tool does not fetch images, alter streams, sign, or emit active catalogs.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from audit_open_radio_artwork_inventory import validate_inventory, public_https

UUID = re.compile(r"^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$", re.I)
MAX_MANIFEST_ENTRIES = 50000


class ReconciliationError(ValueError):
    pass


def validate_manifest(doc: dict) -> dict[str, dict]:
    if not isinstance(doc, dict) or type(doc.get("version")) is not int or \
            doc["version"] < 1 or doc.get("schema", 1) != 1:
        raise ReconciliationError("Unsupported unsigned logo manifest")
    entries = doc.get("entries")
    if not isinstance(entries, list) or len(entries) > MAX_MANIFEST_ENTRIES:
        raise ReconciliationError("Malformed manifest entries")
    by_id: dict[str, dict] = {}
    for row in entries:
        if not isinstance(row, dict):
            raise ReconciliationError("Malformed logo association")
        id_ = row.get("id")
        url = row.get("url")
        if not isinstance(id_, str) or not UUID.fullmatch(id_) or \
                id_ in by_id or not isinstance(url, str) or len(url) > 2048:
            raise ReconciliationError("Invalid/duplicate logo association UUID")
        for field in ("revision", "sizeBytes", "width", "height"):
            if type(row.get(field)) is not int or row[field] < 1:
                raise ReconciliationError("Malformed logo metadata")
        by_id[id_] = dict(row)
    return by_id


def _candidate(url: str, evidence_source: str, metadata: dict | None = None) -> dict:
    # No source-provider whitelist: all HTTPS/public sources can be candidates.
    # Their presence here is NEVER permission to fetch or use as artwork.
    safe = public_https(url)
    return {
        "url": url,
        "evidence_source": evidence_source,
        "safe_public_https_candidate": safe,
        "requires_byte_sha_and_visual_review": True,
        "publication_allowed": False,
        "metadata": metadata,
    }


def reconcile(inventory: dict, current: dict, previous: dict | None = None) -> dict:
    historical = validate_inventory(inventory)
    live = validate_manifest(current)
    old = validate_manifest(previous) if previous is not None else {}
    by_history = {s["legacy_media_id"]: s for s in historical}
    prior_ids = set(old)
    added = sorted(set(live) - prior_ids) if previous is not None else []
    deleted = sorted(prior_ids - set(live)) if previous is not None else []
    changed = sorted(id_ for id_ in set(old) & set(live)
                     if any(old[id_][field] != live[id_][field] for field in (
                         "url", "sizeBytes", "width", "height", "revision")))
    rows = []
    historic_no_url_with_manifest = 0
    historic_with_url_and_manifest = 0
    for station in historical:
        id_ = station["legacy_media_id"]
        src = station["source_logo_url"].strip()
        manifest = live.get(id_)
        if manifest is not None and not src:
            historic_no_url_with_manifest += 1
        if manifest is not None and src:
            historic_with_url_and_manifest += 1
        candidates: list[dict] = []
        if src:
            candidates.append(_candidate(src, "legacy_v64_bootstrap"))
        if manifest:
            candidates.append(_candidate(manifest["url"], "live_public_manifest",
                                         {
                                             "manifest_version": current["version"],
                                             "revision": manifest["revision"],
                                             "reported_bytes": manifest["sizeBytes"],
                                             "reported_width": manifest["width"],
                                             "reported_height": manifest["height"],
                                         }))
        flags = []
        if manifest is None:
            flags.append("no_current_manifest_association")
        if not src:
            flags.append("bootstrap_logo_missing")
        if manifest is not None and (
                manifest["width"] < 192 or manifest["height"] < 192):
            flags.append("public_manifest_image_needs_resolution_review")
        if any(not candidate["safe_public_https_candidate"] for candidate in candidates):
            flags.append("non_public_https_url_no_download")
        rows.append({
            "legacy_media_id": id_,
            "station_name": station["display_name"],
            "station_identity": "exact_historical_uuid",
            "original_genre": station["primary_genre"],
            "candidates": candidates,
            "review_flags": flags,
            "visual_identity_approved": False,
            "immutable_sha_verified": False,
            "publication_allowed": False,
        })
    # New catalog stations are welcome; never force them into the V64 set.
    unmatched = []
    for id_ in sorted(set(live) - set(by_history)):
        association = live[id_]
        unmatched.append({
            "legacy_media_id": id_,
            "station_identity": "requires_signed_catalog_uuid_alias_join",
            "candidates": [_candidate(association["url"], "live_public_manifest",
                                      {
                                          "manifest_version": current["version"],
                                          "revision": association["revision"],
                                          "reported_bytes": association["sizeBytes"],
                                          "reported_width": association["width"],
                                          "reported_height": association["height"],
                                      })],
            "visual_identity_approved": False,
            "immutable_sha_verified": False,
            "publication_allowed": False,
        })
    return {
        "schema_version": 1,
        "scope": "GROSSES_ONDES_LEGACY_ARTWORK_RECONCILIATION_UNREVIEWED",
        "source_history_blob_sha": inventory["source"]["blob_sha"],
        "public_manifest_version": current["version"],
        "previous_manifest_version": previous["version"] if previous is not None else None,
        "discovery_is_open": True,
        "publication_allowed": False,
        "signed_catalog_created": False,
        "summary": {
            "historical_station_count": len(historical),
            "history_with_bootstrap_logo": sum(bool(s["source_logo_url"])
                                              for s in historical),
            "history_without_bootstrap_logo": sum(not s["source_logo_url"]
                                                 for s in historical),
            "public_manifest_associations": len(live),
            "public_manifest_distinct_urls": len({e["url"] for e in live.values()}),
            "history_with_public_manifest": len(set(by_history) & set(live)),
            "history_without_public_manifest": len(set(by_history) - set(live)),
            "history_missing_bootstrap_but_in_public_manifest":
                historic_no_url_with_manifest,
            "history_with_bootstrap_and_public_manifest":
                historic_with_url_and_manifest,
            "public_manifest_not_in_historical_snapshot":
                len(set(live) - set(by_history)),
            "public_manifest_under_192_on_either_axis":
                sum(e["width"] < 192 or e["height"] < 192 for e in live.values()),
            "new_public_manifest_ids_since_previous": len(added),
            "removed_public_manifest_ids_since_previous": len(deleted),
            "changed_public_manifest_ids_since_previous": len(changed),
        },
        "new_public_manifest_ids": added,
        "removed_public_manifest_ids": deleted,
        "changed_public_manifest_ids": changed,
        "historical_stations": rows,
        "unmatched_public_manifest_ids": unmatched,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--current-manifest", type=Path, required=True)
    parser.add_argument("--previous-manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
    current = json.loads(args.current_manifest.read_text(encoding="utf-8"))
    previous = (json.loads(args.previous_manifest.read_text(encoding="utf-8"))
                if args.previous_manifest else None)
    result = reconcile(inventory, current, previous)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(
        result, sort_keys=True, ensure_ascii=False, indent=2
    ) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "GO_LEGACY_ARTWORK_RECONCILED_REVIEW_ONLY",
        **result["summary"],
        "publication_allowed": False,
        "signed_catalog_created": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
