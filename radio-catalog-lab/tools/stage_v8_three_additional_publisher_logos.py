#!/usr/bin/env python3
"""Stage 3 individually verified publisher logos onto MetalON unsigned v8.

Inputs pinned to read-only Actions #45163309601 evidence. Radio stations:
Rockaxis Radio, RSTLSS, Regenbogen 2 Metal (now links to Rock FM Metal).
The NTS The Pit image did not pass due to a timed-out source and is excluded.

Exactly 3 source images downloaded twice and SHA-256 checked; only 3 null
station logos added and one unsigned v8 candidate written to development.
No signed TEST v7 pointer, private key, main, Play Store or production edits.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

from audit_open_radio_artwork_inventory import _request,inspect_bytes,MAX_IMAGE
from audit_v8_four_official_station_logos import STATIONS

ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/"radio-catalog-lab/full-staging/UNSIGNED-radio-v8-metalon-3-official-logos-20261123.json"
OUTPUT=ROOT/"radio-catalog-lab/full-staging/UNSIGNED-radio-v8-metalon-3-independent-3-20261123.json"
ASSETS=ROOT/"grossesondes/radio-test-v2/artwork/staging-independent-v8"
PREFIX=("https://raw.githubusercontent.com/Sarogal/Ondes-Catalogues/"
        "feature/go-radio-v8-metalon-3-logos-20261123/"
        "grossesondes/radio-test-v2/artwork/staging-independent-v8/")
EXPECTED={
    "go-station-000006":"fdf5abb4bfb0837aa5ace1b1ebcd486d25eeee9ca976fbecdd7c0389117dcd99",
    "go-station-000091":"f81d40082d032ac3511f979906ac6d71e025dd83b1729ab958d05668b6e7b175",
    "go-station-000101":"6053589f3889f33ab799c196162c49436f11d24a63bbefebcc9d18bda1983b6d",
}
EXT={"image/png":"png","image/jpeg":"jpg","image/webp":"webp"}


def read_evidence(root:Path)->list[dict]:
    files=[p for p in root.rglob("four-official-network.json")
           if p.is_file() and not p.is_symlink()]
    if len(files)!=1 or files[0].stat().st_size>100*1024:
        raise ValueError("Missing original four-station SHA audit")
    data=json.loads(files[0].read_text(encoding="utf-8"))
    if (data.get("scope")!="GO_V8_FOUR_FIRSTPARTY_STATION_IMAGES_READ_ONLY"
            or data.get("audited_station_count")!=4
            or data.get("image_sha_verified_count")!=3
            or data.get("publication_allowed") is not False
            or data.get("catalog_mutated") is not False):
        raise ValueError("Untrusted/incomplete station identity evidence")
    bad=[x for x in data["records"] if x["go_station_id"]=="go-station-000042"]
    if len(bad)!=1 or bad[0].get("image_bytes_verified") is not False:
        raise ValueError("Unverified NTS artwork must remain excluded")
    return data["records"]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--artifact-root",type=Path,required=True)
    a=p.parse_args()
    if OUTPUT.exists() or ASSETS.exists():
        raise ValueError("Refusing to overwrite already staged v8 assets/catalog")
    old=json.loads(SOURCE.read_text(encoding="utf-8"))
    if (old["release_sequence"]!=8 or len(old["stations"])!=296
            or len(old["tombstones"])!=24
            or sum(x["status"]["state"]=="active" and x["logo"] is None
                   for x in old["stations"])!=93):
        raise ValueError("Expected prior unsigned v8 3-MetalON candidate")
    prior={x["go_station_id"]:x for x in old["stations"]}
    evidence=read_evidence(a.artifact_root.resolve())
    verified={}
    for row in evidence:
        goid=row.get("go_station_id")
        if goid not in EXPECTED:
            continue
        canonical=STATIONS[goid]
        st=prior[goid]
        if (row.get("station_name")!=canonical["name"]
                or row.get("station_name")!=st["display_name"]
                or row.get("publisher_page")!=canonical["official_page"]
                or row.get("browser_observed_station_image")!=canonical["image_url"]
                or row.get("image_bytes_verified") is not True
                or row.get("status")!="FIRST_PARTY_IMAGE_SHA_VERIFIED_PENDING_EDITORIAL"
                or row.get("sha256")!=EXPECTED[goid]
                or row.get("mime_type") not in EXT
                or row.get("publication_allowed") is not False
                or st["logo"] is not None or st["status"]["state"]!="active"):
            raise ValueError("Untrusted official page, station, or SHA association")
        image_url=canonical["image_url"]
        data,mime,final=_request(image_url,max_bytes=MAX_IMAGE,
                                 accept="image/png,image/jpeg,image/webp")
        if urlsplit(final).hostname!=urlsplit(image_url).hostname:
            raise ValueError("Official logo CDN host changed")
        metadata=inspect_bytes(data,content_type=mime)
        expected={k:row[k] for k in
                  ("sha256","byte_size","mime_type","width","height")}
        if metadata!=expected or hashlib.sha256(data).hexdigest()!=EXPECTED[goid]:
            raise ValueError("Station original image mutated since first official audit")
        verified[goid]=(row,data)
    if set(verified)!=set(EXPECTED):
        raise ValueError("Only three strictly verified distinct station logos may stage")
    if len({record["sha256"] for record,_ in verified.values()})!=3:
        raise ValueError("Distinct station brands returned generic image SHA")

    new=deepcopy(old)
    new["generated_at"]="2026-11-23T11:20:00Z"
    for st in new["stations"]:
        if st["go_station_id"] not in verified:
            continue
        row,data=verified[st["go_station_id"]]
        sha=row["sha256"]
        ext=EXT[row["mime_type"]]
        st["logo"]={
            "asset_id":"sha256:"+sha,
            "sha256":sha,"revision":1,
            "url":PREFIX+sha+"."+ext,
            "byte_size":row["byte_size"],
            "width":row["width"],
            "height":row["height"],
            "mime_type":row["mime_type"]
        }
    if (len(new["stations"])!=296 or new["tombstones"]!=old["tombstones"]
            or sum(x["status"]["state"]=="active" and x["logo"] is None
                   for x in new["stations"])!=90
            or sum(x["status"]["state"]=="active" and x["logo"] is not None
                   for x in new["stations"])!=195):
        raise ValueError("New 3-logo diff changed unrelated v8 data")
    for s in new["stations"]:
        old_station=prior[s["go_station_id"]]
        if s["go_station_id"] in EXPECTED:
            without=deepcopy(s)
            without["logo"]=None
            if without!=old_station:
                raise ValueError("Unrelated station metadata changed")
        elif s!=old_station:
            raise ValueError("Unrelated radio changed")
    for row,data in verified.values():
        sha=row["sha256"]
        path=ASSETS/(sha+"."+EXT[row["mime_type"]])
        path.parent.mkdir(parents=True,exist_ok=True)
        if path.exists():
            raise ValueError("Refusing image overwrite")
        path.write_bytes(data)
    OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    OUTPUT.write_text(json.dumps(new,ensure_ascii=False,indent=2)+"\n",
                      encoding="utf-8")
    print(json.dumps({
        "result":"GO_V8_3_ADDITIONAL_FIRSTPARTY_LOGOS_STAGED_UNSIGNED",
        "additional_sha_objects":3,
        "total_new_logo_references_v8":6,
        "active_station_count":285,
        "active_with_logo":195,
        "active_without_logo":90,
        "redirections_preserved":24,
        "signed":False,
        "active_test_v7_untouched":True
    },sort_keys=True))


if __name__=="__main__":
    main()
