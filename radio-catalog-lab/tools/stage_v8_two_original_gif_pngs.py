#!/usr/bin/env python3
"""Stage 2 broadcaster-approved GIF art renderings as SHA256 PNGs in unsigned v8.

HardRadio mark and Radio-Drachenblut fire dragon OG image independently
re-fetched; source GIF SHA and exact derived PNG SHA verified vs pinned
read-only evidence (Pillow 11.3.0). V7 signed pointer is not changed.
"""
from __future__ import annotations
import argparse,hashlib,json
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlsplit
from audit_v8_two_gif_station_logos import SOURCES,convert
from audit_open_radio_artwork_inventory import _request,MAX_IMAGE,inspect_bytes

ROOT=Path(__file__).resolve().parents[2]
BEFORE=ROOT/"radio-catalog-lab/full-staging/UNSIGNED-radio-v8-60-official-sha-logos-20261123.json"
AFTER=ROOT/"radio-catalog-lab/full-staging/UNSIGNED-radio-v8-62-official-sha-logos-20261123.json"
ASSETS=ROOT/"grossesondes/radio-test-v2/artwork/staging-two-gif-rendered-v8"
PREFIX=("https://raw.githubusercontent.com/Sarogal/Ondes-Catalogues/"
        "feature/go-radio-v8-metalon-3-logos-20261123/"
        "grossesondes/radio-test-v2/artwork/staging-two-gif-rendered-v8/")
SHA={
"go-station-000146":"91f0f4ffd7f3495080a611127fcb5ea73df414a324f1c09ce88d12fa9fd9e9d0",
"go-station-000071":"eeffa8c023a4e31455ce256f0636a984688ee0154b4d786cbb2f7627cc6c8f02",
}
def main():
    p=argparse.ArgumentParser();p.add_argument("--artifact-root",type=Path,required=True);args=p.parse_args()
    if AFTER.exists() or ASSETS.exists():raise ValueError("Refusing to overwrite experimental SHA candidate")
    proofs=list(args.artifact_root.rglob("online.json"))
    if len(proofs)!=1 or proofs[0].stat().st_size>90000:raise ValueError("Exactly one original GIF proof report required")
    proof=json.loads(proofs[0].read_bytes())
    if (proof.get("scope")!="GO_V8_HARDRADIO_DRACHENBLUT_GIF_PNG_READ_ONLY"
       or proof.get("targets")!=2 or proof.get("original_gifs_verified")!=2
       or proof.get("derived_pngs_verified")!=2 or proof.get("publisher_page_matches")!=1
       or proof.get("published") is not False or proof.get("signed") is not False):
       raise ValueError("Unapproved GIF source audit")
    rows={r["go_station_id"]:r for r in proof["rows"]}
    if set(rows)!=set(SHA) or set(SHA)!=set(SOURCES):raise ValueError("Unexpected source names")
    old=json.loads(BEFORE.read_bytes())
    active=[s for s in old["stations"] if s["status"]["state"]=="active"]
    if old["release_sequence"]!=8 or len(old["stations"])!=296 or len(old["tombstones"])!=24 or len(active)!=285 or sum(s["logo"] is None for s in active)!=36:
        raise ValueError("Wrong signed v7-compatible unsigned predecessor")
    origin={s["go_station_id"]:s for s in old["stations"]}
    pngs={}
    for sid,expected_sha in SHA.items():
        name,homepage,stream,page,url,host=SOURCES[sid]
        station=origin[sid];row=rows[sid]
        if (station["display_name"]!=name or station["homepage"]!=homepage
            or station["status"]["state"]!="active" or station["logo"] is not None
            or not any(stream in k["url"] for k in station["streams"])
            or row["name"]!=name or row["publisher_page"]!=page or row["original_gif_url"]!=url
            or row["original_gif_sha_verified"] is not True
            or row["derived_png_sha_verified"] is not True
            or row["derived_png_sha256"]!=expected_sha
            or row["status"]!="ORIGINAL_BROADCASTER_GIF_TO_CANONICAL_PNG_SHA_PASS"
            or row["signed"] is not False or row["published"] is not False
            or (sid=="go-station-000146" and row["page_match"] is not True)):
            raise ValueError("Rejected GIF logo metadata for "+sid)
        original,mime,final=_request(url,max_bytes=MAX_IMAGE,accept="image/gif")
        if urlsplit(final).hostname!=host or mime not in ("image/gif","application/octet-stream",""):
            raise ValueError("GIF no longer from first-party domain")
        if hashlib.sha256(original).hexdigest()!=row["original_gif_sha256"] or len(original)!=row["original_gif_byte_size"]:
            raise ValueError("Original owner GIF source changed: "+sid)
        rendered,w,h=convert(original)
        check=inspect_bytes(rendered,content_type="image/png")
        if (check["sha256"]!=expected_sha or check["mime_type"]!="image/png"
            or check["byte_size"]!=row["derived_png_byte_size"] or (w,h)!=(row["width"],row["height"])
            or check["width"]!=w or check["height"]!=h):
            raise ValueError("Re-rendered original GIF PNG content changed: "+sid)
        pngs[sid]=(row,rendered,check)
    if len({sha for sha in SHA.values()})!=2:raise ValueError("Duplicate image objects")
    updated=deepcopy(old);updated["generated_at"]="2026-11-23T16:18:00Z"
    for s in updated["stations"]:
        sid=s["go_station_id"]
        if sid not in pngs:continue
        row,_,info=pngs[sid];digest=info["sha256"]
        s["logo"]={
            "asset_id":"sha256:"+digest,"sha256":digest,"revision":1,
            "url":PREFIX+digest+".png","byte_size":info["byte_size"],
            "width":info["width"],"height":info["height"],"mime_type":"image/png"
        }
    if updated["tombstones"]!=old["tombstones"]:raise ValueError("Tombstones changed")
    if sum(s["status"]["state"]=="active" and s["logo"] is None for s in updated["stations"])!=34:
        raise ValueError("Expect 34 remaining logos")
    if sum(s["status"]["state"]=="active" and s["logo"] is not None for s in updated["stations"])!=251:
        raise ValueError("Expect 251 station logos")
    for station in updated["stations"]:
        old_station=origin[station["go_station_id"]]
        if station["go_station_id"] in SHA:
            blank=deepcopy(station);blank["logo"]=None
            if blank!=old_station:raise ValueError("Station edited beyond logo")
        elif station!=old_station:raise ValueError("Unrelated station edited")
    ASSETS.mkdir(parents=True,exist_ok=False)
    for _,content,info in pngs.values():(ASSETS/(info["sha256"]+".png")).write_bytes(content)
    AFTER.write_text(json.dumps(updated,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"result":"GO_V8_62_OWNER_GIF_DERIVED_SHA_PNGS_STAGED_UNSIGNED",
                      "new_derived_pngs":2,"new_logo_assets_total":62,"active":285,
                      "with_logo":251,"missing_logo":34,"redirects":24,
                      "v8_signed":False,"v8_published":False,"signed_v7_untouched":True},sort_keys=True))
if __name__=="__main__":main()
