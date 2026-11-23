#!/usr/bin/env python3
"""Stage two matched *channel-specific* original radio images, unsigned v8 only.

Hotmix product 214 matches a Metal-labeled tile and active Metal stream.
HuilaGeek Zeno owner page embeds exact existing 8smiwwvtfxxvv stream,
unlike similar-name decoy. Both publisher image byte SHAs rechecked.
"""
from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path
from copy import deepcopy
from urllib.parse import urlsplit
from audit_open_radio_artwork_inventory import _request,inspect_bytes,MAX_IMAGE
from audit_v8_hotmix_metal_huila_exact_logos import (
    HOTMIX_ORIGINAL,HUILA_IMAGE,HUILA_PAGE,HOTMIX_PAGE,STREAM_ID,
)
ROOT=Path(__file__).resolve().parents[2]
BEFORE=ROOT/"radio-catalog-lab/full-staging/UNSIGNED-radio-v8-66-official-sha-logos-20261123.json"
AFTER=ROOT/"radio-catalog-lab/full-staging/UNSIGNED-radio-v8-68-official-sha-logos-20261123.json"
ART=ROOT/"grossesondes/radio-test-v2/artwork/staging-hotmix-huilageek-v8"
PREFIX=("https://raw.githubusercontent.com/Sarogal/Ondes-Catalogues/"
        "feature/go-radio-v8-metalon-3-logos-20261123/"
        "grossesondes/radio-test-v2/artwork/staging-hotmix-huilageek-v8/")
SHA={
"go-station-000212":"2ac3bbbd753682f6ea4ce4b4e7f2ea23fb13a9c576262eb10f5941ddea58687e",
"go-station-000136":"69dff8e0cbec6e21d17948bbfaeb564adc404a7c669d5503bc94805413e20276",
}
URL={"go-station-000212":HOTMIX_ORIGINAL,"go-station-000136":HUILA_IMAGE}
EXT={"image/jpeg":".jpg","image/png":".png","image/webp":".webp"}
def main():
    p=argparse.ArgumentParser();p.add_argument("--artifact-root",type=Path,required=True);a=p.parse_args()
    if AFTER.exists() or ART.exists():raise ValueError("Immutable TEST draft already exists")
    items=list(a.artifact_root.rglob("online.json"))
    if len(items)!=1 or items[0].stat().st_size>160000:
        raise ValueError("Require exactly one approved source audit artifact")
    proof=json.loads(items[0].read_bytes())
    if (proof.get("scope")!="GO_TEST_V8_HOTMIX_METAL_214_HUILAGEEK_MATCHED_STATION_SHA_AUDIT"
       or proof.get("stations")!=2 or proof.get("owner_channels_verified")!=2
       or proof.get("images_verified")!=2 or proof.get("signed") is not False
       or proof.get("published") is not False):
        raise ValueError("Original source/owner identity proof failed")
    records={r["go_station_id"]:r for r in proof["records"]}
    if set(records)!=set(SHA):raise ValueError("Unexpected new station in source report")
    h=records["go-station-000136"];m=records["go-station-000212"]
    if (h["publisher_page"]!=HUILA_PAGE or h.get("matched_existing_stream_id")!=STREAM_ID
        or h.get("different_named_station_rejected") is not True
        or h["verified_owner_channel"] is not True
        or m["publisher_page"]!=HOTMIX_PAGE
        or m.get("publisher_verified_product_id")!="214"
        or m.get("stream_mount_verified") is not True
        or m.get("owner_metal_buttons",0)<1
        or m["verified_owner_channel"] is not True):
        raise ValueError("Wrong Hotmix Metal or HuilaGeek owner channel mapping")
    before=json.loads(BEFORE.read_bytes())
    active=[s for s in before["stations"] if s["status"]["state"]=="active"]
    if (before["release_sequence"]!=8 or len(before["stations"])!=296
        or len(before["tombstones"])!=24 or len(active)!=285
        or sum(s["logo"] is None for s in active)!=30):
        raise ValueError("Expected 66-logo signed v7-compatible unsigned predecessor")
    originals={s["go_station_id"]:s for s in before["stations"]}
    staged={}
    for sid,digest in SHA.items():
        station=originals[sid];record=records[sid]
        name="Hotmix meal" if sid=="go-station-000212" else "HuilaGeek Radio"
        stream="hotmix-metal-en-mp3" if sid=="go-station-000212" else STREAM_ID
        if (station["status"]["state"]!="active" or station["logo"] is not None
           or station["display_name"]!=name
           or not any(stream in s["url"] for s in station["streams"])
           or record["name"]!=name
           or record["status"]!="CHANNEL_ID_AND_IMAGE_SHA_VERIFIED"
           or record["signed"] is not False or record["published"] is not False):
            raise ValueError("Radio identity/source mismatch "+sid)
        proof_image=[x for x in record["possible_original_images"]
                     if x["image_url"]==URL[sid] and x["valid"] is True]
        if len(proof_image)!=1:raise ValueError("Approved exact image original not in source evidence")
        expected=proof_image[0]
        if expected.get("sha256")!=digest or expected.get("mime_type") not in EXT:
            raise ValueError("Image original SHA or MIME mismatch "+sid)
        payload,mime,final=_request(URL[sid],max_bytes=MAX_IMAGE,accept="image/png,image/jpeg,image/webp")
        expected_host="checkout.hotmixradio.com" if sid=="go-station-000212" else "images.zeno.fm"
        if urlsplit(final).hostname!=expected_host:raise ValueError("Image escaped approved owner channel host")
        inspected=inspect_bytes(payload,content_type=mime)
        if inspected!={k:expected[k] for k in ("sha256","byte_size","width","height","mime_type")}:
            raise ValueError("Independent download SHA/metadata differs from audited owner image")
        if hashlib.sha256(payload).hexdigest()!=digest:
            raise ValueError("Original exact channel image SHA mismatch")
        staged[sid]=(payload,inspected)
    if len({m["sha256"] for _,m in staged.values()})!=2:
        raise ValueError("Shared generic image disallowed for independent channels")
    after=deepcopy(before)
    after["generated_at"]="2026-11-23T21:00:00Z"
    for s in after["stations"]:
        if s["go_station_id"] not in staged:continue
        blob,m=staged[s["go_station_id"]]
        suffix=EXT[m["mime_type"]]
        s["logo"]={
            "asset_id":"sha256:"+m["sha256"],"sha256":m["sha256"],
            "revision":1,"url":PREFIX+m["sha256"]+suffix,
            "byte_size":m["byte_size"],"width":m["width"],
            "height":m["height"],"mime_type":m["mime_type"]
        }
    if after["tombstones"]!=before["tombstones"]:
        raise ValueError("Redirects changed")
    if sum(s["status"]["state"]=="active" and s["logo"] is not None for s in after["stations"])!=257:
        raise ValueError("Expect 257 active logos")
    if sum(s["status"]["state"]=="active" and s["logo"] is None for s in after["stations"])!=28:
        raise ValueError("Expect 28 missing active logos")
    for station in after["stations"]:
        previous=originals[station["go_station_id"]]
        if station["go_station_id"] in SHA:
            blank=deepcopy(station);blank["logo"]=None
            if blank!=previous:raise ValueError("Edited radio other than logo")
        elif station!=previous:raise ValueError("Unrelated radio changed")
    ART.mkdir(parents=True,exist_ok=False)
    for blob,m in staged.values():
        (ART/(m["sha256"]+EXT[m["mime_type"]])).write_bytes(blob)
    AFTER.write_text(json.dumps(after,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"result":"GO_TEST_V8_68_VERIFIED_HOTMIX_AND_HUILAGEEK_STAGED_UNSIGNED",
        "new_sha_objects":2,"verified_new_sha_total":68,"active":285,
        "with_logo":257,"missing_logo":28,"redirects":24,
        "signed":False,"published":False,"signed_v7_unchanged":True},sort_keys=True))
if __name__=="__main__":main()
