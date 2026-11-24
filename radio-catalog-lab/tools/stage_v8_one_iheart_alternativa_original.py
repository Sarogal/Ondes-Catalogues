#!/usr/bin/env python3
"""Stage one official channel logo image verified by pinned audit #45195281033.

Only Alternativa by MIX iHeart direct station image can pass; four other candidates are excluded.
No signed TEST pointer, production, main, or existing radio metadata edited.
"""
from __future__ import annotations
import argparse,hashlib,json
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlsplit
from audit_v8_five_official_radio_logo_candidates import SOURCES
from audit_open_radio_artwork_inventory import _request,inspect_bytes,MAX_IMAGE

ROOT=Path(__file__).resolve().parents[2]
BEFORE=ROOT/"radio-catalog-lab/full-staging/UNSIGNED-radio-v8-56-official-sha-logos-20261123.json"
AFTER=ROOT/"radio-catalog-lab/full-staging/UNSIGNED-radio-v8-57-official-sha-logos-20261123.json"
ASSETS=ROOT/"grossesondes/radio-test-v2/artwork/staging-iheart-alternativa-v8"
PREFIX=("https://raw.githubusercontent.com/Sarogal/Ondes-Catalogues/"
        "feature/go-radio-v8-metalon-3-logos-20261123/"
        "grossesondes/radio-test-v2/artwork/staging-iheart-alternativa-v8/")
SHA={
"go-station-000032":"b5d1661cc531ea52dadf76d59012b16a68a2653dfdf08506de69128a0f621470",
}
EXT={"image/png":"png","image/jpeg":"jpg","image/webp":"webp"}
def main():
    p=argparse.ArgumentParser();p.add_argument("--artifact-root",type=Path,required=True)
    a=p.parse_args()
    if AFTER.exists() or ASSETS.exists():raise ValueError("Already staged / immutable asset overwrite prevented")
    reports=list(a.artifact_root.rglob("online.json"))
    if len(reports)!=1 or reports[0].stat().st_size>100000:
        raise ValueError("Expected one approved source report")
    proof=json.loads(reports[0].read_bytes())
    if (proof.get("scope")!="GO_V8_FIVE_OFFICIAL_RADIO_LOGO_IMAGES_READ_ONLY"
       or proof.get("count")!=5 or proof.get("shas_verified")!=1
       or proof.get("html_matches")!=1 or proof.get("published") is not False
       or proof.get("signed") is not False):
        raise ValueError("Pinned image evidence does not meet approved profile")
    records={x["id"]:x for x in proof["records"]}
    if set(records)!=set(SOURCES) or set(SHA)!={"go-station-000032"}:
        raise ValueError("Unreviewed candidate station IDs")
    if any(records[sid].get("image_sha_verified") is not False for sid in set(records)-set(SHA)):
        raise ValueError("Some unapproved source had a verified image")
    old=json.loads(BEFORE.read_bytes())
    active=[x for x in old["stations"] if x["status"]["state"]=="active"]
    if old["release_sequence"]!=8 or len(old["stations"])!=296 or len(old["tombstones"])!=24 or len(active)!=285 or sum(x["logo"] is None for x in active)!=40:
        raise ValueError("Expected previous approved 56-logo version")
    original={x["go_station_id"]:x for x in old["stations"]}
    newbytes={}
    for sid,sha in SHA.items():
        name,home,stream,page,url,host=SOURCES[sid]
        st=original[sid];r=records[sid]
        if (st["logo"] is not None or st["display_name"]!=name or st["homepage"]!=home
           or st["status"]["state"]!="active" or not any(stream in s["url"] for s in st["streams"])
           or r.get("name")!=name or r.get("publisher_page")!=page or r.get("publisher_image")!=url
           or (sid!="go-station-000032" and r.get("page_image_match") is not True) or r.get("image_sha_verified") is not True
           or r.get("status")!="FIRSTPARTY_ORIGINAL_SHA_VALIDATED"
           or r.get("sha256")!=sha or r.get("mime_type") not in EXT
           or r.get("signed") is not False or r.get("published") is not False):
            raise ValueError("Source/station identity failed "+sid)
        binary,mime,final=_request(url,max_bytes=MAX_IMAGE,accept="image/png,image/jpeg,image/webp")
        if urlsplit(final).hostname!=host:raise ValueError("Unexpected firstparty image redirect")
        inspected=inspect_bytes(binary,content_type=mime)
        if inspected!={k:r[k] for k in ("sha256","byte_size","width","height","mime_type")} or hashlib.sha256(binary).hexdigest()!=sha:
            raise ValueError("Changed original logo source SHA")
        newbytes[sid]=(r,binary)
    if len({row["sha256"] for row,_ in newbytes.values()})!=1:
        raise ValueError("Repeated generic source image")
    new=deepcopy(old);new["generated_at"]="2026-11-23T14:38:00Z"
    for station in new["stations"]:
        sid=station["go_station_id"]
        if sid not in newbytes:continue
        row,_=newbytes[sid];sha=row["sha256"]
        station["logo"]={"asset_id":"sha256:"+sha,"sha256":sha,"revision":1,
          "url":PREFIX+sha+"."+EXT[row["mime_type"]],
          "byte_size":row["byte_size"],"width":row["width"],
          "height":row["height"],"mime_type":row["mime_type"]}
    assert new["tombstones"]==old["tombstones"]
    assert sum(s["status"]["state"]=="active" and s["logo"] is None for s in new["stations"])==39
    assert sum(s["status"]["state"]=="active" and s["logo"] is not None for s in new["stations"])==246
    for s in new["stations"]:
        before=original[s["go_station_id"]]
        if s["go_station_id"] in newbytes:
            blank=deepcopy(s);blank["logo"]=None
            assert blank==before,"Unexpected field modified"
        else:assert s==before,"Other radio modified"
    ASSETS.mkdir(parents=True,exist_ok=False)
    for r,data in newbytes.values():
        (ASSETS/(r["sha256"]+"."+EXT[r["mime_type"]])).write_bytes(data)
    AFTER.write_text(json.dumps(new,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"result":"GO_V8_IHEART_ALTERNATIVA_CHANNEL_IMAGE_STAGED_UNSIGNED",
        "new_originals":1,"total_new_logo_sha_assets":57,
        "active_radios":285,"with_logo":246,"without_logo":39,
        "redirects":24,"signed":False,"published":False,
        "signed_test_v7_pointer_unchanged":True},sort_keys=True))
if __name__=="__main__":main()
