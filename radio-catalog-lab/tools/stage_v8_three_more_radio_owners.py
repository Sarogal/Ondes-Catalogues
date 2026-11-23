#!/usr/bin/env python3
"""Stage three owner-provided station artwork originals verified in Actions #45196470571.

idobi Howl original did not pass byte download and is explicitly excluded.
Rocker Radio owner logo, NuMetal JubsTones channel and SFTD publisher radio art.
No signed TEST pointer, production, main, or existing radio metadata edited.
"""
from __future__ import annotations
import argparse,hashlib,json
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlsplit
from audit_v8_four_rocker_idobi_zeno_sftd import SOURCES
from audit_open_radio_artwork_inventory import _request,inspect_bytes,MAX_IMAGE

ROOT=Path(__file__).resolve().parents[2]
BEFORE=ROOT/"radio-catalog-lab/full-staging/UNSIGNED-radio-v8-57-official-sha-logos-20261123.json"
AFTER=ROOT/"radio-catalog-lab/full-staging/UNSIGNED-radio-v8-60-official-sha-logos-20261123.json"
ASSETS=ROOT/"grossesondes/radio-test-v2/artwork/staging-three-radio-owners-v8"
PREFIX=("https://raw.githubusercontent.com/Sarogal/Ondes-Catalogues/"
        "feature/go-radio-v8-metalon-3-logos-20261123/"
        "grossesondes/radio-test-v2/artwork/staging-three-radio-owners-v8/")
SHA={
"go-station-000062":"337088616cea39e471d62b67a41af7b146b500d44649af734d9e115eda8c44bb",
"go-station-000240":"d9cd78641414826da5700ae39218837b892c1e72fe0f272f56a6b7802631b447",
"go-station-000245":"78a3071190ffe4fd9eed71b6beeb80e69f70fdc3d2ca9f39cd784d4d300e6a08",
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
    if (proof.get("scope")!="GO_V8_FOUR_ADDITIONAL_INDEPENDENT_RADIO_ORIGINALS_AUDIT"
       or proof.get("count")!=4 or proof.get("shas_verified")!=3
       or proof.get("html_matches")!=2 or proof.get("published") is not False
       or proof.get("signed") is not False):
        raise ValueError("Pinned image evidence does not meet approved profile")
    records={x["id"]:x for x in proof["records"]}
    if set(records)!=set(SOURCES) or set(SHA)!=(set(records)-{"go-station-000155"}):
        raise ValueError("Unreviewed candidate station IDs")
    if records["go-station-000155"].get("image_sha_verified") is not False:
        raise ValueError("Explicitly reject idobi Howl original without verified SHA")
    old=json.loads(BEFORE.read_bytes())
    active=[x for x in old["stations"] if x["status"]["state"]=="active"]
    if old["release_sequence"]!=8 or len(old["stations"])!=296 or len(old["tombstones"])!=24 or len(active)!=285 or sum(x["logo"] is None for x in active)!=39:
        raise ValueError("Expected previous approved 57-logo version")
    original={x["go_station_id"]:x for x in old["stations"]}
    newbytes={}
    for sid,sha in SHA.items():
        name,home,stream,page,url,host=SOURCES[sid]
        st=original[sid];r=records[sid]
        if (st["logo"] is not None or st["display_name"]!=name or st["homepage"]!=home
           or st["status"]["state"]!="active" or not any(stream in s["url"] for s in st["streams"])
           or r.get("name")!=name or r.get("publisher_page")!=page or r.get("publisher_image")!=url
           or (sid not in {"go-station-000240","go-station-000245"} and r.get("page_image_match") is not True) or r.get("image_sha_verified") is not True
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
    if len({row["sha256"] for row,_ in newbytes.values()})!=3:
        raise ValueError("Repeated generic source image")
    new=deepcopy(old);new["generated_at"]="2026-11-23T14:44:00Z"
    for station in new["stations"]:
        sid=station["go_station_id"]
        if sid not in newbytes:continue
        row,_=newbytes[sid];sha=row["sha256"]
        station["logo"]={"asset_id":"sha256:"+sha,"sha256":sha,"revision":1,
          "url":PREFIX+sha+"."+EXT[row["mime_type"]],
          "byte_size":row["byte_size"],"width":row["width"],
          "height":row["height"],"mime_type":row["mime_type"]}
    assert new["tombstones"]==old["tombstones"]
    assert sum(s["status"]["state"]=="active" and s["logo"] is None for s in new["stations"])==36
    assert sum(s["status"]["state"]=="active" and s["logo"] is not None for s in new["stations"])==249
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
    print(json.dumps({"result":"GO_V8_ROCKER_NUMETAL_SFTD_SHA_LOGOS_STAGED_UNSIGNED",
        "new_originals":3,"total_new_logo_sha_assets":60,
        "active_radios":285,"with_logo":249,"without_logo":36,
        "redirects":24,"signed":False,"published":False,
        "signed_test_v7_pointer_unchanged":True},sort_keys=True))
if __name__=="__main__":main()
