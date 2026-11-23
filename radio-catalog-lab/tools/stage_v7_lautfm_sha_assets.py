#!/usr/bin/env python3
"""Stage 14 first-party laut.fm SHA images and an UNSIGNED v7 logo-enhanced draft.

Input: pinned public Actions #45127799794 artifact, which authenticated each
station identity via its official laut.fm API and verified its image SHA.
Fetch the exact bytes a SECOND time; reject any missing/changed object or
untrusted host. Write ONLY development-branch files. No signing, no pointer,
no APK change and no public TEST branch publication.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse

from audit_open_radio_artwork_inventory import _request, inspect_bytes, MAX_IMAGE
from audit_v7_lautfm_official_logos import radio_slug, source_stations

ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/"radio-catalog-lab/full-staging/UNSIGNED-radio-v7-13-programs-dedupe-20261123.json"
TARGET=ROOT/"radio-catalog-lab/full-staging/UNSIGNED-radio-v7-13-programs-lautfm-14-20261123.json"
OBJROOT=ROOT/"grossesondes/radio-test-v2/artwork/staging-lautfm-v7"
RAW_PREFIX=("https://raw.githubusercontent.com/Sarogal/Ondes-Catalogues/"
            "feature/go-radio-v7-13-dedupe-20261123/"
            "grossesondes/radio-test-v2/artwork/staging-lautfm-v7/")
EXT={"image/jpeg":"jpg","image/png":"png","image/webp":"webp"}
TRUSTED_HOSTS={"assets.laut.fm","api.laut.fm"}


def read_evidence(folder:Path)->list[dict]:
    files=[p for p in folder.rglob("lautfm-v7-verified-evidence.json")
           if p.is_file() and not p.is_symlink()]
    if len(files)!=1 or files[0].stat().st_size>200*1024:
        raise ValueError("Expected exactly one small original LAUT audit evidence file")
    obj=json.loads(files[0].read_text(encoding="utf-8"))
    if (obj.get("scope")!="TEST_V7_LAUTFM_14_FIRST_PARTY_LOGOS_READ_ONLY"
            or obj.get("stations")!=14
            or obj.get("official_metadata_verified")!=14
            or obj.get("logo_bytes_verified")!=14
            or obj.get("catalog_modified") is not False
            or obj.get("publication_allowed") is not False
            or len(obj.get("records",[]))!=14):
        raise ValueError("Incomplete trusted first-party source evidence")
    return obj["records"]


def main()->None:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--artifact-root",type=Path,required=True)
    args=p.parse_args()
    if TARGET.exists() or OBJROOT.exists():
        raise ValueError("Refusing to overwrite already-staged unsigned candidate or objects")

    old=json.loads(BASE.read_text(encoding="utf-8"))
    if (old.get("release_sequence")!=7 or len(old["stations"])!=296
            or len(old["tombstones"])!=24 or
            sum(s["logo"] is not None for s in old["stations"])!=175):
        raise ValueError("Unexpected base candidate for 14-logo enrichment")
    targets={s["go_station_id"]:(s,slug) for s,slug in source_stations()}
    if len(targets)!=14:
        raise ValueError("Audit station set drift")
    evidence=read_evidence(args.artifact_root.resolve())
    unique={}
    for x in evidence:
        goid=x.get("go_station_id")
        if goid not in targets or goid in unique:
            raise ValueError("Extra/duplicate station in first-party evidence")
        source,slug=targets[goid]
        url=x.get("official_logo_url")
        if (x.get("status")!="OFFICIAL_LAUTFM_IMAGE_SHA_VERIFIED"
                or x.get("approval_for_publication") is not False
                or x.get("verified_stream_slug")!=slug
                or x.get("metadata_name_matches_slug") is not True
                or x.get("official_station_api")!="https://api.laut.fm/station/"+slug
                or not isinstance(url,str)
                or urlparse(url).scheme!="https"
                or urlparse(url).hostname not in TRUSTED_HOSTS
                or x.get("mime_type") not in EXT
                or not isinstance(x.get("verified_sha256"),str)
                or len(x["verified_sha256"])!=64):
            raise ValueError("Bad official identity or missing SHA: "+str(goid))
        raw,content_type,final=_request(
            url,max_bytes=MAX_IMAGE,accept="image/png,image/jpeg,image/webp")
        if urlparse(final).hostname not in TRUSTED_HOSTS:
            raise ValueError("Untrusted logo CDN redirect for "+goid)
        actual=inspect_bytes(raw,content_type=content_type)
        expected={
            "sha256":x["verified_sha256"],
            "mime_type":x["mime_type"],
            "byte_size":x["byte_size"],
            "width":x["width"],
            "height":x["height"],
        }
        if actual!=expected or hashlib.sha256(raw).hexdigest()!=x["verified_sha256"]:
            raise ValueError("Official LAUT image bytes changed since audit for "+goid)
        unique[goid]=(x,raw)

    if set(unique)!=set(targets):
        raise ValueError("Incomplete signed-LAUT station list")
    new=deepcopy(old)
    changed=[]
    for station in new["stations"]:
        goid=station["go_station_id"]
        if goid not in unique:
            continue
        if station["logo"] is not None or station["status"]["state"]!="active":
            raise ValueError("Refusing to replace pre-existing station logo")
        x,blob=unique[goid]
        sha=x["verified_sha256"]
        ext=EXT[x["mime_type"]]
        station["logo"]={
            "asset_id":"sha256:"+sha,
            "sha256":sha,
            "revision":1,
            "url":RAW_PREFIX+sha+"."+ext,
            "byte_size":len(blob),
            "width":x["width"],
            "height":x["height"],
            "mime_type":x["mime_type"],
        }
        changed.append(goid)
    if (len(changed)!=14
            or sum(s["logo"] is not None for s in new["stations"])!=189
            or sum(s["status"]["state"]=="active" and s["logo"] is not None
                   for s in new["stations"])!=184
            or new["tombstones"]!=old["tombstones"]):
        raise ValueError("Unexpected change to v7 station identities or logo coverage")
    original={s["go_station_id"]:s for s in old["stations"]}
    for station in new["stations"]:
        if station["go_station_id"] in unique:
            expected=deepcopy(station)
            expected["logo"]=None
            if expected!=original[station["go_station_id"]]:
                raise ValueError("A station changed beyond its official LAUT logo")
        else:
            if station!=original[station["go_station_id"]]:
                raise ValueError("Unrelated station changed")

    # All evidence verified before creating ANY files in the output tree.
    hashes=set()
    for goid,(x,blob) in unique.items():
        sha=x["verified_sha256"]
        ext=EXT[x["mime_type"]]
        dest=OBJROOT/(sha+"."+ext)
        if dest.exists():
            raise ValueError("Unexpected pre-existing SHA object")
        dest.parent.mkdir(parents=True,exist_ok=True)
        dest.write_bytes(blob)
        hashes.add(dest.name)
    if len(hashes)!=14:
        raise ValueError("Unexpected duplicate image SHA among independent station assets")
    TARGET.parent.mkdir(parents=True,exist_ok=True)
    TARGET.write_text(json.dumps(new,ensure_ascii=False,indent=2)+"\n",
                      encoding="utf-8")
    print(json.dumps({
        "result":"GO_RADIO_V7_LAUTFM_14_LOGOS_STAGED_UNSIGNED",
        "official_sha_objects":14,
        "new_station_logos":14,
        "station_records":296,
        "active_stations":285,
        "total_station_logos":189,
        "active_station_logos":184,
        "active_without_logo":101,
        "old_TEST_v6_pointer_changed":False,
        "signed":False,
        "publication_allowed":False,
    },sort_keys=True))


if __name__=="__main__":
    main()
