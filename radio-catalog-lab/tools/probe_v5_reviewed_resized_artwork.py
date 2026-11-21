#!/usr/bin/env python3
"""Fail-closed fresh SHA verification of a prior manually reviewed laut.fm image.

Review-only: this script never signs/publishes, and only probes a source tied
both to the historical UUID and the original eight-shard SHA evidence. It
does not preapprove new radios or require a closed station/genre list.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

from audit_open_radio_artwork_inventory import probe_image
from artwork_release_packager import official_laut_fm_artwork_url


class ResizeProbeError(ValueError):
    pass


def verify_resized_review(review: dict, queue: dict, source_shards: list[dict],
                          *, candidate_uuid: str, network: bool,
                          probe=probe_image) -> dict:
    if (review.get("scope") != "GO_V5_EXPLICIT_VISUAL_DECISIONS_TEST_ONLY_UNSIGNED"
            or review.get("publication_allowed") is not False
            or review.get("signed_catalog_created") is not False
            or queue.get("scope") != "GO_ARTWORK_V5_EDITORIAL_TRIAGE_ONLY"
            or queue.get("publication_allowed") is not False):
        raise ResizeProbeError("Review must be unsigned")
    sources = [
        s for shard in source_shards
        for s in shard.get("records", [])
        if s.get("legacy_media_id") == candidate_uuid
    ]
    chosen = [r for r in review.get("records", [])
              if r.get("legacy_media_id") == candidate_uuid]
    evidence = [r for r in queue.get("priority_no_initial_logo", [])
                if r.get("legacy_media_id") == candidate_uuid]
    if len(sources)!=1 or len(chosen)!=1 or len(evidence)!=1:
        raise ResizeProbeError("Missing/duplicate exact UUID proof")
    official, visual, bytes_before = sources[0], chosen[0], evidence[0]
    if (visual.get("editorial_decision") != "VISUAL_TEST_ACCEPTED_CANONICAL_BYTES_PENDING"
            or visual.get("can_sign_now") is not False
            or visual.get("publication_allowed") is not False
            or bytes_before.get("probe_verified") is not True
            or bytes_before.get("publication_allowed") is not False
            or bytes_before.get("sha256") != visual.get("candidate_sha256")
            or bytes_before.get("source_url") != visual.get("candidate_url")
            or bytes_before.get("width") != visual.get("expected_width")
            or bytes_before.get("height") != visual.get("expected_height")
            or official.get("source_status") != "OFFICIAL_API_EXACT_ASSET_PATH"
            or official.get("candidate_sha256") != visual.get("candidate_sha256")
            or official.get("candidate_url") != visual.get("candidate_url")
            or official.get("publication_allowed") is not False):
        raise ResizeProbeError("Untrusted or contradictory v5 / source evidence")
    proof = official.get("source_evidence")
    if (not isinstance(proof,list) or len(proof)!=1
            or proof[0].get("kind")!="laut_fm_exact_station_slug_api"
            or proof[0].get("source_path_matches_candidate") is not True
            or proof[0].get("official_station_page") != visual.get("source_official_page")
            or proof[0].get("official_image_url") != visual.get("desired_canonical_url")
            or urlsplit(proof[0]["official_image_url"]).path
                 != urlsplit(visual["candidate_url"]).path
            or not official_laut_fm_artwork_url(
                visual["candidate_url"],
                visual["expected_width"],visual["expected_height"])):
        raise ResizeProbeError("Not a matching, strictly resized official laut.fm image")
    if network:
        result=probe(visual["candidate_url"])
        if not isinstance(result,dict) or result.get("approved_station_logo") is True:
            raise ResizeProbeError("Byte verifier cannot approve station identity")
    else:
        result={"verified_bytes":False,"reason":"offline_no_network"}
    same=(
        result.get("verified_bytes") is True
        and all(result.get(k)==bytes_before.get(k)
                for k in ("sha256","byte_size","width","height","mime_type"))
    )
    return {
        "scope":"GO_V5_RESIZED_ARTWORK_EXACT_BYTES_REVIEW_ONLY",
        "legacy_media_id":candidate_uuid,
        "station_name":visual["station_name"],
        "url":visual["candidate_url"],
        "expected_sha256":visual["candidate_sha256"],
        "fresh_probe":result,
        "fresh_sha_size_mime_dimensions_match":same,
        "publication_allowed":False,
        "signed_catalog_created":False,
        "visual_identity_approval_does_not_sign":True,
    }


def main() -> None:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--review",type=Path,required=True)
    p.add_argument("--queue",type=Path,required=True)
    p.add_argument("--source-shard",type=Path,nargs="+",required=True)
    p.add_argument("--uuid",required=True)
    p.add_argument("--network",action="store_true")
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    load=lambda x:json.loads(x.read_text(encoding="utf-8"))
    report=verify_resized_review(
        load(args.review),load(args.queue),
        [load(x) for x in args.source_shard],
        candidate_uuid=args.uuid,network=args.network,
    )
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(
        report,ensure_ascii=False,sort_keys=True,indent=2)+"\n",
        encoding="utf-8")
    print(json.dumps({
        "status":"GO_RESIZED_ARTWORK_BYTES_REVIEW_ONLY",
        "station":report["station_name"],
        "same_sha":report["fresh_sha_size_mime_dimensions_match"],
        "publication_allowed":False,
    }))
    if args.network and not report["fresh_sha_size_mime_dimensions_match"]:
        raise SystemExit("Fresh source has changed: do NOT sign the old SHA")


if __name__=="__main__":
    main()
