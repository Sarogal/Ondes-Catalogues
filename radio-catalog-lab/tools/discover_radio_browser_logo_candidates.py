#!/usr/bin/env python3
"""Read-only Radio Browser UUID artwork candidates for an OPEN-ended catalog.

All station UUIDs are read from the supplied inventory, not from an allowlist.
Searches official Radio Browser API by UUID, never replaces a logo by name,
never downloads an HTTP image, never signs or publishes artwork. The returned
favicon is evidence requiring independent image/identity verification.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError

from audit_open_radio_artwork_inventory import (
    InventoryError, _request, public_https, validate_inventory,
)

UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
API = "https://all.api.radio-browser.info/json/stations/byuuid"
MAX_JSON = 1024 * 1024


def safe_uuid_records(rows: list, requested: set[str]) -> dict[str, dict]:
    if not isinstance(rows, list):
        raise InventoryError("Malformed Radio Browser response")
    answer: dict[str, dict] = {}
    for item in rows:
        if not isinstance(item, dict):
            raise InventoryError("Malformed Radio Browser station")
        id_ = str(item.get("stationuuid", "")).lower()
        if id_ not in requested or id_ in answer:
            raise InventoryError("Unexpected/mismatched/duplicate UUID from Radio Browser")
        favicon = item.get("favicon", "")
        if not isinstance(favicon, str) or len(favicon) > 2048:
            raise InventoryError("Malformed favicon from Radio Browser")
        name = item.get("name", "")
        if not isinstance(name, str) or not name.strip():
            raise InventoryError("Radio Browser name missing")
        answer[id_] = item
    return answer


def fetch_radio_browser_batch(ids: list[str]) -> dict[str, dict]:
    if not ids or len(ids) > 40 or any(not UUID.fullmatch(x) for x in ids):
        raise InventoryError("Unsafe batch of UUID lookup")
    url = API + "?" + urlencode({"uuids": ",".join(ids)})
    raw, mime, _ = _request(
        url, max_bytes=MAX_JSON,
        accept="application/json",
    )
    if mime not in {"application/json", "text/json", "text/plain", ""}:
        raise InventoryError("Radio Browser returned non-JSON response")
    return safe_uuid_records(json.loads(raw.decode("utf-8")), set(ids))


def collect(inventory: dict, *, network: bool) -> dict:
    rows = validate_inventory(inventory)
    by_uuid = {}
    for station in rows:
        id_ = station["legacy_media_id"].lower()
        if UUID.fullmatch(id_):
            by_uuid[id_] = station
    ids = sorted(by_uuid)
    results: dict[str, dict] = {}
    errors = []
    for begin in range(0, len(ids), 40):
        batch = ids[begin:begin+40]
        try:
            if network:
                results.update(fetch_radio_browser_batch(batch))
        except (InventoryError, HTTPError, URLError, TimeoutError,
                OSError, ValueError) as exc:
            errors.append({
                "batch_index": begin//40,
                "count": len(batch),
                "error_type": type(exc).__name__,
            })
    evidence = []
    for id_ in ids:
        seed = by_uuid[id_]
        answer = results.get(id_)
        raw = answer.get("favicon", "").strip() if answer else ""
        favicon = raw if public_https(raw) else None
        evidence.append({
            "legacy_media_id": seed["legacy_media_id"],
            "historical_name": seed["display_name"],
            "radio_browser_name": answer.get("name") if answer else None,
            "historical_has_logo_url": bool(seed["source_logo_url"]),
            "radio_browser_favicon": raw or None,
            "https_candidate_url": favicon,
            "source_state": (
                "candidate_not_reviewed" if favicon else
                "http_candidate_not_fetched" if raw.startswith("http://") else
                "api_has_no_favicon" if answer else
                "station_unresolved"
            ),
            "radio_browser_lastcheckok": answer.get("lastcheckok") if answer else None,
            "identity_match_by_uuid_only": bool(answer),
            "candidate_is_verified_logo": False,
            "publication_allowed": False,
        })
    return {
        "schema_version": 1,
        "scope": "RADIO_BROWSER_UUID_LOGO_DISCOVERY_NOT_PUBLICATION",
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_blob_sha": inventory["source"]["blob_sha"],
        "requested_uuid_count": len(ids),
        "resolved_uuid_count": len(results),
        "https_logo_candidates": sum(bool(e["https_candidate_url"]) for e in evidence),
        "missing_original_logos_with_https_candidate": sum(
            not e["historical_has_logo_url"] and bool(e["https_candidate_url"])
            for e in evidence),
        "batch_errors": errors,
        "publication_allowed": False,
        "records": evidence,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--inventory", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--network", action="store_true")
    args = p.parse_args()
    if args.inventory.stat().st_size > 3 * 1024 * 1024:
        raise InventoryError("Oversized inventory")
    inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
    result = collect(inventory, network=args.network)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2)+"\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status":"GO_RADIO_BROWSER_LOGO_DISCOVERY_EVIDENCE_ONLY",
        "requested":result["requested_uuid_count"],
        "resolved":result["resolved_uuid_count"],
        "https_candidates":result["https_logo_candidates"],
        "missing_with_candidates":result["missing_original_logos_with_https_candidate"],
        "batch_errors":len(result["batch_errors"]),
        "publication_allowed":False,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
