#!/usr/bin/env python3
"""Stage eight first-party broadcaster image SHAs into unsigned v8 only.

Requires pinned successful read-only audit Actions #45177980618 and
independently re-downloads every exact original image. Preserves all
existing station identifiers, aliases, metadata and signed v7 pointer.
"""
from __future__ import annotations
import argparse,hashlib,json
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlsplit
from audit_v8_eight_more_original_logos import SOURCES
from audit_open_radio_artwork_inventory import _request,inspect_bytes,MAX_IMAGE

ROOT=Path(__file__).resolve().parents[2]
BEFORE=ROOT/"radio-catalog-lab/full-staging/UNSIGNED-radio-v8-35-official-sha-logos-20261123.json"
AFTER=ROOT/"radio-catalog-lab/full-staging/UNSIGNED-radio-v8-43-official-sha-logos-20261123.json"
ART=ROOT/"grossesondes/radio-test-v2/artwork/staging-eight-more-v8"
PREFIX=("https://raw.githubusercontent.com/Sarogal/Ondes-Catalogues/"
        "feature/go-radio-v8-metalon-3-logos-20261123/"
        "grossesondes/radio-test-v2/artwork/staging-eight-more-v8/")
SHA={
"go-station-000018":"41d70bf91da8cd79a4a4facfe04839986f9971f4e81bb9604ff94781bdbea3d2",
"go-station-000028":"ec9257b8179a4ebe0f135a4b4bd991c6215dbdde5eff19a7d3098829f4adc85e",
"go-station-000035":"030a30f5396b4f216ccefbb148284ebb9f923a8bc9f2ea6cdb3b27b3a2c53744",
"go-station-000310":"75e3054599f53f2918026857c6e791e5bb0513443cda77b1798a8b39a2f60860",
"go-station-000303":"a8a21c5185a0d24e4b44b21e7795acdddd0787dce2aad2a61ed3751022dcee61",
"go-station-000302":"327ec9c51b154f5296736534b5befe29b17592104b4d9ce5173b7486b9743df1",
"go-station-000197":"686219a9ece8643c6d6ebe835fa4e288a87c30fd56a807443f6c71e711517fa4",
"go-station-000088":"1725db18cd75eb17c7b39b814971c1baa5add3ea3ba8ac77069e2647ae5a6bed",
}
EXT={"image/png":"png","image/jpeg":"jpg","image/webp":"webp"}
def main():
    p=argparse.ArgumentParser();p.add_argument("--artifact-root",type=Path,required=True)
    options=p.parse_args()
    if AFTER.exists() or ART.exists():
        raise ValueError("Refusing to overwrite immutable staging candidate")
    evidence_files=list(options.artifact_root.rglob("online.json"))
    if len(evidence_files)!=1 or evidence_files[0].stat().st_size>100000:
        raise ValueError("Expected single previous read-only image-evidence artifact")
    evidence=json.loads(evidence_files[0].read_bytes())
    if (evidence.get("scope")!="GO_V8_EIGHT_FURTHER_BROADCASTER_ORIGINAL_LOGOS_READ_ONLY"
        or evidence.get("targets")!=8 or evidence.get("original_shas_verified")!=8
        or evidence.get("publisher_html_matches")!=6
        or evidence.get("catalog_changed") is not False
        or evidence.get("published") is not False):
        raise ValueError("Source audit run not valid")
    records={x["go_station_id"]:x for x in evidence["rows"]}
    if set(records)!=set(SHA) or set(SHA)!=set(SOURCES):
        raise ValueError("Unreviewed radio IDs in source artifact")
    previous=json.loads(BEFORE.read_bytes())
    active=[x for x in previous["stations"] if x["status"]["state"]=="active"]
    if (previous["release_sequence"]!=8 or len(previous["stations"])!=296
        or len(active)!=285 or len(previous["tombstones"])!=24
        or sum(x["logo"] is None for x in active)!=61):
        raise ValueError("Expected exact 35-logo v8 unsigned predecessor")
    original={x["go_station_id"]:x for x in previous["stations"]}
    collected={}
    for sid,digest in SHA.items():
        name,home,stream,page,image,asset_host=SOURCES[sid]
        current=original[sid];row=records[sid]
        if (current["status"]["state"]!="active" or current["logo"] is not None
            or current["display_name"]!=name or current["homepage"]!=home
            or not any(stream in s["url"] for s in current["streams"])
            or row.get("station_name")!=name
            or row.get("original_page")!=page
            or row.get("image_url")!=image
            or row.get("publisher_asset_host")!=asset_host
            or row.get("image_sha_verified") is not True
            or row.get("status")!="ORIGINAL_FIRST_PARTY_IMAGE_SHA_VALIDATED"
            or row.get("sha256")!=digest or row.get("mime_type") not in EXT
            or row.get("release_signed") is not False or row.get("published") is not False
            or row.get("catalog_changed") is not False
            or (sid not in {"go-station-000028","go-station-000197"}
                and row.get("page_html_matched") is not True)):
            raise ValueError("Publisher original image/station identity rejected: "+sid)
        binary,mime,final=_request(image,max_bytes=MAX_IMAGE,
                                   accept="image/png,image/jpeg,image/webp")
        if urlsplit(final).hostname!=asset_host:
            raise ValueError("Image origin escaped approved first-party host")
        source=inspect_bytes(binary,content_type=mime)
        expected={k:row[k] for k in ("sha256","byte_size","width","height","mime_type")}
        if source!=expected or hashlib.sha256(binary).hexdigest()!=digest:
            raise ValueError("Publisher image SHA changed on independent re-download")
        collected[sid]=(row,binary)
    if len({r["sha256"] for r,_ in collected.values()})!=8:
        raise ValueError("Repeated/generic source image")
    after=deepcopy(previous)
    after["generated_at"]="2026-11-23T13:55:00Z"
    for station in after["stations"]:
        sid=station["go_station_id"]
        if sid not in collected:continue
        row,_=collected[sid];digest=row["sha256"]
        station["logo"]={
            "asset_id":"sha256:"+digest,"sha256":digest,"revision":1,
            "url":PREFIX+digest+"."+EXT[row["mime_type"]],
            "byte_size":row["byte_size"],"width":row["width"],
            "height":row["height"],"mime_type":row["mime_type"],
        }
    if (after["tombstones"]!=previous["tombstones"] or len(after["stations"])!=296
        or sum(x["status"]["state"]=="active" and x["logo"] is not None for x in after["stations"])!=232
        or sum(x["status"]["state"]=="active" and x["logo"] is None for x in after["stations"])!=53):
        raise ValueError("Unrelated metadata or logo totals changed")
    for station in after["stations"]:
        old=original[station["go_station_id"]]
        if station["go_station_id"] in collected:
            copy=deepcopy(station);copy["logo"]=None
            if copy!=old:raise ValueError("Changed radio metadata beyond verified logo")
        elif station!=old:raise ValueError("Unrelated radio metadata changed")
    ART.mkdir(parents=True,exist_ok=False)
    for row,binary in collected.values():
        (ART/(row["sha256"]+"."+EXT[row["mime_type"]])).write_bytes(binary)
    AFTER.write_text(json.dumps(after,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({
        "result":"GO_V8_EIGHT_FURTHER_FIRSTPARTY_ORIGINAL_IMAGES_STAGED_UNSIGNED",
        "new_shas":8,"total_new_shas":43,
        "active_stations":285,"with_logo":232,"without_logo":53,
        "redirects":24,"signed":False,"published":False,
        "signed_test_v7_pointer_unchanged":True
    },sort_keys=True))
if __name__=="__main__":main()
