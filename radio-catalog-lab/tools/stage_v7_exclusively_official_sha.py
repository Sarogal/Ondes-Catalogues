#!/usr/bin/env python3
"""Stage 5 official YouRadio station tiles (4 unique SHA objects) into unsigned v7.

The two genuinely different Led Zeppelin programs are allowed to share only
their broadcaster's EXPLICIT official artist tile, not a genre placeholder.
Consume first-party browser-verified YouRadio evidence from read-only CI,
download byte-identical originals again from manager.uber.radio, and write
only development-branch SHA objects plus one more unsigned v7 candidate.

No keys accessed. No signed pointer, APK, main, production or TEST edits.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse

from audit_open_radio_artwork_inventory import _request,inspect_bytes,MAX_IMAGE
from audit_v7_exclusively_broadcaster_images import BROADCASTER

ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/"radio-catalog-lab/full-staging/UNSIGNED-radio-v7-13-programs-lautfm-14-20261123.json"
OUTPUT=ROOT/"radio-catalog-lab/full-staging/UNSIGNED-radio-v7-13-programs-lautfm-14-exclusive-5-20261123.json"
ASSETS=ROOT/"grossesondes/radio-test-v2/artwork/staging-exclusive-v7"
BASE_URL=("https://raw.githubusercontent.com/Sarogal/Ondes-Catalogues/"
          "feature/go-radio-v7-13-dedupe-20261123/"
          "grossesondes/radio-test-v2/artwork/staging-exclusive-v7/")
EXT={"image/jpeg":"jpg","image/png":"png","image/webp":"webp"}
LEGITIMATE_SHARED={"go-station-000204","go-station-000274"}


def evidence(folder:Path)->list[dict]:
    paths=[p for p in folder.rglob("exclusive-four-network.json")
           if p.is_file() and not p.is_symlink()]
    if len(paths)!=1 or paths[0].stat().st_size>120*1024:
        raise ValueError("Missing unique pinned first-party image evidence")
    doc=json.loads(paths[0].read_text(encoding="utf-8"))
    if (doc.get("scope")!="TEST_V7_EXCLUSIVELY_5_BROADCASTER_ORIGINAL_TILES"
            or doc.get("requested_stations")!=5
            or doc.get("verified_station_logo_count")!=5
            or doc.get("verified_unique_sha_count")!=4
            or doc.get("shared_artist_pair_only") is not True
            or doc.get("publication_allowed") is not False):
        raise ValueError("Incomplete or unsafe official-source SHA evidence")
    return doc["records"]


def main()->None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root",type=Path,required=True)
    args=parser.parse_args()
    if OUTPUT.exists() or ASSETS.exists():
        raise ValueError("Refuse overwrite of any prior test-only staged assets/catalog")
    old=json.loads(SOURCE.read_text(encoding="utf-8"))
    if (old.get("release_sequence")!=7 or len(old.get("stations",[]))!=296
            or len(old["tombstones"])!=24
            or sum(s["logo"] is not None for s in old["stations"])!=189):
        raise ValueError("Base 14-LAUT unsigned v7 changed")
    old_rows={s["go_station_id"]:s for s in old["stations"]}
    rows=evidence(args.artifact_root.resolve())
    if len(rows)!=5:
        raise ValueError("Exactly 5 original broadcaster images expected")
    downloaded={}
    by_digest={}
    for item in rows:
        goid=item.get("go_station_id")
        if goid not in BROADCASTER or goid in downloaded:
            raise ValueError("Unknown or duplicate Exclusive GO ID")
        slug,page,image=BROADCASTER[goid]
        if (item.get("stream_program_slug")!=slug
                or item.get("broadcaster_station_page")!=page
                or item.get("broadcaster_station_image_url")!=image
                or item.get("station_dom_verified_in_browser") is not True
                or item.get("status") not in {
                    "OFFICIAL_IMAGE_BYTES_VERIFIED",
                    "OFFICIAL_SHARED_ARTIST_STATION_TILE_VERIFIED"}
                or item.get("editorial_publication_approved") is not False
                or item.get("mime_type") not in EXT
                or item.get("byte_size",0)<256):
            raise ValueError("Image/program identity or source changed")
        previous=old_rows[goid]
        if previous["status"]["state"]!="active" or previous["logo"] is not None:
            raise ValueError("Previously signed/programmed station logo overwrite")
        if not any("/"+slug+"/" in s["url"].lower() and
                   "streaming.exclusive.radio" in s["url"].lower()
                   for s in previous["streams"]):
            raise ValueError("Source image mismatched the program's audio slug")
        if urlparse(image).hostname!="manager.uber.radio":
            raise ValueError("Off-domain image data refused")
        bytes_,mime,final=_request(
            image,max_bytes=MAX_IMAGE,accept="image/png,image/jpeg,image/webp")
        if urlparse(final).hostname!="manager.uber.radio":
            raise ValueError("Official image redirected away from known broadcaster CDN")
        meta=inspect_bytes(bytes_,content_type=mime)
        required={k:item[k] for k in
                  ("sha256","mime_type","byte_size","width","height")}
        if meta!=required or hashlib.sha256(bytes_).hexdigest()!=item["sha256"]:
            raise ValueError("Official tile bytes/format/size mutated since independent CI audit")
        downloaded[goid]=(item,bytes_)
        by_digest.setdefault(item["sha256"],[]).append(goid)

    if set(downloaded)!=set(BROADCASTER) or len(by_digest)!=4:
        raise ValueError("Five official station image records / four SHA objects required")
    if any(len(v)>1 and set(v)!=LEGITIMATE_SHARED for v in by_digest.values()):
        raise ValueError("Unrelated programs reused a generic SHA placeholder")
    if not any(set(v)==LEGITIMATE_SHARED for v in by_digest.values()):
        raise ValueError("Led Zeppelin shared official artist tile not corroborated")

    doc=deepcopy(old)
    new_by_id={s["go_station_id"]:s for s in doc["stations"]}
    for goid,(record,body) in downloaded.items():
        st=new_by_id[goid]
        sha=record["sha256"]
        ext=EXT[record["mime_type"]]
        st["logo"]={
            "asset_id":"sha256:"+sha,"sha256":sha,"revision":1,
            "url":BASE_URL+sha+"."+ext,
            "byte_size":record["byte_size"],
            "width":record["width"],"height":record["height"],
            "mime_type":record["mime_type"],
        }
    if (len(doc["stations"])!=296 or len(doc["tombstones"])!=24
            or sum(s["status"]["state"]=="active" for s in doc["stations"])!=285
            or sum(s["logo"] is not None for s in doc["stations"])!=194
            or sum(s["status"]["state"]=="active" and s["logo"] is not None
                   for s in doc["stations"])!=189):
        raise ValueError("Unexpected v7 enriched catalog counts")
    for goid,original in old_rows.items():
        edited=new_by_id[goid]
        if goid in BROADCASTER:
            no_logo=deepcopy(edited)
            no_logo["logo"]=None
            if no_logo!=original:
                raise ValueError("Station mutation other than signed-logo metadata")
        elif edited!=original:
            raise ValueError("Unrelated radio changed")

    # Generate four content-addressed objects; shared Led Zeppelin SHA stored
    # ONCE and referenced by both distinct official program entries.
    for sha,station_ids in by_digest.items():
        item,blob=downloaded[station_ids[0]]
        ext=EXT[item["mime_type"]]
        target=ASSETS/(sha+"."+ext)
        target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists():
            raise ValueError("Refusing to replace SHA blob")
        target.write_bytes(blob)
    OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    OUTPUT.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+"\n",
                      encoding="utf-8")
    print(json.dumps({
        "result":"GO_RADIO_V7_EXCLUSIVE_5_LOGOS_4_SHA_STAGED_UNSIGNED",
        "new_station_logo_descriptors":5,
        "new_sha_objects":4,
        "active_stations":285,
        "total_station_logo_descriptors":194,
        "active_station_logo_descriptors":189,
        "active_without_logo":96,
        "existing_redirects_preserved":24,
        "signed":False,
        "published":False
    },sort_keys=True))


if __name__=="__main__":
    main()
