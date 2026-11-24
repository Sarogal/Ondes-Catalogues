#!/usr/bin/env python3
"""Read-only website branding discovery for the remaining 90 missing TEST v8 logos.

Unlike Radio Browser's stale favicon fields, this checks the radio's
recorded publisher homepage itself over HTTPS for OpenGraph/Twitter images,
apple-touch icons and other identified brand assets. No source is assumed
to be a radio logo just because it is found on the publisher site.

Each discovered image is decoded, SHA-256, MIME and size verified through
the existing SSRF-safe bounded image fetcher. Author/brand identity and
generic/article-art risk remain visible in the report for editorial gating.
No TEST pointer changes, no signing or publication.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
import hashlib
import json
from urllib.parse import urlsplit
import re

from audit_open_radio_artwork_inventory import (
    discover_official_page,probe_image,upgraded_https_homepage,
)

ROOT=Path(__file__).resolve().parents[2]
DRAFT=ROOT/"radio-catalog-lab/full-staging/UNSIGNED-radio-v8-metalon-3-independent-3-20261123.json"
SOURCE="f735884aa0841a86d88aaafe406e62b7a826cf9cd60f6a70285a0894326841aa"


def stations()->list[dict]:
    candidate=json.loads(DRAFT.read_bytes())
    if (candidate["release_sequence"]!=8 or len(candidate["stations"])!=296
            or len(candidate["tombstones"])!=24):
        raise ValueError("Unknown unsigned v8 source")
    active=[s for s in candidate["stations"] if s["status"]["state"]=="active"]
    without=sorted([s for s in active if s["logo"] is None],
                   key=lambda s:s["go_station_id"])
    if len(active)!=285 or len(without)!=90:
        raise ValueError("Expected 90 missing station logos in unsigned v8")
    return without


def same_domain(candidate:str,site:str)->bool:
    try:
        a=(urlsplit(candidate).hostname or "").lower().removeprefix("www.")
        b=(urlsplit(site).hostname or "").lower().removeprefix("www.")
    except ValueError:
        return False
    return bool(a and b and (a==b or a.endswith("."+b) or b.endswith("."+a)))


def brand_score(image_url:str,meta_kind:str)->str:
    path=urlsplit(image_url).path.lower()
    if any(x in path for x in ("article","episode","album","artist","covers/","cover-","news",
                              "/posts/","/2026/","sponsor","advert")):
        return "ARTICLE_OR_TRACK_ART_RISK"
    if any(x in path for x in ("logo","brand","branding","stationlogo","radioicon")):
        return "POSSIBLE_STATION_BRAND_LOGO"
    if meta_kind.startswith("html:link-icon"):
        return "ICON_GENERIC_OR_SITE_BRAND_UNREVIEWED"
    if meta_kind.startswith("og:image") or meta_kind.startswith("twitter:image"):
        return "SOCIAL_CARD_NOT_NECESSARILY_STATION_LOGO"
    return "UNREVIEWED"


def run_one(s:dict,network:bool)->dict:
    link=s.get("homepage") or ""
    rec={"go_station_id":s["go_station_id"],
         "catalog_station_name":s["display_name"],
         "catalog_homepage":link,
         "logo_present_in_v8":False,
         "source_page_verified":False,
         "image_candidates":[],"publication_allowed":False}
    if not link:
        rec["problem"]="NO_HOMEPAGE"
        return rec
    converted=upgraded_https_homepage(link)
    if converted is None:
        rec["problem"]="UNSAFE_HOMEPAGE"
        return rec
    if not network:
        rec["problem"]="NO_NETWORK_DRY_RUN"
        return rec
    audit=discover_official_page(link)
    rec["homepage_probe_status"]=audit.get("reason")
    candidates=audit.get("image_candidates",[])
    rec["source_page_verified"]=audit.get("reason") in {
        "homepage_metadata_candidates_not_approved",
        "homepage_no_image_metadata",
    }
    # First-party publisher images only. A third-party logo can be
    # investigated separately with direct content evidence.
    seen=set()
    for option in candidates:
        if len(rec["image_candidates"])>=4:
            break
        source=option["url"]
        if source in seen:
            continue
        seen.add(source)
        kind=option["source_meta"]
        firstparty=same_domain(source,converted)
        row={"image_url":source,
             "evidence":kind,"same_publisher_host":firstparty,
             "purpose":brand_score(source,kind),
             "sha_verified":False,
             "editorial_identity_confirmed":False,
             "publication_allowed":False}
        if firstparty:
            v=probe_image(source)
            row["sha_verified"]=v.get("verified_bytes") is True
            if row["sha_verified"]:
                for attr in ("sha256","byte_size","width","height","mime_type"):
                    row[attr]=v[attr]
            else:
                row["problem"]=v.get("reason")
        else:
            row["problem"]="EXTERNAL_IMAGE_HOST_REQUIRES_DIRECT_PROVIDER_REVIEW"
        rec["image_candidates"].append(row)
    return rec


def collect(shard:int,shards:int,network:bool)->dict:
    all_=stations()
    if not (0<=shard<shards<=24):
        raise ValueError("Invalid shard count")
    items=[s for i,s in enumerate(all_) if i%shards==shard]
    with ThreadPoolExecutor(max_workers=6) as pool:
        tasks=[pool.submit(run_one,s,network) for s in items]
        found=sorted([f.result() for f in as_completed(tasks)],
                     key=lambda item:item["go_station_id"])
    count=sum(x["sha_verified"] and x["same_publisher_host"]
              for s in found for x in s["image_candidates"])
    return {
        "scope":"GO_V8_MISSING_90_OFFICIAL_HOMEPAGE_LOGO_DISCOVERY_READ_ONLY",
        "predecessor_signed_v7_sha":SOURCE,
        "selected_missing":len(found),
        "total_missing_logo_descriptors":90,
        "shard":shard,"shards":shards,
        "firstparty_decoded_sha_candidates":count,
        "publication_allowed":False,"catalog_modified":False,
        "records":found,
    }


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--shard",type=int,required=True)
    p.add_argument("--shards",type=int,default=8)
    p.add_argument("--network",action="store_true")
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    report=collect(a.shard,a.shards,a.network)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",
                        encoding="utf-8")
    print(json.dumps({
        "result":"GO_V8_90_HOMEPAGE_IMAGES_READ_ONLY",
        "shard":a.shard,
        "stations":report["selected_missing"],
        "verified_images":report["firstparty_decoded_sha_candidates"],
        "publication_allowed":False,
    },sort_keys=True))


if __name__=="__main__":
    main()
