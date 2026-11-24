#!/usr/bin/env python3
"""Create unsigned Grosses Ondes TEST v8 with 3 official Metal ON logos only.

Read original Ed25519-signed TEST v7 and independently reviewed first-party
station image SHA evidence from GitHub Actions #45161806138. Download the
exact official images a SECOND time, recheck bytes/MIME/dimensions/SHA, and
store 3 content-addressed assets on development branch only.

No signed pointer, private signing key, TEST v7, main or production changes.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

from audit_open_radio_artwork_inventory import _request,inspect_bytes,MAX_IMAGE
from audit_v8_metalon_official_artwork import CHANNELS

ROOT=Path(__file__).resolve().parents[2]
SIGNED=ROOT/"grossesondes/radio-test-v2"
SOURCE=SIGNED/"releases/f735884aa0841a86d88aaafe406e62b7a826cf9cd60f6a70285a0894326841aa.json"
SOURCE_SHA="f735884aa0841a86d88aaafe406e62b7a826cf9cd60f6a70285a0894326841aa"
TARGET=ROOT/"radio-catalog-lab/full-staging/UNSIGNED-radio-v8-metalon-3-official-logos-20261123.json"
ASSETS=SIGNED/"artwork/staging-metalon-v8"
RAW_PREFIX=("https://raw.githubusercontent.com/Sarogal/Ondes-Catalogues/"
            "feature/go-radio-v8-metalon-3-logos-20261123/"
            "grossesondes/radio-test-v2/artwork/staging-metalon-v8/")
EXT={"image/jpeg":"jpg","image/png":"png","image/webp":"webp"}
EXPECTED={
    "go-station-000218":"64b499012b0e6f64ff0eca85ef69772e6e9c800c3661d4d73dad7e0b99e41503",
    "go-station-000046":"c17784a27ff5972c60ea10c716f2921f8a60b4af9e9d2015d13da5952389a31f",
    "go-station-000024":"ca6c81dc2248f5d04c93d0e7270ec7470503295604ccccd48c8d45545c7c8ad5",
}


def evidence(folder:Path)->list[dict]:
    files=[p for p in folder.rglob("metalon-verified.json")
           if p.is_file() and not p.is_symlink()]
    if len(files)!=1 or files[0].stat().st_size>120*1024:
        raise ValueError("Expected one official MetalON SHA evidence report")
    data=json.loads(files[0].read_text(encoding="utf-8"))
    if (data.get("scope")!="GO_V8_METALON_OFFICIAL_3_CHANNEL_SHA_AUDIT"
            or data.get("verified_distinct_channel_logos")!=3
            or data.get("expected_station_count")!=3
            or data.get("modified_catalog") is not False
            or data.get("publication_allowed") is not False
            or len(data.get("records",[]))!=3):
        raise ValueError("Incomplete or non-read-only first-party source evidence")
    return data["records"]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--artifact-root",type=Path,required=True)
    a=p.parse_args()
    if TARGET.exists() or ASSETS.exists():
        raise ValueError("Refusing overwrite of previous SHA images or unsigned v8")
    raw=SOURCE.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=SOURCE_SHA:
        raise ValueError("Signed v7 source payload SHA mismatch")
    previous=json.loads(raw)
    if (previous["release_sequence"]!=7 or len(previous["stations"])!=296
            or len(previous["tombstones"])!=24
            or sum(s["status"]["state"]=="active" for s in previous["stations"])!=285
            or sum(s["status"]["state"]=="active" and s["logo"] is None
                   for s in previous["stations"])!=96):
        raise ValueError("Unexpected signed v7 baseline")
    byid={s["go_station_id"]:s for s in previous["stations"]}
    report=evidence(a.artifact_root.resolve())
    originals={}
    for rec in report:
        goid=rec.get("go_station_id")
        if goid not in EXPECTED or goid in originals:
            raise ValueError("Unexpected/duplicated Metal ON GO ID")
        identity=CHANNELS[goid]
        station=byid[goid]
        if (rec.get("station_name")!=station["display_name"]
                or rec.get("publisher_page")!="https://metalon.org/"
                or rec.get("image_filename")!=identity["logo_filename"]
                or rec.get("status") not in {
                    "FIRST_PARTY_STATION_IMAGE_SHA_AND_HTML_VERIFIED",
                    "FIRST_PARTY_STATION_IMAGE_SHA_BROWSER_PROVENANCE_VERIFIED"}
                or rec.get("browser_observed_publisher_station_mapping") is not True
                or rec.get("image_verified") is not True
                or rec.get("publication_allowed") is not False
                or rec.get("sha256")!=EXPECTED[goid]
                or rec.get("mime_type") not in EXT):
            raise ValueError("Invalid official image identity / SHA evidence")
        url=rec.get("image_url")
        if (url!="https://metalon.org/wp-content/uploads/2026/05/"+
            identity["logo_filename"]
            or urlsplit(url).hostname!="metalon.org"):
            raise ValueError("Official image URL changed")
        if (station["status"]["state"]!="active" or station["logo"] is not None
                or not any(identity["stream_fragment"] in s["url"]
                           for s in station["streams"])):
            raise ValueError("Source radio no longer matches original audio stream")
        data,mime,final=_request(url,max_bytes=MAX_IMAGE,
                                 accept="image/png,image/jpeg,image/webp")
        if urlsplit(final).hostname!="metalon.org":
            raise ValueError("Image left first-party publisher host")
        checked=inspect_bytes(data,content_type=mime)
        required={k:rec[k] for k in
                  ("sha256","byte_size","mime_type","width","height")}
        if (checked!=required or
                hashlib.sha256(data).hexdigest()!=EXPECTED[goid]):
            raise ValueError("First-party image bytes changed since signed evidence")
        originals[goid]=(rec,data)
    if set(originals)!=set(EXPECTED) or len({x[0]["sha256"] for x in originals.values()})!=3:
        raise ValueError("All 3 distinct source station images required")

    new=deepcopy(previous)
    new["release_sequence"]=8
    new["generated_at"]="2026-11-23T11:10:00Z"
    for st in new["stations"]:
        goid=st["go_station_id"]
        if goid not in originals:
            continue
        rec,data=originals[goid]
        digest=rec["sha256"]
        ext=EXT[rec["mime_type"]]
        st["logo"]={
            "asset_id":"sha256:"+digest,
            "sha256":digest,
            "revision":1,
            "url":RAW_PREFIX+digest+"."+ext,
            "byte_size":rec["byte_size"],
            "width":rec["width"],
            "height":rec["height"],
            "mime_type":rec["mime_type"],
        }
    if (new["tombstones"]!=previous["tombstones"]
            or len(new["stations"])!=296
            or sum(s["status"]["state"]=="active" for s in new["stations"])!=285
            or sum(s["status"]["state"]=="active" and s["logo"] is None
                   for s in new["stations"])!=93
            or sum(s["status"]["state"]=="active" and s["logo"] is not None
                   for s in new["stations"])!=192):
        raise ValueError("Unsigned v8 station/redirect/logo invariant mismatch")
    old_byid={s["go_station_id"]:s for s in previous["stations"]}
    for station in new["stations"]:
        prior=old_byid[station["go_station_id"]]
        if station["go_station_id"] not in originals:
            if station!=prior:
                raise ValueError("Unrelated active station mutated")
        else:
            copy=deepcopy(station)
            copy["logo"]=None
            if copy!=prior:
                raise ValueError("Only station logo may change")
    # Store only after full metadata/image/diff validation completes.
    for rec,data in originals.values():
        sha=rec["sha256"]
        ext=EXT[rec["mime_type"]]
        blob=ASSETS/(sha+"."+ext)
        if blob.exists():
            raise ValueError("Refusing to overwrite content-addressed logo")
        blob.parent.mkdir(parents=True,exist_ok=True)
        blob.write_bytes(data)
    TARGET.parent.mkdir(parents=True,exist_ok=True)
    TARGET.write_text(json.dumps(new,ensure_ascii=False,indent=2)+"\n",
                      encoding="utf-8")
    print(json.dumps({
        "result":"GO_RADIO_V8_METALON_3_SIGNABLE_LOGOS_STAGED_DEV_ONLY",
        "new_verified_firstparty_logo_assets":3,
        "active_stations":285,
        "station_ids_preserved":320,
        "active_logos":192,
        "active_without_logo":93,
        "tombstone_redirects":24,
        "signed":False,
        "published_to_active_test":False,
    },sort_keys=True))


if __name__=="__main__":
    main()
