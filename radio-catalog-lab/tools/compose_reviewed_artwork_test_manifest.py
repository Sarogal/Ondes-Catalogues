#!/usr/bin/env python3
"""Prepare TEST-only artwork sidecar from reviewed first-party image evidence.

This is explicitly NOT a station catalog, not a signing tool and not a
publisher. The sidecar maps historical radio UUIDs to immutable SHA image
descriptors without changing streams, favorites, logos already present,
or the existing signed catalog generation 4.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

UUID = re.compile(r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$", re.I)
SHA = re.compile(r"^[0-9a-f]{64}$")
ASSET = re.compile(r"^https://assets\.laut\.fm/[a-f0-9]{24,80}$")
MIME = {"image/png","image/jpeg","image/webp"}


class ArtworkReviewError(ValueError):
    pass


def compose(queue: dict, review: dict, *, generated_at: str) -> dict:
    if (queue.get("scope") != "LOGO_SHA_PREPUBLICATION_REVIEW_ONLY" or
            queue.get("publication_allowed") is not False or
            queue.get("signed_catalog_created") is not False):
        raise ArtworkReviewError("Input is not trusted review-only evidence")
    if (review.get("scope") != "GROSSES_ONDES_TEST_VISUAL_REVIEW_ONLY" or
            review.get("publication_allowed") is not False or
            review.get("open_discovery_not_allowlist") is not True):
        raise ArtworkReviewError("Input is not isolated visual review decisions")
    entries=queue.get("logo_candidates",[])
    choices=review.get("records",[])
    if not isinstance(entries,list) or not isinstance(choices,list):
        raise ArtworkReviewError("Missing source records")
    by_slug={}
    for choice in choices:
        slug=choice.get("station_slug")
        if (not isinstance(slug,str) or slug in by_slug or
                choice.get("scope") != "test_only" or
                choice.get("publication_allowed") is not False or
                choice.get("replace_existing_logo") is not False or
                choice.get("decision") not in {"test_visual_approved","hold"} or
                not isinstance(choice.get("visual_evidence"),str) or
                len(choice["visual_evidence"]) < 15):
            raise ArtworkReviewError("Invalid visual-review record")
        by_slug[slug]=choice
    approved=sum(x["decision"]=="test_visual_approved" for x in choices)
    if approved!=review.get("approved_for_test") or \
       len(choices)-approved!=review.get("held"):
        raise ArtworkReviewError("Incorrect reviewed candidate totals")
    assets=[]
    ids=set()
    slugs=set()
    digests={}
    for row in entries:
        slug=row["station_slug"]
        if slug in slugs:
            raise ArtworkReviewError("Duplicate reviewed station slug")
        slugs.add(slug)
        choice=by_slug.get(slug)
        if choice is None:
            raise ArtworkReviewError("Missing source-specific review decision")
        if choice["decision"] != "test_visual_approved":
            continue
        id_=row["legacy_media_id"]
        spec=row["candidate_logo"]
        if not UUID.fullmatch(id_) or id_ in ids:
            raise ArtworkReviewError("Invalid/duplicate historical radio ID")
        ids.add(id_)
        if (row.get("identity_provider")!="official_laut_fm_api" or
                row.get("editorial_status")!="candidate_requires_visual_identity_review" or
                row.get("allow_replace_historical_logo") is not False or
                row.get("can_activate") is not False or
                row.get("publication_allowed") is not False or
                row.get("old_source_logo_url") != "" or
                row.get("official_station_page") != "https://laut.fm/"+slug):
            raise ArtworkReviewError("Rejected publisher or station identity evidence")
        url=spec.get("url")
        sha=spec.get("sha256")
        size=spec.get("byte_size")
        w,h=spec.get("width"),spec.get("height")
        if (not isinstance(url,str) or not ASSET.fullmatch(url) or
                not isinstance(sha,str) or not SHA.fullmatch(sha) or
                spec.get("asset_id")!="sha256:"+sha or
                type(size) is not int or not 128<=size<=2*1024*1024 or
                type(w) is not int or type(h) is not int or
                not 192<=w<=4096 or not 192<=h<=4096 or
                w*h>12_000_000 or spec.get("mime_type") not in MIME or
                spec.get("revision")!=1):
            raise ArtworkReviewError("Unsigned or low-quality logo candidate")
        meta=(size,w,h,spec["mime_type"])
        if sha in digests and digests[sha]!=meta:
            raise ArtworkReviewError("Conflicting metadata for same asset hash")
        digests[sha]=meta
        assets.append({
            "legacy_media_id": id_,
            "station_name": row["historical_name"],
            "logo": {
                "asset_id": spec["asset_id"],
                "sha256":sha,"url":url,"byte_size":size,
                "width":w,"height":h,"mime_type":spec["mime_type"],
                "revision":1
            },
            "source": {
                "provider":"laut.fm",
                "official_station_page":row["official_station_page"],
                "station_slug":slug,
                "visual_identity_evidence":choice["visual_evidence"],
                "review_scope":"test_only",
            },
            "replace_existing_logo":False,
        })
    if len(by_slug)!=len(slugs):
        raise ArtworkReviewError("Review choices and evidence do not agree")
    if len(assets)!=approved:
        raise ArtworkReviewError("Approved records missing from source evidence")
    if not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ",generated_at):
        raise ArtworkReviewError("Invalid generated-at timestamp")
    return {
        "schema_version":1,
        "catalog_id":"grosses-ondes-artwork",
        "release_sequence":1,
        "generated_at":generated_at,
        "source_radio_catalog_min_sequence":4,
        "scope":"TEST_ONLY",
        "production_publication_allowed":False,
        "selection_mode":"manual_visual_review_of_open_discovery_candidates",
        "assets":sorted(assets,key=lambda a:a["legacy_media_id"]),
    }


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--queue",type=Path,required=True)
    p.add_argument("--visual-review",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--generated-at",default="2026-11-21T11:30:00Z")
    a=p.parse_args()
    doc=compose(
        json.loads(a.queue.read_text(encoding="utf-8")),
        json.loads(a.visual_review.read_text(encoding="utf-8")),
        generated_at=a.generated_at,
    )
    a.output.write_text(json.dumps(
        doc,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status":"GO_TEST_ARTWORK_UNSIGNED_PENDING_ONLY",
        "assets":len(doc["assets"]),
        "publication_allowed":False,
        "current_pointer_changed":False,
    }))


if __name__=="__main__":
    main()
