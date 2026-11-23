#!/usr/bin/env python3
"""Stage two firstparty broadcaster marks with exact independent SHA proof.

BeGood general station-network mark and BloodStream owner red-drop favicon
are specifically marked as publisher brands, not 80s channel-only artwork.
Repeat-download original image bytes, compare immutable source fingerprints
from pinned audit #45261679936, and stage PNGs and unsigned v8 JSON only.
"""
from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path
from copy import deepcopy
from urllib.parse import urlsplit
from audit_v8_begood_bloodstream_owner_images import SOURCES,safe_svg_to_png
from audit_open_radio_artwork_inventory import _request,inspect_bytes,MAX_IMAGE

ROOT=Path(__file__).resolve().parents[2]
BEFORE=ROOT/"radio-catalog-lab/full-staging/UNSIGNED-radio-v8-64-official-sha-logos-20261123.json"
AFTER=ROOT/"radio-catalog-lab/full-staging/UNSIGNED-radio-v8-66-official-sha-logos-20261123.json"
ART=ROOT/"grossesondes/radio-test-v2/artwork/staging-begood-bloodstream-v8"
PREFIX=("https://raw.githubusercontent.com/Sarogal/Ondes-Catalogues/"
        "feature/go-radio-v8-metalon-3-logos-20261123/"
        "grossesondes/radio-test-v2/artwork/staging-begood-bloodstream-v8/")
SHA={
"go-station-000142":"a54cd85a72a4d9d707eb95e9df120aa71f6aaa370073286f3e0f39e8183722a2",
"go-station-000092":"c9f28689815b32b6ff9e9f7b867a49309d6e3a566d81aa09e001e94abd9857fe",
}
def main():
    ap=argparse.ArgumentParser();ap.add_argument("--artifact-root",type=Path,required=True);args=ap.parse_args()
    if AFTER.exists() or ART.exists():raise ValueError("Refuse immutable candidate overwrite")
    proof_files=list(args.artifact_root.rglob("online.json"))
    if len(proof_files)!=1 or proof_files[0].stat().st_size>90000:
        raise ValueError("Missing single pinned owner image evidence artifact")
    proof=json.loads(proof_files[0].read_bytes())
    if (proof.get("scope")!="GO_V8_TWO_OWNER_BRAND_BEG0OD_BLOODSTREAM_READ_ONLY"
        or proof.get("targets")!=2 or proof.get("shas_verified")!=2
        or proof.get("owner_page_matches")!=2
        or proof.get("signed") is not False or proof.get("published") is not False):
        raise ValueError("Unverified firstparty brand report")
    rows={r["id"]:r for r in proof["rows"]}
    if set(rows)!=set(SOURCES) or set(rows)!=set(SHA):
        raise ValueError("Unexpected station in report")
    old=json.loads(BEFORE.read_bytes())
    active=[s for s in old["stations"] if s["status"]["state"]=="active"]
    if (old["release_sequence"]!=8 or len(old["stations"])!=296 or
        len(old["tombstones"])!=24 or len(active)!=285 or
        sum(s["logo"] is None for s in active)!=32):
        raise ValueError("Wrong audited 64-new-sha predecessor")
    original={x["go_station_id"]:x for x in old["stations"]}
    staged={}
    for sid,digest in SHA.items():
        name,home,stream,page,url,host,fmt,kind=SOURCES[sid]
        station=original[sid];row=rows[sid]
        if (station["display_name"]!=name or station["homepage"]!=home
            or station["logo"] is not None or station["status"]["state"]!="active"
            or not any(stream in t["url"] for t in station["streams"])
            or row["station"]!=name or row["publisher_page"]!=page or
            row["image_url"]!=url or row["asset_kind"]!=kind
            or row["owner_page_match"] is not True or row["source_verified"] is not True
            or row["png_verified"] is not True or row["status"]!="PUBLISHER_OWNED_BRAND_ORIGINAL_SHA_VERIFIED"
            or row["png_metadata"]["sha256"]!=digest or row["signed"] is not False
            or row["published"] is not False):
            raise ValueError("Unapproved publisher image/station identity: "+sid)
        content,mime,final=_request(url,max_bytes=MAX_IMAGE,accept=fmt)
        if urlsplit(final).hostname!=host:raise ValueError("Unexpected image host")
        if hashlib.sha256(content).hexdigest()!=row["original_sha256"] or len(content)!=row["original_bytes"]:
            raise ValueError("Owner original bytes differ from read-only audit")
        if fmt=="image/svg+xml":
            if mime not in ("image/svg+xml","application/octet-stream","text/xml","application/xml",""):
                raise ValueError("Original owner vector MIME changed")
            png=safe_svg_to_png(content)
        else:
            if mime not in ("image/png","application/octet-stream",""):
                raise ValueError("Original owner PNG MIME changed")
            png=content
        meta=inspect_bytes(png,content_type="image/png")
        if meta!=row["png_metadata"] or meta["sha256"]!=digest:
            raise ValueError("Derived bytes image SHA did not match validated audit")
        staged[sid]=(png,meta)
    if len({m["sha256"] for _,m in staged.values()})!=2:
        raise ValueError("Repeated logo object")
    updated=deepcopy(old)
    updated["generated_at"]="2026-11-23T20:48:00Z"
    for s in updated["stations"]:
        sid=s["go_station_id"]
        if sid not in staged:continue
        _,m=staged[sid]
        s["logo"]={
            "asset_id":"sha256:"+m["sha256"],"sha256":m["sha256"],"revision":1,
            "url":PREFIX+m["sha256"]+".png","byte_size":m["byte_size"],
            "width":m["width"],"height":m["height"],"mime_type":"image/png"
        }
    if updated["tombstones"]!=old["tombstones"]:
        raise ValueError("Redirects/tombstones changed")
    assert sum(s["status"]["state"]=="active" and s["logo"] is not None for s in updated["stations"])==255
    assert sum(s["status"]["state"]=="active" and s["logo"] is None for s in updated["stations"])==30
    for s in updated["stations"]:
        before=original[s["go_station_id"]]
        if s["go_station_id"] in SHA:
            blank=deepcopy(s);blank["logo"]=None
            if blank!=before:raise ValueError("Changed more than approved radio logo")
        elif s!=before:raise ValueError("Changed unrelated radio")
    ART.mkdir(parents=True,exist_ok=False)
    for png,m in staged.values():
        (ART/(m["sha256"]+".png")).write_bytes(png)
    AFTER.write_text(json.dumps(updated,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({
        "result":"GO_TEST_V8_66_2_OWNER_BRANDS_STAGED_UNSIGNED",
        "new_sha_logos":2,"total_new_sha_logos":66,
        "active":285,"with_logo":255,"without_logo":30,"redirects":24,
        "signed":False,"published":False,"signed_v7_untouched":True
    },sort_keys=True))
if __name__=="__main__":main()
