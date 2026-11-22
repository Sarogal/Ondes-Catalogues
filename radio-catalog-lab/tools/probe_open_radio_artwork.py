#!/usr/bin/env python3
"""Bounded SHA-256/decoder evidence for official-source radio artwork candidates.

NEVER labels logos as approved, never downloads permanently, never signs,
never publishes. Network-brand logos are NOT silently mapped to genre-specific
channels. SHA256 is meaningful only for immutable bytes actually retrieved.
"""
from __future__ import annotations

import argparse
from io import BytesIO
import hashlib
import json
from pathlib import Path
import ssl
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPSHandler, Request, build_opener
from probe_open_radio_candidates import (
    CandidateError, HttpsOnlyRedirects, public_https, validate_input,
)

MAX_LOGO_BYTES = 2 * 1024 * 1024
MAX_DIMENSION = 4096
ALLOWED_FORMATS = {"PNG", "JPEG", "WEBP"}


def inspect_image_bytes(data: bytes) -> dict:
    from PIL import Image, UnidentifiedImageError
    if not 128 <= len(data) <= MAX_LOGO_BYTES:
        raise CandidateError("Logo bytes outside safe bounds")
    try:
        with Image.open(BytesIO(data)) as img:
            width, height = img.size
            fmt = img.format
            if (fmt not in ALLOWED_FORMATS or
                    not 48 <= width <= MAX_DIMENSION or
                    not 48 <= height <= MAX_DIMENSION or
                    width * height > 12_000_000):
                raise CandidateError("Unsupported image format or dimensions")
            img.verify()
    except (OSError, ValueError, UnidentifiedImageError) as e:
        raise CandidateError("Logo decoder rejected bytes") from e
    return {
        "sha256": hashlib.sha256(data).hexdigest(),
        "byte_length": len(data),
        "width": width,
        "height": height,
        "image_format": fmt,
    }


def inspect_logo(url: str, scope: str, timeout: int = 12) -> dict:
    result = {
        "url": url,
        "claimed_scope": scope,
        "image_bytes_decoded": False,
        "editorially_approved": False,
        "catalogue_logo_published": False,
    }
    if not public_https(url):
        result["reason"] = "unsafe_source_url"
        return result
    req = Request(url, headers={
        "User-Agent": "GrossesOndes/central-test-logo-evidence-20261121",
        "Accept": "image/jpeg, image/png, image/webp",
    })
    opener = build_opener(
        HTTPSHandler(context=ssl.create_default_context()),
        HttpsOnlyRedirects(),
    )
    started = time.monotonic()
    try:
        with opener.open(req, timeout=timeout) as response:
            if not public_https(response.geturl()):
                raise CandidateError("Unsafe redirect destination")
            content_type = response.headers.get("Content-Type", "").split(";")[0].lower()
            if content_type not in {"image/jpeg", "image/png", "image/webp"}:
                raise CandidateError("Unacceptable Content-Type")
            data = response.read(MAX_LOGO_BYTES + 1)
            inspected = inspect_image_bytes(data)
            result.update(inspected)
            result["content_type"] = content_type
            result["image_bytes_decoded"] = True
            result["reason"] = "SHA_bytes_observed_still_needs_visual_brand_review"
    except (HTTPError, URLError, OSError, TimeoutError, CandidateError) as e:
        result["reason"] = type(e).__name__
    result["duration_ms"] = round((time.monotonic()-started)*1000)
    return result


def evaluate(manifest: dict, *, network: bool) -> dict:
    entries = validate_input(manifest)
    report = {
        "schema_version": 1,
        "evidence_kind": "sha256_byte_probe_without_editorial_approval",
        "publication_allowed": False,
        "signed_release_generated": False,
        "radios": [],
    }
    for row in entries:
        logo_evidence = []
        for candidate in row.get("logo_candidates", []):
            image = inspect_logo(
                candidate["url"], candidate.get("scope", "unknown")
            ) if network else {
                "url": candidate["url"], "claimed_scope": candidate.get("scope", "unknown"),
                "image_bytes_decoded": False,
                "editorially_approved": False,
                "catalogue_logo_published": False,
                "reason": "offline_preflight_only",
            }
            logo_evidence.append(image)
        report["radios"].append({
            "candidate_id": row["candidate_id"],
            "name": row["name"],
            "logo_evidence": logo_evidence,
            "logo_editorial_review_required": True,
        })
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--live-probe", action="store_true")
    args = parser.parse_args()
    if args.manifest.stat().st_size > 200_000:
        raise CandidateError("Manifest too large")
    report = evaluate(
        json.loads(args.manifest.read_text(encoding="utf-8")),
        network=args.live_probe,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False)+"\n",
                           encoding="utf-8")
    checked = [x for radio in report["radios"] for x in radio["logo_evidence"]]
    print(json.dumps({
        "status": "GO_LOGO_SHA_CANDIDATE_ONLY",
        "decoded_images": sum(bool(item["image_bytes_decoded"]) for item in checked),
        "total_images": len(checked),
        "publication_allowed": False,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
