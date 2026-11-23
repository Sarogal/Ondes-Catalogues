#!/usr/bin/env python3
"""READ-ONLY verification of every signed SHA image in GO TEST v6.

The v6 APK displays an artwork only after validating exact SHA-256, byte
count, dimensions and MIME. For this audit, probe each distinct image URL
and compare actual bytes with its signed descriptor. No catalog edits, no
merges, no logo publishing, no secret signing key use.

Run in parallel 8 shards for bounded upstream traffic; accept per-source
network failures as evidence of unreliable availability, not permission
to change the signed catalog.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path

from audit_open_radio_artwork_inventory import probe_image, public_https

ROOT = Path(__file__).resolve().parents[2]
CATALOG = (ROOT / "grossesondes/radio-test-v2/releases" /
           "40215a58967a8b7a83b322c9f02645a9bc2bf319385442e5d89277e0b0d6d861.json")
EXPECTED_HASH = "40215a58967a8b7a83b322c9f02645a9bc2bf319385442e5d89277e0b0d6d861"


def collect(*, network: bool, shard_index: int, shard_count: int) -> dict:
    raw = CATALOG.read_bytes()
    if hashlib.sha256(raw).hexdigest() != EXPECTED_HASH:
        raise ValueError("Signed catalog digest differs from TEST v6 pointer")
    cat = json.loads(raw)
    if cat["release_sequence"] != 6:
        raise ValueError("Incorrect signed release")
    active = [s for s in cat["stations"] if s["status"]["state"] == "active"]
    if len(active) != 304:
        raise ValueError("Expected 304 active radios")
    images = defaultdict(list)
    for s in active:
        if s["logo"] is not None:
            img=s["logo"]
            images[img["sha256"]].append((s["go_station_id"],img))
    if sum(map(len,images.values())) != 185 or len(images) != 98:
        raise ValueError("Logo coverage changed")
    assert 0 <= shard_index < shard_count <= 32
    records=[]
    for digest,owner in sorted(images.items()):
        if int(digest,16) % shard_count != shard_index:
            continue
        variants = {}
        for id_,desc in owner:
            variants.setdefault(desc["url"],(desc,[]))[1].append(id_)
        results=[]
        for url,(desc,ids) in sorted(variants.items()):
            if not public_https(url):
                state="UNSAFE_LOGO_SOURCE"
                details={"reason":"HTTPS_source_not_accepted"}
            elif not network:
                state="NOT_FETCHED_DRY_RUN"
                details={}
            else:
                trial=probe_image(url)
                if trial.get("verified_bytes") is not True:
                    state="UNAVAILABLE_OR_BLOCKED"
                    details={"reason":trial.get("reason")}
                elif (trial["sha256"] != digest or
                      trial["byte_size"] != desc["byte_size"] or
                      trial["width"] != desc["width"] or
                      trial["height"] != desc["height"] or
                      trial["mime_type"] != desc["mime_type"]):
                    state="SIGNED_DESCRIPTOR_MISMATCH"
                    details={"actual_sha256":trial["sha256"],
                             "reason":"SHA_length_mime_or_dimensions_mismatch"}
                else:
                    state="SHA_IMAGE_BYTES_VERIFIED"
                    details={"byte_size":trial["byte_size"]}
            results.append({
                "url":url,
                "go_station_ids":ids,
                "status":state,
                "details":details,
                "publish":False,
            })
        records.append({"sha256":digest,"station_count":len(owner),
                        "go_station_ids":list(dict.fromkeys(x[0] for x in owner)),
                        "tested_urls":results,
                        "any_source_verified":any(z["status"]=="SHA_IMAGE_BYTES_VERIFIED"
                                                  for z in results)})
    return {
        "catalog_release_sequence":6,
        "catalog_signed_sha256":EXPECTED_HASH,
        "scope":"READ_ONLY_TEST_V6_SIGNED_ARTWORK_LINK_HEALTH",
        "station_count":304,
        "radio_without_descriptor":119,
        "radio_with_descriptor":185,
        "distinct_sha_count":98,
        "shard_index":shard_index,
        "shard_count":shard_count,
        "tested_distinct_shas":len(records),
        "verified_distinct_shas":sum(r["any_source_verified"] for r in records),
        "distinct_shas_unverified":sum(not r["any_source_verified"] for r in records),
        "publication_allowed":False,
        "records":records,
    }


def main() -> None:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--shard-index",type=int,default=0)
    p.add_argument("--shard-count",type=int,default=1)
    p.add_argument("--network",action="store_true")
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    result=collect(network=args.network,shard_index=args.shard_index,
                   shard_count=args.shard_count)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",
                          encoding="utf-8")
    print(json.dumps({
        "result":"GO_RADIO_304_SIGNED_LOGO_HEALTH_READ_ONLY",
        "shard_index":result["shard_index"],
        "shard_count":result["shard_count"],
        "tested_unique_sha":result["tested_distinct_shas"],
        "verified_unique_sha":result["verified_distinct_shas"],
        "unverified_unique_sha":result["distinct_shas_unverified"],
        "publication_allowed":False
    }))


if __name__ == "__main__":
    main()
