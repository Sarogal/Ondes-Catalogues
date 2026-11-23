#!/usr/bin/env python3
"""Read-only diagnosis of missing RADIO BOB!/Exclusively logos in TEST v6.

Discover favicon candidates by their OWN historical Radio Browser UUID, then
probe exact image bytes for SHA-256, MIME and pixel size. This is NOT approval,
NOT a signed catalog, NOT a publisher, and never copies arbitrary genre art.
The audit scope is two providers; it does not limit radio discovery itself.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from urllib.error import HTTPError, URLError

from audit_open_radio_artwork_inventory import public_https, probe_image
from discover_radio_browser_logo_candidates import fetch_radio_browser_batch

CANDIDATE = (Path(__file__).resolve().parents[1] / "full-staging" /
             "UNSIGNED-radio-v6-radcap-3-duplicate-families-20261123.json")
UUID = re.compile(r"^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$", re.I)


def provider(station: dict) -> str | None:
    urls = [s.get("url", "").lower() for s in station.get("streams", [])]
    if any("streams.radiobob.de/" in u for u in urls):
        return "RADIO_BOB"
    if any("streaming.exclusive.radio/" in u for u in urls):
        return "EXCLUSIVELY"
    return None


def discover(candidate: dict, *, network: bool, lookup=fetch_radio_browser_batch,
             probe=probe_image) -> dict:
    stations = candidate["stations"]
    tombstones = candidate.get("tombstones", [])
    by_owner = {}
    for old in tombstones:
        redirect = old.get("redirect_to")
        if redirect:
            by_owner.setdefault(redirect, []).extend(old.get("legacy_aliases", []))
    target = [s for s in stations if provider(s) and s.get("logo") is None]
    uuids = sorted({
        alias.lower() for s in target for alias in
        s["legacy_aliases"] + by_owner.get(s["go_station_id"], [])
        if UUID.fullmatch(alias)
    })
    received = {}
    errors = []
    for start in range(0, len(uuids), 40):
        batch = uuids[start:start + 40]
        if not network:
            continue
        try:
            received.update(lookup(batch))
        except (ValueError, HTTPError, URLError, TimeoutError, OSError,
                RuntimeError) as exc:
            errors.append({"batch_start": start, "type": type(exc).__name__})
    probed = {}
    entries = []
    for station in target:
        extra = by_owner.get(station["go_station_id"], [])
        identities = sorted(set(s.lower() for s in
                                station["legacy_aliases"] + extra))
        candidate_urls = {}
        for uuid in identities:
            rb = received.get(uuid)
            if rb is None:
                continue
            image = (rb.get("favicon") or "").strip()
            if public_https(image):
                candidate_urls.setdefault(image, []).append(uuid)
        artwork = []
        for url, matching_uuids in sorted(candidate_urls.items()):
            if url not in probed:
                probed[url] = probe(url) if network else {
                    "candidate_url": url, "verified_bytes": False,
                    "reason": "dry_run_no_network"}
            verified = probed[url]
            artwork.append({
                "favicon_url": url,
                "matched_historical_uuids": matching_uuids,
                "sha256": verified.get("sha256"),
                "byte_size": verified.get("byte_size"),
                "mime_type": verified.get("mime_type"),
                "width": verified.get("width"),
                "height": verified.get("height"),
                "download_verified_sha": verified.get("verified_bytes") is True,
                "error": verified.get("reason"),
                "identity_approved": False,
                "publication_allowed": False,
            })
        entries.append({
            "go_station_id": station["go_station_id"],
            "provider": provider(station),
            "name": station["display_name"],
            "historical_uuids_checked": identities,
            "resolved_uuids": [id_ for id_ in identities if id_ in received],
            "artwork_candidates": artwork,
            "missing_logo_at_start": True,
            "brand_channel_verified": False,
            "publication_allowed": False,
        })
    return {
        "schema_version": 1,
        "scope": "RADIO_BOB_EXCLUSIVELY_MISSING_SHA_DISCOVERY_READ_ONLY",
        "source_catalog_sequence": candidate["release_sequence"],
        "target_missing_logo_count": len(target),
        "provider_counts": {
            "RADIO_BOB": sum(e["provider"] == "RADIO_BOB" for e in entries),
            "EXCLUSIVELY": sum(e["provider"] == "EXCLUSIVELY" for e in entries),
        },
        "requested_uuid_count": len(uuids),
        "resolved_uuid_count": len(received),
        "unique_image_urls_probed": len(probed),
        "download_verified_sha_candidates": sum(
            v.get("verified_bytes") is True for v in probed.values()),
        "radio_browser_errors": errors,
        "publication_allowed": False,
        "entries": entries,
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--catalog", type=Path, default=CANDIDATE)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--network", action="store_true")
    args = p.parse_args()
    candidate = json.loads(args.catalog.read_text(encoding="utf-8"))
    if (candidate.get("release_sequence") != 6
            or len(candidate.get("stations", [])) != 315):
        raise ValueError("Unexpected UNSIGNED TEST v6 input")
    report = discover(candidate, network=args.network)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print(json.dumps({
        "status": "MISSING_BOB_EXCLUSIVE_LOGO_DISCOVERY_ONLY",
        "missing": report["target_missing_logo_count"],
        "providers": report["provider_counts"],
        "uuid_requested": report["requested_uuid_count"],
        "uuid_resolved": report["resolved_uuid_count"],
        "sha_verified_url_candidates": report["download_verified_sha_candidates"],
        "publication_allowed": False,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
