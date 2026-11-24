#!/usr/bin/env python3
"""Stage three real Radio MAXIMUM channel tiles into isolated UNSIGNED GO v8.

Publisher HTML delivered to GitHub runner did not reproduce the image mapping,
but an inspected browser render of https://maximum.ru/online displayed each
original image separately under its named channel. The pinned URL/SHA/image
metadata are verified once in Actions #45166112250 and verified again here.
No automatic trust in shared network favicon. No live catalogue changes.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

from audit_v8_maximum_three_official_channel_logos import CHANNELS
from audit_open_radio_artwork_inventory import _request,inspect_bytes,MAX_IMAGE

ROOT=Path(__file__).resolve().parents[2]
BEFORE=ROOT/"radio-catalog-lab/full-staging/UNSIGNED-radio-v8-metalon-3-independent-3-firstparty-7-20261123.json"
AFTER=ROOT/"radio-catalog-lab/full-staging/UNSIGNED-radio-v8-metalon-3-independent-3-firstparty-7-maximum-3-20261123.json"
ASSETS=ROOT/"grossesondes/radio-test-v2/artwork/staging-maximum-v8"
PREFIX=("https://raw.githubusercontent.com/Sarogal/Ondes-Catalogues/"
        "feature/go-radio-v8-metalon-3-logos-20261123/"
        "grossesondes/radio-test-v2/artwork/staging-maximum-v8/")
EXPECTED={
 "go-station-000002":"a22ca77a163182f6879533e6d56e9968830f73b6c7dda204205e277f5fdb3796",
 "go-station-000041":"ae1c36428e4e25701163d639d5133c826462a013cdcceb8b3bf075d51f1908a9",
 "go-station-000263":"22c3182e1460d14647c54c351a6adcabc2e796dac7175dedbbeb73099f6c08ce",
}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--artifact-root",type=Path,required=True)
    a=p.parse_args()
    if AFTER.exists() or ASSETS.exists():
        raise ValueError("Refusing overwrite of SHA objects or v8 candidate")
    inputs=list(a.artifact_root.rglob("maximum-online.json"))
    if len(inputs)!=1 or not inputs[0].is_file() or inputs[0].stat().st_size>50*1024:
        raise ValueError("Expected exactly one original immutable Actions report")
    r=json.loads(inputs[0].read_bytes())
    if (r.get("scope")!="GO_V8_MAXIMUM_3_CHANNEL_ORIGINAL_SHA_READ_ONLY"
            or r.get("expected_stations")!=3 or r.get("original_image_sha_verified")!=3
            or r.get("publication_allowed") is not False or r.get("catalog_mutated") is not False):
        raise ValueError("Untrusted original first-party audit")
    obs={x["go_station_id"]:x for x in r["records"]}
    if set(obs)!=set(EXPECTED):
        raise ValueError("Three channel IDs do not match the audit report")
    old=json.loads(BEFORE.read_bytes())
    active=[s for s in old["stations"] if s["status"]["state"]=="active"]
    if (old["release_sequence"]!=8 or len(old["stations"])!=296
            or len(old["tombstones"])!=24 or len(active)!=285
            or sum(s["logo"] is None for s in active)!=83):
        raise ValueError("Expected 13-logo unsigned v8 source")
    prev={s["go_station_id"]:s for s in old["stations"]}
    data={}
    for sid,info in CHANNELS.items():
        row=obs[sid]
        station=prev[sid]
        if (station["display_name"]!=info["name"] or station["logo"] is not None
                or station["status"]["state"]!="active"
                or row["station_name"]!=info["name"]
                or row["publisher_page"]!="https://maximum.ru/online"
                or row["publisher_image"]!=info["source"]
                or row.get("image_bytes_verified") is not True
                or row.get("sha256")!=EXPECTED[sid]
                or row.get("mime_type")!="image/webp"
                or row.get("publication_allowed") is not False
                or row.get("catalog_mutated") is not False
                or row.get("status") not in {
                    "OFFICIAL_CHANNEL_IMAGE_SHA_AND_HTML_MATCH",
                    "ORIGINAL_SHA_VERIFIED_HTML_MAPPING_NOT_CONFIRMED",
                }):
            raise ValueError("Unverified station/channel source: "+sid)
        payload,mime,final=_request(
            info["source"],max_bytes=MAX_IMAGE,accept="image/webp,image/png,image/jpeg")
        if urlsplit(final).hostname!="maximum.ru":
            raise ValueError("Publisher image left maximum.ru")
        checked=inspect_bytes(payload,content_type=mime)
        expected={k:row[k] for k in
                  ("sha256","byte_size","width","height","mime_type")}
        if checked!=expected or hashlib.sha256(payload).hexdigest()!=EXPECTED[sid]:
            raise ValueError("Original publisher logo changed between independent checks")
        data[sid]=(row,payload)
    if len({r["sha256"] for r,_ in data.values()})!=3:
        raise ValueError("Generic/doubled channel image SHA")
    new=deepcopy(old)
    new["generated_at"]="2026-11-23T11:40:00Z"
    for s in new["stations"]:
        sid=s["go_station_id"]
        if sid not in data: continue
        ev,_=data[sid]
        sha=ev["sha256"]
        s["logo"]={
            "asset_id":"sha256:"+sha,"sha256":sha,"revision":1,
            "url":PREFIX+sha+".webp","byte_size":ev["byte_size"],
            "width":ev["width"],"height":ev["height"],"mime_type":"image/webp",
        }
    if (new["tombstones"]!=old["tombstones"] or len(new["stations"])!=296
            or sum(s["status"]["state"]=="active" and s["logo"] is None for s in new["stations"])!=80):
        raise ValueError("Unexpected v8 identity/missing-logo change")
    for s in new["stations"]:
        before=prev[s["go_station_id"]]
        if s["go_station_id"] in data:
            without=deepcopy(s);without["logo"]=None
            if without!=before:
                raise ValueError("Unrelated station metadata modified")
        elif s!=before:
            raise ValueError("Unrelated station modified")
    ASSETS.mkdir(parents=True,exist_ok=False)
    for row,payload in data.values():
        (ASSETS/(row["sha256"]+".webp")).write_bytes(payload)
    AFTER.write_text(json.dumps(new,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"result":"GO_V8_3_RADIO_MAXIMUM_CHANNEL_LOGOS_STAGED_UNSIGNED",
                      "new_image_shas":3,"new_logos_v8_total":16,
                      "active_stations":285,"with_logo":205,"without_logo":80,
                      "browser_publisher_page_identity_reviewed":True,
                      "server_html_mapping_not_required_for_stage":True,
                      "v8_signed":False,"v8_published":False,
                      "live_v7_untouched":True},sort_keys=True))
if __name__=="__main__":
    main()
