#!/usr/bin/env python3
"""Stage 7 reviewed first-party broadcaster images by immutable SHA in DEV v8.

Requires pinned original evidence Actions #45167550211 and a second exact
byte-for-byte image verification from broadcaster websites. Six of seven
HTML image mappings were observed in raw site HTML; TotalRock's square
branded icon was independently observed in the JS/browser page image set.
No silent generic favicon substitution. No signed TEST or production edits.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit
from audit_v8_seven_official_broadcaster_logos import TARGETS
from audit_open_radio_artwork_inventory import _request,inspect_bytes,MAX_IMAGE
ROOT=Path(__file__).resolve().parents[2]
PREV=ROOT/"radio-catalog-lab/full-staging/UNSIGNED-radio-v8-metalon-3-independent-3-firstparty-7-maximum-3-20261123.json"
OUT=ROOT/"radio-catalog-lab/full-staging/UNSIGNED-radio-v8-metalon-3-independent-3-firstparty-7-maximum-3-broadcaster-7-20261123.json"
ASSETS=ROOT/"grossesondes/radio-test-v2/artwork/staging-broadcasters-v8"
URL_PREFIX=("https://raw.githubusercontent.com/Sarogal/Ondes-Catalogues/"
            "feature/go-radio-v8-metalon-3-logos-20261123/"
            "grossesondes/radio-test-v2/artwork/staging-broadcasters-v8/")
EXT={"image/png":"png","image/jpeg":"jpg","image/webp":"webp"}
SHA={
 "go-station-000186":"d7bc9b06a46c6035d975779dbbc5b24b1cd24026eb5247765907fcc3effcf1c2",
 "go-station-000014":"b063da4bbb1c2b2ae74110cce4ddd769b77d99c2429afebb15b144a217b2ab2d",
 "go-station-000284":"09dad8fa85745f051f410fabbb9357fb38937c701cfbcfa600ef75a8b858dcd0",
 "go-station-000286":"00aaa66f5021abe8e54324c2b08fa60b10b60f4dfa7f7201bcb6cbf564520a4f",
 "go-station-000271":"ac3667d29d947e40e8fbd17b648d82952889007cbdb719ac754f55889e474663",
 "go-station-000295":"54e665e2b5e85b14c27f94fff4d04fb914b8297e3e0a6a218824882b34e9ddcc",
 "go-station-000138":"8ee32c801fc05bdbc1bc927622c641219b3c822c62a9ae670153488dc864ab11",
}
def main():
    p=argparse.ArgumentParser();p.add_argument("--artifact-root",type=Path,required=True);a=p.parse_args()
    if OUT.exists() or ASSETS.exists():
        raise ValueError("Refusing overwriting staged artifacts")
    files=list(a.artifact_root.rglob("online.json"))
    if len(files)!=1 or files[0].stat().st_size>100000:
        raise ValueError("Missing one original GitHub Actions source report")
    ev=json.loads(files[0].read_bytes())
    if (ev.get("scope")!="GO_V8_SEVEN_BROADCASTER_SOURCE_IMAGES_READ_ONLY"
            or ev.get("targets")!=7 or ev.get("sha_verified")!=7
            or ev.get("html_mappings_verified")!=6 or ev.get("publication_allowed") is not False
            or ev.get("catalog_changed") is not False):
        raise ValueError("Unexpected source verification report")
    rows={r["go_station_id"]:r for r in ev["records"]}
    if set(rows)!=set(SHA) or set(SHA)!=set(TARGETS):
        raise ValueError("Unreviewed stations present in evidence")
    before=json.loads(PREV.read_bytes())
    active=[s for s in before["stations"] if s["status"]["state"]=="active"]
    if (before.get("release_sequence")!=8 or len(before["stations"])!=296
            or len(before["tombstones"])!=24 or len(active)!=285
            or sum(s["logo"] is None for s in active)!=80):
        raise ValueError("16 verified-logo candidate missing or altered")
    original={s["go_station_id"]:s for s in before["stations"]}
    checked={}
    for sid,info in TARGETS.items():
        station=original[sid];row=rows[sid]
        if (station["logo"] is not None or station["status"]["state"]!="active"
                or station["display_name"]!=info["name"]
                or row.get("station_name")!=info["name"]
                or row.get("publisher_page")!=info["official_page"]
                or row.get("image_url")!=info["image_url"]
                or row.get("real_image_sha_verified") is not True
                or row.get("status")!="OFFICIAL_ORIGINAL_SHA_VALIDATED"
                or row.get("sha256")!=SHA[sid] or row.get("mime_type") not in EXT
                or row.get("publication_allowed") is not False
                or row.get("catalog_changed") is not False
                or (sid!="go-station-000295" and row.get("official_page_verified") is not True)
                or (sid!="go-station-000295" and row.get("publisher_html_mapping_verified") is not True)):
            raise ValueError("Publisher/source identity rejected "+sid)
        data,mime,final=_request(info["image_url"],max_bytes=MAX_IMAGE,
                                  accept="image/jpeg,image/png,image/webp")
        if urlsplit(final).hostname!=urlsplit(info["image_url"]).hostname:
            raise ValueError("Official image left first-party host")
        now=inspect_bytes(data,content_type=mime)
        expected={k:row[k] for k in ("sha256","byte_size","width","height","mime_type")}
        if now!=expected or hashlib.sha256(data).hexdigest()!=SHA[sid]:
            raise ValueError("Publisher image bytes changed between independent audits")
        checked[sid]=(row,data)
    if len({r["sha256"] for r,_ in checked.values()})!=7:
        raise ValueError("Repeated generic brand image SHA")
    after=deepcopy(before)
    after["generated_at"]="2026-11-23T11:50:00Z"
    for st in after["stations"]:
        sid=st["go_station_id"]
        if sid not in checked:continue
        record,_=checked[sid];sha=record["sha256"];extension=EXT[record["mime_type"]]
        st["logo"]={
            "asset_id":"sha256:"+sha,"sha256":sha,"revision":1,
            "url":URL_PREFIX+sha+"."+extension,
            "byte_size":record["byte_size"],"width":record["width"],
            "height":record["height"],"mime_type":record["mime_type"]
        }
    if (after["tombstones"]!=before["tombstones"] or len(after["stations"])!=296
            or sum(s["status"]["state"]=="active" and s["logo"] is None for s in after["stations"])!=73
            or sum(s["status"]["state"]=="active" and s["logo"] is not None for s in after["stations"])!=212):
        raise ValueError("Unexpected changes to existing v8 station data")
    for st in after["stations"]:
        old=original[st["go_station_id"]]
        if st["go_station_id"] in checked:
            without=deepcopy(st);without["logo"]=None
            if without!=old:raise ValueError("Unrelated radio field edited")
        elif st!=old:raise ValueError("Unrelated radio edited")
    ASSETS.mkdir(parents=True,exist_ok=False)
    for record,data in checked.values():
        filename=record["sha256"]+"."+EXT[record["mime_type"]]
        (ASSETS/filename).write_bytes(data)
    OUT.write_text(json.dumps(after,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({
      "result":"GO_V8_SEVEN_ADDITIONAL_BROADCASTER_LOGOS_STAGED_UNSIGNED",
      "seven_new_station_images":7,
      "new_station_logo_descriptors_total":23,
      "active_radios":285,"active_with_logo":212,"active_without_logo":73,
      "tombstones":24,"signed":False,"published":False,
      "signed_v7_pointer_untouched":True},sort_keys=True))
if __name__=="__main__":main()
