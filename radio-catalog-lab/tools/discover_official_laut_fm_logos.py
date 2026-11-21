#!/usr/bin/env python3
"""Official laut.fm station artwork discovery, READ ONLY and not publishable.

Works from arbitrary historical or future station homepage/stream URLs, not
a station or genre allowlist. Uses an exact station slug and checks returned
API identity before considering the image, then independently hashes and
decodes the image. No signing, no image upload, no media ID changes.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlsplit

from audit_open_radio_artwork_inventory import (
    InventoryError, _request, probe_image, validate_inventory,
)

API = "https://api.laut.fm/station/"
LAUT_DOMAINS = {
    "laut.fm", "www.laut.fm", "stream.laut.fm",
}
STATION_SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]{1,100}$", re.I)
MAX_JSON = 256*1024


def extract_slug(homepage: str) -> str | None:
    if not isinstance(homepage, str) or len(homepage) > 2048:
        return None
    try:
        parts = urlsplit(homepage.strip())
        if (parts.scheme not in {"http", "https"} or
                parts.hostname not in LAUT_DOMAINS or parts.username or
                parts.password or parts.fragment or parts.query or
                parts.port not in (None, 80, 443)):
            return None
        segments = [unquote(x) for x in parts.path.split("/") if x]
        if len(segments) != 1 or not STATION_SLUG.fullmatch(segments[0]):
            return None
        return segments[0].lower()
    except (TypeError, ValueError):
        return None


def validated_station_metadata(payload: dict, slug: str) -> dict:
    if not isinstance(payload, dict):
        raise InventoryError("Unexpected laut.fm response")
    actual = payload.get("name")
    if not isinstance(actual, str) or actual.lower() != slug:
        raise InventoryError("laut.fm station identity differs from request")
    if extract_slug(payload.get("page_url", "")) != slug:
        raise InventoryError("laut.fm canonical page mismatch")
    images = payload.get("images")
    if not isinstance(images, dict):
        raise InventoryError("Missing laut.fm image metadata")
    image_url = images.get("station")
    if not isinstance(image_url, str) or not image_url.startswith(
        "https://assets.laut.fm/"
    ):
        raise InventoryError("No official laut.fm station image URL")
    parts = urlsplit(image_url)
    if (parts.hostname != "assets.laut.fm" or parts.username or parts.password or
            parts.query or parts.fragment or
            not re.fullmatch(r"/[0-9a-f]{24,80}", parts.path)):
        raise InventoryError("Unexpected official image identifier")
    stream = payload.get("stream_url", "")
    if not isinstance(stream, str) or not (
        stream.startswith("https://") and
        (urlsplit(stream).hostname or "").endswith(".stream.laut.fm")
    ):
        raise InventoryError("Unexpected laut.fm stream identity")
    return {
        "station_slug": slug, "display_name": payload.get("display_name"),
        "official_page": payload["page_url"],
        "official_stream": stream,
        "official_source": API+quote(slug),
        "official_image": image_url,
        "identity_by_exact_station_slug": True,
    }


def fetch_official(slug: str) -> dict:
    if not STATION_SLUG.fullmatch(slug):
        raise InventoryError("Unsafe station slug")
    body, mime, final = _request(
        API+quote(slug), max_bytes=MAX_JSON,
        accept="application/json",
    )
    if mime not in {"application/json", "text/json", "text/plain", ""} or \
       urlsplit(final).hostname != "api.laut.fm":
        raise InventoryError("Untrusted metadata response")
    return validated_station_metadata(json.loads(body.decode("utf-8")),slug)


def collect(inventory: dict, *, network: bool) -> dict:
    records = validate_inventory(inventory)
    evidence = []
    by_slug = {}
    for station in records:
        slug = extract_slug(station.get("homepage", ""))
        if slug is None:
            continue
        entry = {
            "legacy_media_id": station["legacy_media_id"],
            "historical_name": station["display_name"],
            "historical_homepage": station["homepage"],
            "slug": slug,
            "source_had_logo": bool(station["source_logo_url"]),
            "identity_verified_from_official_api": False,
            "verified_image_bytes": False,
            "station_logo_approved": False,
            "publication_allowed": False,
        }
        if network:
            if slug not in by_slug:
                try:
                    info = fetch_official(slug)
                    checked = probe_image(info["official_image"])
                    by_slug[slug] = (info, checked, None)
                except (InventoryError, HTTPError, URLError, TimeoutError,
                        ValueError, OSError) as e:
                    by_slug[slug] = (None, None, type(e).__name__)
            info, checked, error = by_slug[slug]
            if info is not None:
                entry.update(info)
                entry["identity_verified_from_official_api"] = True
                entry["image_byte_evidence"] = checked
                entry["verified_image_bytes"] = (
                    checked.get("verified_bytes") is True
                )
                entry["reason"] = (
                    "official_slug_and_decoded_sha_unreviewed"
                    if entry["verified_image_bytes"] else
                    "official_image_unavailable_or_invalid"
                )
            else:
                entry["reason"] = error
        else:
            entry["reason"] = "offline_no_request"
        evidence.append(entry)
    return {
        "schema_version": 1,
        "scope": "OFFICIAL_LAUT_FM_ARTWORK_DISCOVERY_NOT_PUBLICATION",
        "source_blob_sha": inventory["source"]["blob_sha"],
        "candidate_stations": len(evidence),
        "api_identity_matches": sum(
            bool(e["identity_verified_from_official_api"]) for e in evidence
        ),
        "decoded_official_images": sum(
            bool(e["verified_image_bytes"]) for e in evidence
        ),
        "new_images_for_stations_missing_historical_url": sum(
            bool(e["verified_image_bytes"]) and not e["source_had_logo"]
            for e in evidence
        ),
        "publication_allowed": False,
        "signed_catalog_created": False,
        "records": evidence,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--network", action="store_true")
    args = parser.parse_args()
    if args.inventory.stat().st_size > 3*1024*1024:
        raise InventoryError("Oversized inventory")
    doc = json.loads(args.inventory.read_text(encoding="utf-8"))
    result = collect(doc, network=args.network)
    args.output.write_text(
        json.dumps(result, indent=2, ensure_ascii=False)+"\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status":"GO_OFFICIAL_LAUT_FM_LOGO_CANDIDATES_ONLY",
        "candidates": result["candidate_stations"],
        "identity_matched": result["api_identity_matches"],
        "decoded_image_bytes": result["decoded_official_images"],
        "recovered_missing_urls":result["new_images_for_stations_missing_historical_url"],
        "publication_allowed":False,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
