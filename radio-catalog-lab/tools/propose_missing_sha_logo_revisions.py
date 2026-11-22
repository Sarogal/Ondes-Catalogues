#!/usr/bin/env python3
"""Stage NEW SHA images only as REVIEWABLE proposals for three failed sources.

Every source belongs to the already audited signed-TEST v5 draft; network URLs
are never invented. New image bytes never inherit old SHA identities. This
tool never edits a station, writes releases, or publishes current.json.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from audit_open_radio_artwork_inventory import _request, inspect_bytes, MAX_IMAGE
from stage_immutable_sha_artwork import normalized_assets, EXTENSIONS


def review_missing(catalog: dict, immutable_manifest: dict, outdir: Path) -> dict:
    if outdir.exists():
        raise ValueError("Refusing to overwrite an earlier source-recheck archive")
    records = immutable_manifest.get("objects")
    if not isinstance(records, list) or len(records) != 89:
        raise ValueError("Unrecognized independent SHA archive manifest")
    affected = [r for r in records if r.get("ready_for_explicit_review") is False]
    if len(affected) != 3:
        raise ValueError("Expected exactly three unresolved historical SHA objects")
    by_sha = {r["sha256"]: r for r in normalized_assets(catalog)}
    if len(by_sha) != 89:
        raise ValueError("Unexpected original v5 logo identity set")
    outdir.mkdir(parents=True)
    images = outdir / "sha256"
    images.mkdir()
    proposals = []
    for lost in affected:
        old_sha = lost["sha256"]
        source = by_sha[old_sha]
        owners = [
            {"go_station_id": s["go_station_id"], "name": s["display_name"]}
            for s in catalog["stations"]
            if isinstance(s.get("logo"), dict) and s["logo"]["sha256"] == old_sha
        ]
        proposal = {
            "old_sha256": old_sha,
            "source_url": source["url"],
            "owners": owners,
            "old_error_code": lost.get("reason_code"),
            "may_be_published": False,
            "requires_station_identity_quality_review": True,
        }
        try:
            data, mime, final_url = _request(
                source["url"], max_bytes=MAX_IMAGE,
                accept="image/png,image/jpeg,image/webp")
            fresh = inspect_bytes(data, content_type=mime)
            new_sha = fresh["sha256"]
            ext = EXTENSIONS[fresh["mime_type"]]
            name = "sha256/" + new_sha + "." + ext
            (outdir / name).write_bytes(data)
            proposal.update({
                "source_check": ("recovered_same_SHA" if new_sha == old_sha
                                 else "new_SHA_candidate_not_approved"),
                "replacement_descriptor_proposal": {
                    "asset_id": "sha256:" + new_sha,
                    "sha256": new_sha,
                    "byte_size": fresh["byte_size"],
                    "width": fresh["width"],
                    "height": fresh["height"],
                    "mime_type": fresh["mime_type"],
                    "url": final_url,
                    "revision": source["revision"] + (0 if new_sha == old_sha else 1),
                },
                "verified_file": name,
            })
        except Exception as exc:
            proposal.update({
                "source_check": "not_fetchable_no_replacement",
                "error_code": type(exc).__name__,
            })
        proposals.append(proposal)
    report = {
        "scope": "UNSIGNED_NEW_SHA_ARTWORK_REVIEW_PROPOSALS_ONLY",
        "source_catalog_stations": len(catalog["stations"]),
        "original_sha_objects": len(by_sha),
        "unresolved_original_SHA_count": len(affected),
        "proposals": proposals,
        "updated_radio_catalog": False,
        "updated_remote_pointer": False,
        "signed_or_published": False,
        "approved_image_changes": 0,
    }
    (outdir / "unsigned-proposals.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--outdir", required=True, type=Path)
    args = parser.parse_args()
    read = lambda p: json.loads(p.read_text(encoding="utf-8"))
    report = review_missing(read(args.catalog), read(args.manifest), args.outdir)
    print(json.dumps({
        "unresolved_original_SHA_count": report["unresolved_original_SHA_count"],
        "station_proposals": [
            {
                "stations": [o["name"] for o in x["owners"]],
                "status": x["source_check"],
                "old_sha256": x["old_sha256"],
                "new_sha256": x.get("replacement_descriptor_proposal", {}).get("sha256"),
            } for x in report["proposals"]
        ],
        "updated_remote_pointer": False, "signed_or_published": False,
    }, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
