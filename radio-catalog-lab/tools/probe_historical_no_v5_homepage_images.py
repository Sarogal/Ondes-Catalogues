#!/usr/bin/env python3
"""SHA-check official homepage OG/Twitter artwork of historical no-v5 radios.

The eight earlier reports contain open-discovered HTTPS metadata. This tool
performs an independent size-bounded fetch and Pillow decode of at most two
social-card images per UUID. Site icons and favicons are NOT treated as
identifiable station art. No station, supplier or genre allowlist is present.
All outputs remain nonpublishable, even if SHA and dimensions verify.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from audit_open_radio_artwork_inventory import public_https, probe_image

SCOPE="GO_HISTORICAL_NO_V5_OFFICIAL_LOGO_DISCOVERY_REVIEW_ONLY"
META={"og:image","og:image:url","twitter:image","twitter:image:src"}


class NoV5MetaProbeError(ValueError):
    pass


def require(ok, message):
    if not ok:
        raise NoV5MetaProbeError(message)


def probe_reports(reports: list[dict], *, network: bool,
                  downloader=probe_image) -> dict:
    require(isinstance(reports,list) and len(reports)>0,
            "No historical metadata shards")
    shard_count=reports[0].get("shard_count")
    require(type(shard_count) is int and 1 <= shard_count <= 16
            and len(reports)==shard_count,
            "Incomplete metadata shard set")
    ids=set()
    shards=set()
    candidates=[]
    skipped_icons=0
    historical_total=reports[0].get("historical_total")
    without=reports[0].get("historical_without_v5")
    with_v5=reports[0].get("historical_with_v5")
    require(type(historical_total) is int
            and type(without) is int and type(with_v5) is int
            and with_v5+without==historical_total,
            "Invalid historical inventory scope")
    for report in reports:
        index=report.get("shard_index")
        require(report.get("scope")==SCOPE
                and report.get("publication_allowed") is False
                and report.get("signed_catalog_created") is False
                and report.get("identity_visual_approved") is False
                and report.get("historical_total")==historical_total
                and report.get("historical_with_v5")==with_v5
                and report.get("historical_without_v5")==without
                and type(index) is int and 0<=index<shard_count
                and index not in shards
                and report.get("shard_count")==shard_count,
                "Unsigned first-party shard validation failed")
        shards.add(index)
        rows=report.get("records")
        require(isinstance(rows,list)
                and report.get("selected")==len(rows),
                "Malformed source records")
        for row in rows:
            sid=row.get("legacy_media_id")
            require(isinstance(sid,str) and sid not in ids
                    and row.get("publication_allowed") is False
                    and row.get("replace_existing_logo") is False
                    and row.get("identity_visual_approved") is False,
                    "Duplicate UUID or forbidden approval")
            ids.add(sid)
            images=row.get("image_candidates",[])
            require(isinstance(images,list) and len(images)<=8,
                    "Oversized metadata candidates")
            used=0
            for img in images:
                require(isinstance(img,dict)
                        and img.get("verified_image_bytes") is False
                        and img.get("identity_visual_approved") is False
                        and img.get("publication_allowed") is False,
                        "Already approved or untrusted image candidate")
                kind=img.get("source_meta")
                if kind not in META:
                    skipped_icons+=1
                    continue
                if used>=2:
                    continue
                url=img.get("url")
                require(isinstance(url,str) and public_https(url),
                        "Non-public HTTPS metadata URL")
                candidates.append({
                    "legacy_media_id":sid,
                    "station_name":row["station_name"],
                    "homepage":row["historical_homepage"],
                    "previous_logo_url_preserved":
                        row["historical_logo_url_preserved"],
                    "source_meta":kind,
                    "candidate_url":url,
                    "identity_visual_approved":False,
                    "replace_existing_logo":False,
                    "publication_allowed":False,
                })
                used+=1
    require(shards==set(range(shard_count)) and len(ids)==without,
            "Incomplete historical UUID coverage")
    require(not network or len(candidates)<=80,
            "Bounded network budget exceeded")
    fetched={}
    records=[]
    for item in candidates:
        url=item["candidate_url"]
        if url not in fetched:
            fetched[url]=(downloader(url) if network
                          else {"verified_bytes":False,
                                "reason":"offline_no_download"})
        check=fetched[url]
        require(isinstance(check,dict)
                and check.get("publication_allowed") is not True
                and check.get("approved_station_logo") is not True,
                "Untrusted byte probe approval")
        decoded=check.get("verified_bytes") is True
        size_ok=(decoded and type(check.get("width")) is int
                 and type(check.get("height")) is int
                 and min(check["width"],check["height"])>=192)
        records.append({
            **item,
            "byte_evidence":check,
            "sha_and_decoder_verified":decoded,
            "large_enough_to_review":size_ok,
            "identity_visual_approved":False,
            "publication_allowed":False,
        })
    return {
        "schema_version":1,
        "scope":"GO_NO_V5_HOMEPAGE_IMAGE_SHA_REVIEW_ONLY",
        "historical_missing_v5":without,
        "historical_scanned":len(ids),
        "selected_image_references":len(candidates),
        "distinct_image_urls_probed":len(fetched),
        "technical_image_valid_count":sum(x["sha_and_decoder_verified"]
                                           for x in records),
        "image_quality_min_192_count":sum(x["large_enough_to_review"]
                                           for x in records),
        "site_icons_not_downloaded":skipped_icons,
        "network":network,
        "identity_visual_approved":False,
        "publication_allowed":False,
        "signed_catalog_created":False,
        "records":records,
    }


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-shard",type=Path,nargs="+",required=True)
    parser.add_argument("--network",action="store_true")
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    inputs=[json.loads(p.read_text(encoding="utf-8"))
            for p in args.source_shard]
    result=probe_reports(inputs,network=args.network)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(
        result,ensure_ascii=False,indent=2,sort_keys=True)+"\n",
        encoding="utf-8")
    print(json.dumps({k:v for k,v in result.items() if k!="records"},
                     ensure_ascii=False))


if __name__=="__main__":
    main()
