#!/usr/bin/env python3
"""Stage six SHA-verified channel-specific radio logos (UNSIGNED v8 only).

Strictly pinned to read-only Actions #45170511954, second byte download.
NTS The Pit omitted (source image did not validate). No TEST v7 changes.
"""
import argparse,hashlib,json
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlsplit
from audit_v8_seven_exact_channel_images import SOURCES
from audit_open_radio_artwork_inventory import _request,inspect_bytes,MAX_IMAGE
ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/"radio-catalog-lab/full-staging/UNSIGNED-radio-v8-metalon-3-independent-3-firstparty-7-maximum-3-broadcaster-7-indep6-20261123.json"
OUT=ROOT/"radio-catalog-lab/full-staging/UNSIGNED-radio-v8-35-official-sha-logos-20261123.json"
ASSETS=ROOT/"grossesondes/radio-test-v2/artwork/staging-exact-six-v8"
PREFIX=("https://raw.githubusercontent.com/Sarogal/Ondes-Catalogues/"
        "feature/go-radio-v8-metalon-3-logos-20261123/"
        "grossesondes/radio-test-v2/artwork/staging-exact-six-v8/")
SHA={
"go-station-000168":"0a2b8b624dbbf10171909ed4c1119aba5fbe28fef5fc319e7e6ac5d2243146ce",
"go-station-000102":"d9c787f1580281fab6c1660afdb6d557071dd6072d89e3efbf746d8ddb6d0e93",
"go-station-000294":"7f3f962fa21ac8653d14b67a61d4001eba25dab3040a18b279b6902489e18ee2",
"go-station-000273":"0f4b521f3dfa712863983134401185de2b6660cc16085ba4f6f42cb2388000af",
"go-station-000150":"7f3d308903eb8a54413ecb8681146f28bde02eacbd6e622da7cb0a9f91953da4",
"go-station-000298":"f28d6aeca32a9fcae809d68a014d8971dd85c8c345dfba15adaf4457f8cdc8aa",
}
EXT={"image/jpeg":"jpg","image/png":"png","image/webp":"webp"}
def main():
    a=argparse.ArgumentParser()
    a.add_argument("--artifact-root",type=Path,required=True)
    opts=a.parse_args()
    if OUT.exists() or ASSETS.exists():raise ValueError("Refusing SHA/catalog overwrite")
    proof_files=list(opts.artifact_root.rglob("online.json"))
    if len(proof_files)!=1 or proof_files[0].stat().st_size>100000:
        raise ValueError("Missing one exact Actions report")
    proof=json.loads(proof_files[0].read_bytes())
    if (proof.get("scope")!="GO_V8_7_EXACT_CHANNEL_ORIGINAL_IMAGE_AUDIT" or
        proof.get("targets")!=7 or proof.get("original_sha_verified")!=6 or
        proof.get("html_matches")!=5 or proof.get("published") is not False or
        proof.get("catalog_changed") is not False):
        raise ValueError("Invalid publisher evidence")
    rows={x["go_station_id"]:x for x in proof["rows"]}
    if set(rows)!=set(SOURCES) or set(SHA)!=(set(SOURCES)-{"go-station-000042"}):
        raise ValueError("Unexpected station evidence")
    if rows["go-station-000042"].get("image_sha_verified") is not False:
        raise ValueError("Unverified NTS source unexpectedly accepted")
    old=json.loads(BASE.read_bytes())
    active=[x for x in old["stations"] if x["status"]["state"]=="active"]
    if (old["release_sequence"]!=8 or len(old["stations"])!=296 or
        len(old["tombstones"])!=24 or len(active)!=285 or
        sum(x["logo"] is None for x in active)!=67):
        raise ValueError("Expected old 29-logo staging")
    prior={x["go_station_id"]:x for x in old["stations"]}
    verified={}
    for sid,expected_sha in SHA.items():
        name,home,stream,page,image,host=SOURCES[sid]
        station=prior[sid]
        record=rows[sid]
        if (station["logo"] is not None or station["display_name"]!=name or
            station["homepage"]!=home or station["status"]["state"]!="active" or
            not any(stream in x["url"] for x in station["streams"]) or
            record.get("station_name")!=name or
            record.get("publisher_page")!=page or
            record.get("publisher_image")!=image or
            record.get("image_source_host")!=host or
            record.get("image_sha_verified") is not True or
            record.get("status")!="ORIGINAL_BROADCASTER_CHANNEL_IMAGE_SHA_VERIFIED" or
            record.get("sha256")!=expected_sha or
            record.get("mime_type") not in EXT or
            record.get("published") is not False or
            record.get("catalog_changed") is not False or
            (sid not in ("go-station-000168","go-station-000273") and
             record.get("html_image_match") is not True)):
            raise ValueError("Untrusted channel/station mapping "+sid)
        data,mime,final=_request(image,max_bytes=MAX_IMAGE,
                                   accept="image/jpeg,image/png,image/webp")
        if urlsplit(final).hostname!=host:raise ValueError("Unexpected CDN redirect")
        metadata=inspect_bytes(data,content_type=mime)
        if metadata!={k:record[k] for k in ("sha256","byte_size","width","height","mime_type")} or hashlib.sha256(data).hexdigest()!=expected_sha:
            raise ValueError("Changed source image on second byte inspection "+sid)
        verified[sid]=(record,data)
    if len({x["sha256"] for x,_ in verified.values()})!=6:
        raise ValueError("Repeated/missing source image SHA")
    new=deepcopy(old)
    new["generated_at"]="2026-11-23T12:20:00Z"
    for st in new["stations"]:
        sid=st["go_station_id"]
        if sid not in verified:continue
        row,_=verified[sid];sha=row["sha256"]
        st["logo"]={"asset_id":"sha256:"+sha,"sha256":sha,"revision":1,
                    "url":PREFIX+sha+"."+EXT[row["mime_type"]],
                    "byte_size":row["byte_size"],"width":row["width"],
                    "height":row["height"],"mime_type":row["mime_type"]}
    assert new["tombstones"]==old["tombstones"]
    assert sum(x["status"]["state"]=="active" and x["logo"] is None for x in new["stations"])==61
    assert sum(x["status"]["state"]=="active" and x["logo"] is not None for x in new["stations"])==224
    for st in new["stations"]:
        before=prior[st["go_station_id"]]
        if st["go_station_id"] in verified:
            clone=deepcopy(st);clone["logo"]=None
            assert clone==before,"Unrelated station metadata modified"
        else:assert st==before,"Unexpected other station edit"
    ASSETS.mkdir(parents=True,exist_ok=False)
    for row,data in verified.values():
        (ASSETS/(row["sha256"]+"."+EXT[row["mime_type"]])).write_bytes(data)
    OUT.write_text(json.dumps(new,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"result":"GO_V8_SIX_EXACT_BROADCASTER_CHANNEL_LOGOS_STAGED_UNSIGNED",
                      "new_logos_added_now":6,"all_added_v8":35,
                      "active_stations":285,"with_logo":224,"without_logo":61,
                      "tombstones":24,"signed":False,"published":False},sort_keys=True))
if __name__=="__main__":main()
