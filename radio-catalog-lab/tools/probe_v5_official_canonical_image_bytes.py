#!/usr/bin/env python3
"""Recheck canonical laut.fm image bytes before potential TEST artwork signing.

This is NOT a signing tool. It compares a previously SHA-checked v5 URL to
the exact canonical image URL independently reported by the official station
API. Parameterized image URLs may serve different bytes, so matching *paths*
alone never makes an image eligible to sign. No station allowlist is used.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from audit_open_radio_artwork_inventory import probe_image

API_SCOPE = "GO_V5_OFFICIAL_SOURCE_CORROBORATION_REVIEW_ONLY"
RESULT_SCOPE = "GO_V5_CANONICAL_ARTWORK_BYTES_EVIDENCE_ONLY"
ASSET = re.compile(r"^https://assets\.laut\.fm/[0-9a-f]{24,80}$")
SHA = re.compile(r"^[a-f0-9]{64}$")
UUID = re.compile(r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$", re.I)


class CanonicalEvidenceError(ValueError):
    pass


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise CanonicalEvidenceError(reason)


def collect(report_shards: list[dict], *, network: bool,
            downloader=probe_image) -> dict:
    require(bool(report_shards), "No first-party source evidence")
    expected = report_shards[0].get("shard_count")
    require(type(expected) is int and 1 <= expected <= 16,
            "Invalid first-party shard count")
    seen_shards, seen_ids, matched = set(), set(), []
    for report in report_shards:
        index = report.get("shard_index")
        require(report.get("scope") == API_SCOPE
                and report.get("publication_allowed") is False
                and report.get("identity_visual_approved") is False
                and report.get("signed_catalog_created") is False
                and report.get("shard_count") == expected
                and type(index) is int and 0 <= index < expected
                and index not in seen_shards,
                "Untrusted, partial or duplicate first-party evidence")
        seen_shards.add(index)
        rows = report.get("records")
        require(isinstance(rows, list)
                and report.get("candidate_count") == len(rows),
                "Corrupted first-party source report")
        for row in rows:
            sid = row.get("legacy_media_id")
            require(isinstance(sid, str) and UUID.fullmatch(sid)
                    and sid not in seen_ids
                    and row.get("publication_allowed") is False
                    and row.get("identity_visual_approved") is False,
                    "Duplicated or approved station UUID")
            seen_ids.add(sid)
            if row.get("source_status") != "OFFICIAL_API_EXACT_ASSET_PATH":
                continue
            source = row.get("source_evidence")
            require(isinstance(source, list) and len(source) == 1,
                    "Official API evidence not unique")
            proof = source[0]
            canonical = proof.get("official_image_url")
            sha = row.get("candidate_sha256")
            require(proof.get("kind") == "laut_fm_exact_station_slug_api"
                    and proof.get("source_path_matches_candidate") is True
                    and isinstance(canonical, str)
                    and ASSET.fullmatch(canonical)
                    and isinstance(sha, str) and SHA.fullmatch(sha),
                    "Non-canonical or missing official source proof")
            matched.append({
                "legacy_media_id": sid,
                "station_name": row["station_name"],
                "source_station_url": proof["official_station_page"],
                "canonical_image_url": canonical,
                "v5_image_url": row["candidate_url"],
                "v5_sha256": sha,
            })
    require(seen_shards == set(range(expected)),
            "Some independent source shards are missing")
    require(not network or len(matched) <= 32,
            "Too many images in bounded canonical recheck")
    by_url = {}
    out = []
    for row in sorted(matched, key=lambda x: x["legacy_media_id"]):
        url = row["canonical_image_url"]
        if url not in by_url:
            by_url[url] = (
                downloader(url) if network
                else {"verified_bytes": False, "reason": "offline_no_request"}
            )
        e = by_url[url]
        require(isinstance(e, dict)
                and e.get("approved_station_logo") is not True
                and e.get("publication_allowed") is not True,
                "Byte probe attempted editorial approval")
        verified = e.get("verified_bytes") is True
        same = verified and e.get("sha256") == row["v5_sha256"]
        quality = (
            verified and type(e.get("width")) is int
            and type(e.get("height")) is int
            and min(e["width"], e["height"]) >= 192
        )
        out.append({
            **row,
            "canonical_probe": e,
            "canonical_sha_matches_v5_sha": same,
            "canonical_satisfies_192px_quality": quality,
            "canonical_sha_and_quality_ready_for_visual_review": same and quality,
            "identity_visual_approved": False,
            "publication_allowed": False,
            "replace_existing_logo": False,
        })
    return {
        "schema_version": 1,
        "scope": RESULT_SCOPE,
        "canonical_image_count": len(by_url),
        "candidate_radios": len(out),
        "same_sha": sum(r["canonical_sha_matches_v5_sha"] for r in out),
        "same_sha_and_quality": sum(
            r["canonical_sha_and_quality_ready_for_visual_review"] for r in out),
        "network_enabled": network,
        "publication_allowed": False,
        "signed_catalog_created": False,
        "records": out,
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-report", nargs="+", type=Path, required=True)
    p.add_argument("--network", action="store_true")
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    shards = [json.loads(path.read_text(encoding="utf-8"))
              for path in args.source_report]
    report = collect(shards, network=args.network)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(
        report, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "records"},
                     sort_keys=True))


if __name__ == "__main__":
    main()
