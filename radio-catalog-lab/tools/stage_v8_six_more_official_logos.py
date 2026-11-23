#!/usr/bin/env python3
"""Second verified broadcaster batch: stage six exact SHA image files unsigned.

Read-only audit #45168508032 verified six publishers by original image
bytes, with four source HTML-image associations and two JS-rendered images
from official original pages. Rock FM 105.5 was not SHA verified and MUST
stay without artwork. Never change signed TEST v7 or production.
"""
from __future__ import annotations
from copy import deepcopy
import argparse,hashlib,json
from pathlib import Path
from urllib.parse import urlsplit
from audit_v8_seven_more_publisher_logos import TARGETS
from audit_open_radio_artwork_inventory import _request,inspect_bytes,MAX_IMAGE
ROOT=Path(__file__).resolve().parents[2]
BEFORE=ROOT/"radio-catalog-lab/full-staging/UNSIGNED-radio-v8-metalon-3-independent-3-firstparty-7-maximum-3-broadcaster-7-20261123.json"
AFTER=ROOT/"radio-catalog-lab/full-staging/UNSIGNED-radio-v8-metalon-3-independent-3-firstparty-7-maximum-3-broadcaster-7-indep6-20261123.json"
ASSETS=ROOT/"grossesondes/radio-test-v2/artwork/staging-indep-six-v8"
PREFIX=("https://raw.githubusercontent.com/Sarogal/Ondes-Catalogues/"
        "feature/go-radio-v8-metalon-3-logos-20261123/"
        "grossesondes/radio-test-v2/artwork/staging-indep-six-v8/")
EXT={"image/jpeg":"jpg","image/png":"png","image/webp":"webp"}
SHAS={
 "go-station-000236":"9fdbd3033f9fb22bbe181589a711c9539e92e781f5e5fb3533b8d1ac7bacda3b",
 "go-station-000234":"551747ae21ac5c946af90677ec61104e0f67d7fd7e8c0ea98f5ad6dd6bc01a53",
 "go-station-000217":"4406301d81c15db8ad20dde980bc833ddb1a56aeb634320a54a583c1882a6e95",
 "go-station-000225":"77006275fb574e74e5e25fb14eecc65a3d674967df5ee2119c4048fc45d146b8",
 "go-station-000213":"e68490347c0d672514f7854b813c54580822e3a7e3bbcc7295427c4ad583d656",
 "go-station-000182":"d3e58ad1b5f89b9357aebac434e041f79da5efbf237f4ea9458d967889e35e78"
}
def main():
    p=argparse.ArgumentParser();p.add_argument("--artifact-root",type=Path,required=True);a=p.parse_args()
    if AFTER.exists() or ASSETS.exists():raise ValueError("Never overwrite signed/mutable assets")
    evidence=list(a.artifact_root.rglob("online.json"))
    if len(evidence)!=1 or not evidence[0].is_file() or evidence[0].stat().st_size>100000:
        raise ValueError("Expected one pinned publisher audit JSON")
    doc=json.loads(evidence[0].read_bytes())
    if (doc.get("scope")!="GO_V8_7_MORE_FIRSTPARTY_RADIO_LOGOS_READ_ONLY"
            or doc.get("target_count")!=7 or doc.get("verified_count")!=6
            or doc.get("confirmed_html_mapping_count")!=4
            or doc.get("catalog_modified") is not False
            or doc.get("publication_allowed") is not False):
        raise ValueError("First-party original image audit unexpected")
    records={x["go_station_id"]:x for x in doc["records"]}
    if set(records)!=set(TARGETS) or set(SHAS)!=(set(records)-{"go-station-000107"}):
        raise ValueError("Unexpected identity list")
    reject=records["go-station-000107"]
    if reject.get("sha_verified") is not False:
        raise ValueError("Unverified Rock FM image must never be staged")
    prior=json.loads(BEFORE.read_bytes())
    active=[x for x in prior["stations"] if x["status"]["state"]=="active"]
    if (prior["release_sequence"]!=8 or len(prior["stations"])!=296
            or len(prior["tombstones"])!=24 or len(active)!=285
            or sum(x["logo"] is None for x in active)!=73):
        raise ValueError("Expected 23 previous logo corrections")
    original={x["go_station_id"]:x for x in prior["stations"]}
    verified={}
    for sid,digest in SHAS.items():
        row=records[sid];c=TARGETS[sid];s=original[sid]
        if (s["logo"] is not None or s["status"]["state"]!="active"
                or s["display_name"]!=c["name"] or s["homepage"]!=c["homepage"]
                or row["station_name"]!=c["name"] or row["publisher_page"]!=c["page"]
                or row["image_url"]!=c["image"] or row.get("sha_verified") is not True
                or row.get("status")!="PUBLISHER_IMAGE_SHA_VALIDATED"
                or row.get("sha256")!=digest or row.get("mime_type") not in EXT
                or row.get("published") is not False or row.get("catalog_modified") is not False
                or (sid not in {"go-station-000236","go-station-000234"}
                    and row.get("publisher_html_mapping_verified") is not True)):
            raise ValueError("Publisher image/station identity failed "+sid)
        data,mime,final=_request(c["image"],max_bytes=MAX_IMAGE,
                                  accept="image/png,image/jpeg,image/webp")
        if urlsplit(final).hostname!=urlsplit(c["image"]).hostname:
            raise ValueError("First-party image URL redirected")
        result=inspect_bytes(data,content_type=mime)
        expected={k:row[k] for k in ("sha256","byte_size","width","height","mime_type")}
        if result!=expected or hashlib.sha256(data).hexdigest()!=digest:
            raise ValueError("Official logo original bytes mismatch")
        verified[sid]=(row,data)
    if len({r["sha256"] for r,_ in verified.values()})!=6:
        raise ValueError("Repeated generic logo rejected")
    next_=deepcopy(prior);next_["generated_at"]="2026-11-23T12:00:00Z"
    for s in next_["stations"]:
        if s["go_station_id"] not in verified:continue
        row,_=verified[s["go_station_id"]];sha=row["sha256"]
        s["logo"]={"asset_id":"sha256:"+sha,"sha256":sha,"revision":1,
                   "url":PREFIX+sha+"."+EXT[row["mime_type"]],
                   "byte_size":row["byte_size"],"width":row["width"],
                   "height":row["height"],"mime_type":row["mime_type"]}
    if (next_["tombstones"]!=prior["tombstones"]
            or sum(x["status"]["state"]=="active" and x["logo"] is None for x in next_["stations"])!=67
            or sum(x["status"]["state"]=="active" and x["logo"] is not None for x in next_["stations"])!=218):
        raise ValueError("Unexpected v8 station/logo changes")
    for s in next_["stations"]:
        past=original[s["go_station_id"]]
        if s["go_station_id"] in verified:
            without=deepcopy(s);without["logo"]=None
            if without!=past:raise ValueError("Metadata changed beyond logo")
        elif s!=past:raise ValueError("Unrelated station altered")
    ASSETS.mkdir(parents=True,exist_ok=False)
    for record,data in verified.values():
        (ASSETS/(record["sha256"]+"."+EXT[record["mime_type"]])).write_bytes(data)
    AFTER.write_text(json.dumps(next_,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"result":"GO_V8_MORE_SIX_OFFICIAL_STATION_LOGOS_UNSIGNED",
      "new_logo_references_total":29,"new_sha_files":6,
      "active_radios":285,"logo_covered":218,"logo_missing":67,
      "tombstones_preserved":24,"signed":False,"published":False,
      "signed_v7_pointer_untouched":True},sort_keys=True))
if __name__=="__main__":main()
