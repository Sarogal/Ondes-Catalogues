#!/usr/bin/env python3
"""Turn qualified official laut.fm byte evidence into a NOT-ACTIVE logo queue.

A digest/decoder check is not an editorial approval. The records produced by
this module are NEVER a signed catalog, never a published radio station, and
never an instruction to overwrite current logos. Every future station UUID is
eligible without a closed station/host list; exact provider identity is still
required for each candidate.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from audit_open_radio_artwork_inventory import InventoryError, validate_inventory

SHA = re.compile(r"^[a-f0-9]{64}$")
MIME = {"image/jpeg", "image/png", "image/webp"}


def stage(inventory: dict, evidence: dict) -> dict:
    inventory_rows = validate_inventory(inventory)
    by_id = {row["legacy_media_id"]: row for row in inventory_rows}
    if (not isinstance(evidence, dict) or
            evidence.get("scope") != "OFFICIAL_LAUT_FM_ARTWORK_DISCOVERY_NOT_PUBLICATION"
            or evidence.get("source_blob_sha") != inventory["source"]["blob_sha"]
            or evidence.get("publication_allowed") is not False or
            evidence.get("signed_catalog_created") is not False):
        raise InventoryError("Untrusted or mismatched official-source evidence")
    rows = evidence.get("records")
    if not isinstance(rows, list):
        raise InventoryError("Missing source records")
    staged = []
    seen_ids = set()
    by_sha = {}
    skipped = []
    for row in rows:
        if not isinstance(row, dict):
            raise InventoryError("Malformed source evidence")
        id_ = row.get("legacy_media_id")
        source = by_id.get(id_)
        if source is None or id_ in seen_ids:
            raise InventoryError("Unknown or repeated station UUID")
        seen_ids.add(id_)
        if (row.get("historical_name") != source["display_name"] or
                row.get("historical_homepage") != source["homepage"] or
                row.get("station_logo_approved") is not False or
                row.get("publication_allowed") is not False):
            raise InventoryError("Media identity changed or already approved")
        if not (row.get("identity_verified_from_official_api") is True
                and row.get("verified_image_bytes") is True):
            skipped.append({"legacy_media_id":id_, "reason":row.get("reason")})
            continue
        spec = row.get("image_byte_evidence")
        if not isinstance(spec, dict) or spec.get("verified_bytes") is not True or \
           spec.get("approved_station_logo") is not False:
            raise InventoryError("Image checksum not independently verified")
        digest = spec.get("sha256")
        length = spec.get("byte_size")
        width = spec.get("width")
        height = spec.get("height")
        mime = spec.get("mime_type")
        official = row.get("official_image")
        if (not isinstance(digest, str) or not SHA.fullmatch(digest) or
                type(length) is not int or not 128 <= length <= 2*1024*1024 or
                type(width) is not int or not 64 <= width <= 4096 or
                type(height) is not int or not 64 <= height <= 4096 or
                width*height > 12_000_000 or
                mime not in MIME or
                not isinstance(official, str) or
                urlsplit(official).hostname != "assets.laut.fm" or
                spec.get("candidate_url") != official or
                row.get("official_page") != "https://laut.fm/"+row.get("slug","")):
            raise InventoryError("Signed candidate input has inconsistent image provenance")
        descriptor = {
            "asset_id": "sha256:"+digest,
            "sha256": digest,
            "byte_size": length,
            "width": width,
            "height": height,
            "mime_type": mime,
            "revision": 1,
            "url": official,
        }
        metadata_key = (length, width, height, mime)
        old = by_sha.get(digest)
        if old is not None and old != metadata_key:
            raise InventoryError("Same image SHA with conflicting dimensions/MIME")
        by_sha[digest] = metadata_key
        staged.append({
            "legacy_media_id": id_,
            "historical_name": source["display_name"],
            "old_source_logo_url": source["source_logo_url"],
            "identity_provider": "official_laut_fm_api",
            "station_slug": row["slug"],
            "official_station_page": row["official_page"],
            "candidate_logo": descriptor,
            "editorial_status": "candidate_requires_visual_identity_review",
            "allow_replace_historical_logo": False,
            "can_activate": False,
            "publication_allowed": False,
        })
    return {
        "schema_version": 1,
        "scope": "LOGO_SHA_PREPUBLICATION_REVIEW_ONLY",
        "source_blob_sha": inventory["source"]["blob_sha"],
        "logo_candidates": sorted(staged, key=lambda x:x["legacy_media_id"]),
        "not_qualified": skipped,
        "historical_station_count": len(inventory_rows),
        "unique_candidate_sha_count":len(by_sha),
        "publication_allowed": False,
        "signed_catalog_created": False,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--inventory", type=Path, required=True)
    p.add_argument("--evidence", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args=p.parse_args()
    result=stage(json.loads(args.inventory.read_text(encoding="utf-8")),
                 json.loads(args.evidence.read_text(encoding="utf-8")))
    args.output.write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n",
                           encoding="utf-8")
    print(json.dumps({
        "status":"GO_LAUT_FM_SHA_REVIEW_QUEUE_ONLY",
        "candidates":len(result["logo_candidates"]),
        "unique_sha":result["unique_candidate_sha_count"],
        "unqualified":len(result["not_qualified"]),
        "publication_allowed":False,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
