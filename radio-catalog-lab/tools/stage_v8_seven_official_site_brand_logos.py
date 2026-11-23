#!/usr/bin/env python3
"""Stage 7 first-party verified radio brand images as SHA blobs in unsigned v8.

Read immutable GitHub Actions #45164093159 official publisher home page
evidence. Strict manually reviewed 7 exact GO IDs, URLs and SHA pins, with
second independent byte download, no album art or third-party directory
images. 181.FM station deliberately uses the publisher's shared brand logo.
No v7 TEST pointer change, no signing, no production or Android compilation.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

from audit_open_radio_artwork_inventory import _request,inspect_bytes,MAX_IMAGE

ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/"radio-catalog-lab/full-staging/UNSIGNED-radio-v8-metalon-3-independent-3-20261123.json"
TARGET=ROOT/"radio-catalog-lab/full-staging/UNSIGNED-radio-v8-metalon-3-independent-3-firstparty-7-20261123.json"
ASSETS=ROOT/"grossesondes/radio-test-v2/artwork/staging-official-site-v8"
RAW_PREFIX=("https://raw.githubusercontent.com/Sarogal/Ondes-Catalogues/"
            "feature/go-radio-v8-metalon-3-logos-20261123/"
            "grossesondes/radio-test-v2/artwork/staging-official-site-v8/")
EXT={"image/png":"png","image/jpeg":"jpg","image/webp":"webp"}
APPROVED={
 "go-station-000313":(
  "REAL PUNK RADIO",
  "https://realpunkradio.com/wp-content/uploads/2017/07/new_rpr_logo_white-on-black.jpg",
  "cb95823509e3f2fbe893b6449e1031d714bdaf2c4594d11e69e5b0d0b2ac5b63"),
 "go-station-000192":(
  "Radio Metal",
  "https://www.radiometal.com/wp-content/uploads/2024/02/cropped-logo-radio-metal-since-2007-192x192.jpg",
  "3a3e59a8c52cdc3516f7ba9265b9ba1c1334f6dcd864d68e1367c8072f735c9d"),
 "go-station-000174":(
  "181.FM - 80's HairBand",
  "https://www.181.fm/images/og181fmlogo.jpg",
  "ef746603932c9b428fe0044f5a92e22a42d50138dea0d8e79852eaf9d43de4e3"),
 "go-station-000081":(
  "BDPST ROCK Rádió (Hi-Fi / Lossless / FLAC)",
  "https://www.bdpstrock.hu/logo192.png",
  "de080d8622e7705db768199c54c4ee7be6c562aa2735c3035eed2bff602bb3ec"),
 "go-station-000173":(
  "Hard Rock Heaven",
  "https://www.hrhradio.com/wp-content/uploads/2023/05/logo_cuadrado_fondo_negro-300x300.png",
  "16612976c806bc247b6f5d087ba637285b34886e98c359dda69450045c909c2d"),
 "go-station-000228":(
  "Dead2Self Radio",
  "https://deadtoselfradio.com/images/d2slogo.jpg",
  "9b423ad10591d09a1f1b74011e2f8f943f475da3ac683c7322baae7b40c3f27f"),
 "go-station-000195":(
  "Babe Radio",
  "https://baberadio.net/assets/img/logo.png",
  "a93ab221a9fdef25eec0199c62bcdbce5b67b8f9889f2f1596b1d63b32830dc0"),
}


def load_evidence(folder:Path)->dict:
    result=[p for p in folder.rglob("GO-v8-90-firstparty-images-audit.json")
            if p.is_file() and not p.is_symlink()]
    if len(result)!=1 or result[0].stat().st_size>2*1024*1024:
        raise ValueError("Expected one immutable safe homepage image audit")
    data=json.loads(result[0].read_text(encoding="utf-8"))
    if (data.get("scope")!="GO_V8_90_OFFICIAL_SITE_BRAND_IMAGE_TRIAGE"
            or data.get("missing_stations")!=90
            or data.get("not_auto_approved") is not True
            or data.get("publish_allowed") is not False):
        raise ValueError("Homepage evidence is not an audited read-only report")
    matched={}
    for c in data.get("unique_firstparty_logo_candidates",[]):
        goid=c.get("go_station_id")
        if goid in APPROVED and c.get("sha256")==APPROVED[goid][2]:
            if goid in matched:
                raise ValueError("Ambiguous duplicate approved source")
            matched[goid]=c
    if set(matched)!=set(APPROVED):
        raise ValueError("Missing one of seven reviewed exact station source SHAs")
    return matched


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root",type=Path,required=True)
    args=parser.parse_args()
    if TARGET.exists() or ASSETS.exists():
        raise ValueError("Cannot overwrite prior SHA objects or unsigned catalog")
    prior=json.loads(BASE.read_bytes())
    if (prior.get("release_sequence")!=8 or len(prior["stations"])!=296
            or len(prior["tombstones"])!=24
            or sum(x["status"]["state"]=="active" and x["logo"] is None
                   for x in prior["stations"])!=90):
        raise ValueError("Unexpected reviewed unsigned v8 6-logo source")
    before={s["go_station_id"]:s for s in prior["stations"]}
    report=load_evidence(args.artifact_root.resolve())
    new_images={}
    existing={s["logo"]["sha256"] for s in prior["stations"] if s["logo"]}
    for goid,(label,url,digest) in APPROVED.items():
        st=before[goid]
        evidence=report[goid]
        if (st["display_name"]!=label or st["logo"] is not None
                or st["status"]["state"]!="active"
                or evidence["station_name"]!=label
                or evidence["logo_url"]!=url
                or evidence["sha256"]!=digest
                or evidence.get("status")!="FIRSTPARTY_BRAND_IMAGE_SHA_NEEDS_FINAL_IDENTITY_REVIEW"
                or evidence.get("eligible_for_second_byte_identical_validation") is True
                or evidence.get("mime_type") not in EXT
                or digest in existing):
            raise ValueError("Unapproved station/brand metadata or SHA")
        # The first-party image must belong to the same publisher's
        # catalogued website (including http->https conversion and www).
        canonical=(st.get("homepage") or "").lower().replace("http://","https://").replace("www.","")
        website=urlsplit(canonical).hostname
        image_host=urlsplit(url).hostname
        if not website or not image_host or not (
            image_host==website or image_host.endswith("."+website)
            or website.endswith("."+image_host)
        ):
            raise ValueError("Publisher station homepage does not match image host")
        raw,ctype,final=_request(
            url,max_bytes=MAX_IMAGE,accept="image/png,image/jpeg,image/webp")
        if urlsplit(final).hostname!=image_host:
            raise ValueError("Official image redirected outside publisher")
        metadata=inspect_bytes(raw,content_type=ctype)
        expected={k:evidence[k] for k in
                  ("sha256","mime_type","byte_size","width","height")}
        if metadata!=expected or hashlib.sha256(raw).hexdigest()!=digest:
            raise ValueError("Official logo SHA bytes changed since original site audit")
        new_images[goid]=(evidence,raw)
    if set(new_images)!=set(APPROVED) or len({
        v[0]["sha256"] for v in new_images.values()})!=7:
        raise ValueError("Seven independent real station images required")
    next_=deepcopy(prior)
    next_["generated_at"]="2026-11-23T11:35:00Z"
    for st in next_["stations"]:
        goid=st["go_station_id"]
        if goid not in new_images:
            continue
        ev,raw=new_images[goid]
        sha=ev["sha256"]
        st["logo"]={
            "asset_id":"sha256:"+sha,"sha256":sha,"revision":1,
            "url":RAW_PREFIX+sha+"."+EXT[ev["mime_type"]],
            "byte_size":ev["byte_size"],"width":ev["width"],
            "height":ev["height"],"mime_type":ev["mime_type"]
        }
    if (len(next_["stations"])!=296
            or next_["tombstones"]!=prior["tombstones"]
            or sum(s["status"]["state"]=="active" and s["logo"] is None
                   for s in next_["stations"])!=83
            or sum(s["status"]["state"]=="active" and s["logo"] is not None
                   for s in next_["stations"])!=202):
        raise ValueError("Unexpected change to v8 identities or missing-logo coverage")
    for st in next_["stations"]:
        old=before[st["go_station_id"]]
        if st["go_station_id"] in APPROVED:
            clone=deepcopy(st);clone["logo"]=None
            if clone!=old:
                raise ValueError("Radio altered beyond its logo")
        elif st!=old:
            raise ValueError("Unrelated station metadata mutated")
    for ev,raw in new_images.values():
        digest=ev["sha256"]
        destination=ASSETS/(digest+"."+EXT[ev["mime_type"]])
        destination.parent.mkdir(parents=True,exist_ok=True)
        if destination.exists():
            raise ValueError("Never overwrite a SHA filename")
        destination.write_bytes(raw)
    TARGET.parent.mkdir(parents=True,exist_ok=True)
    TARGET.write_text(json.dumps(next_,ensure_ascii=False,indent=2)+"\n",
                      encoding="utf-8")
    print(json.dumps({
        "result":"GO_V8_SEVEN_ADDITIONAL_OFFICIAL_SITE_LOGOS_STAGED_UNSIGNED",
        "new_first_party_sha_objects":7,
        "all_new_station_logos_v8":13,
        "active_radios":285,
        "active_with_logo":202,
        "active_missing_logo":83,
        "redirects_preserved":24,
        "signed":False,
        "published":False,
    },sort_keys=True))


if __name__=="__main__":
    main()
