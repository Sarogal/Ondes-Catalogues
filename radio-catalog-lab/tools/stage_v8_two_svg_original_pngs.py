#!/usr/bin/env python3
"""Stage original SVG-derived firstparty radio logos in experimental v8 only.

Verified original SVG bytes from owner + exact deterministic CairoSVG raster
SHA256 are checked twice. PNG assets are immutable. No signed pointer writes.
"""
from __future__ import annotations
import argparse,hashlib,json
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlsplit
from audit_v8_two_official_svg_logos import SOURCES,safe_svg_to_png
from audit_open_radio_artwork_inventory import _request,MAX_IMAGE,inspect_bytes

ROOT=Path(__file__).resolve().parents[2]
BEFORE=ROOT/"radio-catalog-lab/full-staging/UNSIGNED-radio-v8-62-official-sha-logos-20261123.json"
AFTER=ROOT/"radio-catalog-lab/full-staging/UNSIGNED-radio-v8-64-official-sha-logos-20261123.json"
ASSETS=ROOT/"grossesondes/radio-test-v2/artwork/staging-two-svg-rendered-v8"
PREFIX=("https://raw.githubusercontent.com/Sarogal/Ondes-Catalogues/"
        "feature/go-radio-v8-metalon-3-logos-20261123/"
        "grossesondes/radio-test-v2/artwork/staging-two-svg-rendered-v8/")
SHA={
"go-station-000038":"5f49e4ae99e21a23ffbfaa23b495137c108023265795b4be71ad377ed7fffe34",
"go-station-000157":"02c31c619f63eea5484b30a4eabf2387b5415df7d29e75296796c1cc13c5c435",
}
def main():
    p=argparse.ArgumentParser();p.add_argument("--artifact-root",type=Path,required=True);a=p.parse_args()
    if AFTER.exists() or ASSETS.exists():raise ValueError("Refusing overwrite of immutable experimental asset")
    files=list(a.artifact_root.rglob("online.json"))
    if len(files)!=1 or files[0].stat().st_size>90000:raise ValueError("Single verified prior audit needed")
    proof=json.loads(files[0].read_bytes())
    if (proof.get("scope")!="GO_V8_TWO_OFFICIAL_SVG_RADIO_LOGOS_SAFE_PNG_READ_ONLY"
       or proof.get("targets")!=2 or proof.get("original_svg_verified")!=2
       or proof.get("derived_png_verified")!=2 or proof.get("owner_page_matches")!=1
       or proof.get("signed") is not False or proof.get("published") is not False):
        raise ValueError("Wrong audited original SVG source evidence")
    rows={r["id"]:r for r in proof["rows"]}
    if set(rows)!=set(SHA) or set(SHA)!=set(SOURCES):raise ValueError("Original station ID mismatch")
    old=json.loads(BEFORE.read_bytes())
    active=[s for s in old["stations"] if s["status"]["state"]=="active"]
    if old["release_sequence"]!=8 or len(old["stations"])!=296 or len(old["tombstones"])!=24 or len(active)!=285 or sum(s["logo"] is None for s in active)!=34:
        raise ValueError("Expected fully QA verified 62 image v8 predecessor")
    originals={s["go_station_id"]:s for s in old["stations"]}
    pngs={}
    for sid,sha in SHA.items():
        name,home,stream,page,url,host=SOURCES[sid]
        station=originals[sid];row=rows[sid]
        if (station["logo"] is not None or station["status"]["state"]!="active"
            or station["display_name"]!=name or station["homepage"]!=home
            or not any(stream in t["url"] for t in station["streams"])
            or row["station_name"]!=name or row["publisher_page"]!=page or row["original_svg_url"]!=url
            or row["verified_svg"] is not True or row["verified_png"] is not True
            or row["status"]!="OWNER_ORIGINAL_SVG_SAFE_RASTER_PNG_SHA_VERIFIED"
            or row["rendered_png"]["sha256"]!=sha or row["signed"] is not False or row["published"] is not False
            or (sid=="go-station-000038" and row["source_page_match"] is not True)):
            raise ValueError("Unapproved vector logo original/station metadata: "+sid)
        blob,mime,final=_request(url,max_bytes=MAX_IMAGE,accept="image/svg+xml")
        if mime not in ("image/svg+xml","application/octet-stream","text/xml","application/xml","") or urlsplit(final).hostname!=host:
            raise ValueError("Original broadcaster SVG host changed")
        if hashlib.sha256(blob).hexdigest()!=row["original_svg_sha256"] or len(blob)!=row["original_svg_byte_size"]:
            raise ValueError("Original broadcaster SVG has changed")
        png=safe_svg_to_png(blob);meta=inspect_bytes(png,content_type="image/png")
        if meta!=row["rendered_png"] or meta["sha256"]!=sha:raise ValueError("PNG renderer changed original SHA")
        pngs[sid]=(png,meta)
    if len({r["sha256"] for _,r in pngs.values()})!=2:raise ValueError("Repeated generic image")
    updated=deepcopy(old);updated["generated_at"]="2026-11-23T16:28:00Z"
    for station in updated["stations"]:
        sid=station["go_station_id"]
        if sid not in pngs:continue
        _,img=pngs[sid];digest=img["sha256"]
        station["logo"]={"asset_id":"sha256:"+digest,"sha256":digest,
            "revision":1,"url":PREFIX+digest+".png",
            "byte_size":img["byte_size"],"width":img["width"],"height":img["height"],
            "mime_type":"image/png"}
    if updated["tombstones"]!=old["tombstones"]:raise ValueError("Tombstones changed")
    if sum(s["status"]["state"]=="active" and s["logo"] is None for s in updated["stations"])!=32:
        raise ValueError("Expected 32 without logo")
    if sum(s["status"]["state"]=="active" and s["logo"] is not None for s in updated["stations"])!=253:
        raise ValueError("Expected 253 with logo")
    for station in updated["stations"]:
        before=originals[station["go_station_id"]]
        if station["go_station_id"] in SHA:
            copy=deepcopy(station);copy["logo"]=None
            if copy!=before:raise ValueError("Unexpected identity or stream edit")
        elif station!=before:raise ValueError("Unrelated station edited")
    ASSETS.mkdir(parents=True,exist_ok=False)
    for png,info in pngs.values():(ASSETS/(info["sha256"]+".png")).write_bytes(png)
    AFTER.write_text(json.dumps(updated,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"result":"GO_TEST_V8_64_ORIGINAL_SVG_DERIVED_PNG_SHA_STAGED",
       "new_derived_pngs":2,"new_logo_objects_total":64,
       "active":285,"with_logo":253,"without_logo":32,"tombstones":24,
       "signed":False,"published":False,"signed_v7_unchanged":True},sort_keys=True))
if __name__=="__main__":main()
