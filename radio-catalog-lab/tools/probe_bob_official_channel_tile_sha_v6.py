#!/usr/bin/env python3
"""One-time official RADIO BOB! square artwork recovery for the v6 TEST draft.

These URLs were found in the matching first-party RADIO BOB! stream pages,
NOT guessed from names and NOT sourced from album artwork. The program checks
that each official page embeds its matching tile, decodes actual bytes,
computes SHA-256 and saves exact binaries. This is EVIDENCE ONLY: none of the
catalog, pointer, or images is published or signed automatically.
"""
from __future__ import annotations

import argparse
from html import unescape
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
from urllib.error import HTTPError, URLError
import ssl

from audit_open_radio_artwork_inventory import (
    _request, inspect_bytes, public_https, InventoryError, MAX_HTML, MAX_IMAGE
)

CANDIDATE = Path(__file__).resolve().parents[1] / "full-staging" / "UNSIGNED-radio-v6-radcap-3-duplicate-families-20261123.json"
PAGE = "https://www.radiobob.de/"
CDN = "https://images.radiobob.de/files/"
# Immutable one-time FIRST-PARTY observations: the square tile must appear
# on that named stream page. The daily radio discovery engine has no allowlist.
OFFICIAL_CHANNELS = {
    "metalcore": ("metalcore-stream", "2025-05/metalcore_stream_schrift.jpg"),
    "bob-metal": ("metal-stream", "2025-05/metal_stream_schrift.jpg"),
    "progrock": ("bobs-prog-rock-stream", "2025-05/prock_rock_stream_schrift.jpg"),
    "powermetal": ("power-metal-stream", "2025-05/power_metal_stream_schrift.jpg"),
    "symphmetal": ("bobs-symphonic-metal-stream", "2025-05/symphonic_metal_stream_schrift.jpg"),
    "mittelalter": ("mittelalter-rock-stream", "2025-05/mittelalter_rock_stream_schrift.jpg"),
    "2000er": ("bobs-2000er-rock-stream", "2025-05/2000er_rock_schrift.jpg"),
    "rockparty": ("rockparty-stream", "2025-05/rockparty_stream_schrift.jpg"),
    "bob-hartesaite": ("bobs-harte-saite", "2025-05/harte_saite_stream_schrift.jpg"),
    "gothic": ("gothic-rock-stream", "2025-05/gothic_rock_stream_schrift.jpg"),
    "bob-wacken": ("wacken-radio-stream", "2025-07/wackenradio.jpg"),
    "metallica": ("metallica-stream", "2025-05/metallica_stream_schrift.jpg"),
    "bob-acdc": ("acdc-stream", "2025-05/acdc_stream_schrift.jpg"),
    "bob-punk": ("punk-stream", "2025-05/punk_stream_schrift.jpg"),
}
MIME_EXT = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
BOB_URL = re.compile(r"^https?://streams\.radiobob\.de/([^/]+)/", re.I)


def target_rows(candidate: dict) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for station in candidate.get("stations", []):
        if station.get("logo") is not None:
            continue
        codes = {
            hit.group(1).lower()
            for stream in station.get("streams", [])
            if (hit := BOB_URL.match(stream.get("url", "")))
        }
        if len(codes) > 1:
            raise ValueError("One station unexpectedly uses multiple RADIO BOB! programs")
        for code in codes:
            result.setdefault(code, []).append(station["go_station_id"])
    if (len(result) != 14 or sum(map(len, result.values())) != 19
            or set(result) != set(OFFICIAL_CHANNELS)):
        raise ValueError("Expected 14 first-party BOB channels behind 19 missing-logo stations")
    return result


def collect(rows: dict[str, list[str]], *, network: bool, folder: Path) -> dict:
    records = []
    for channel, station_ids in sorted(rows.items()):
        page_slug, image_path = OFFICIAL_CHANNELS[channel]
        page = PAGE + page_slug
        image = CDN + image_path + "?width=360&height=360"
        assert public_https(page) and public_https(image)
        info = {
            "channel_stream_slug": channel,
            "go_station_ids": station_ids,
            "verified_first_party_page": page,
            "official_square_tile_url": image,
            "download_verified_sha": False,
            "page_embeds_tile": False,
            "editorial_identity_review_complete": False,
            "publication_allowed": False,
        }
        if network:
            # The RADIO BOB! website may render stream artwork via JS; its
            # plain HTML therefore cannot always prove an image/slug match.
            # Independently obtain exact image SHA bytes even if that happens.
            # In that case DO NOT approve the image/station identity.
            try:
                html, mime, destination = _request(
                    page, max_bytes=MAX_HTML, accept="text/html")
                if mime not in {"text/html", "application/xhtml+xml", ""}:
                    raise InventoryError("Official stream page is not HTML")
                if urlsplit(destination).hostname not in ("www.radiobob.de", "radiobob.de"):
                    raise InventoryError("Official page redirected to another host")
                raw = unescape(html.decode("utf-8", errors="replace"))
                info["page_embeds_tile"] = image_path in raw
                info["page_check_status"] = (
                    "EMBEDDED_EXACT_TILE" if info["page_embeds_tile"]
                    else "DYNAMIC_RENDERING_REQUIRES_INDEPENDENT_IDENTITY_REVIEW"
                )
            except (InventoryError, HTTPError, URLError, TimeoutError,
                    OSError, ssl.SSLError, ValueError) as exc:
                info["page_check_status"] = "OFFICIAL_PAGE_UNAVAILABLE"
                info["page_error_type"] = type(exc).__name__
            try:
                data, image_mime, final = _request(
                    image, max_bytes=MAX_IMAGE, accept="image/png,image/jpeg,image/webp")
                if urlsplit(final).hostname != "images.radiobob.de":
                    raise InventoryError("Official channel tile redirected off provider domain")
                sha_meta = inspect_bytes(data, content_type=image_mime)
                info["sha_evidence"] = sha_meta
                info["download_verified_sha"] = True
                ext = MIME_EXT[sha_meta["mime_type"]]
                path = folder / "objects" / (sha_meta["sha256"] + "." + ext)
                path.parent.mkdir(parents=True, exist_ok=True)
                if path.exists() and path.read_bytes() != data:
                    raise InventoryError("SHA object collision on disk")
                path.write_bytes(data)
                info["staged_object_name"] = "objects/" + path.name
                info["status"] = (
                    "FIRST_PARTY_PAGE_AND_IMAGE_BYTES_VERIFIED_PENDING_EDITORIAL"
                    if info["page_embeds_tile"]
                    else "OFFICIAL_CDN_BYTES_VERIFIED_IDENTITY_REVIEW_REQUIRED"
                )
            except (InventoryError, HTTPError, URLError, TimeoutError,
                    OSError, ssl.SSLError, ValueError) as exc:
                info["status"] = "IMAGE_BYTE_VERIFICATION_FAILED"
                info["image_error_type"] = type(exc).__name__
        records.append(info)
    return {
        "schema_version": 1,
        "scope": "BOB_FIRST_PARTY_SQUARE_TILE_SHA_UNPUBLISHED",
        "candidate_release_sequence": 6,
        "station_ids_with_missing_logo": sum(map(len, rows.values())),
        "unique_official_channel_pages": len(rows),
        "verified_official_page_and_image_count": sum(
            r["download_verified_sha"] and r["page_embeds_tile"] for r in records),
        "verified_official_cdn_image_count": sum(
            r["download_verified_sha"] for r in records),
        "publication_allowed": False,
        "images_do_not_become_signed_until_separate_review": True,
        "records": records,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=CANDIDATE)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--network", action="store_true")
    args = parser.parse_args()
    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    if catalog.get("release_sequence") != 6:
        raise ValueError("Expected a draft v6 only")
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    ids = target_rows(catalog)
    report = collect(ids, network=args.network, folder=output)
    (output / "bob-official-channel-tile-evidence.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "BOB_OFFICIAL_SHA_EVIDENCE_ONLY",
        "channels": report["unique_official_channel_pages"],
        "station_ids": report["station_ids_with_missing_logo"],
        "verified_shas": report["verified_official_cdn_image_count"],
        "source_identity_verified": report["verified_official_page_and_image_count"],
        "publication_allowed": False,
    }))


if __name__ == "__main__":
    main()
