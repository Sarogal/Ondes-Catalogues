#!/usr/bin/env python3
"""Read-only SHA-256 qualification of five broadcaster-original Exclusively tiles.

The five exact image URLs were obtained via a live DOM inspection of the
corresponding you.radio station pages (23 Nov 2026), NOT guessed from names
or generic genre logos. Exact browser-observed station page and image path
are pinned. Verify actual image bytes and distinct SHA before any staging.
The Led Zeppelin HITS channel is separate from regular Led Zeppelin.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlparse

from audit_open_radio_artwork_inventory import probe_image

ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/"radio-catalog-lab/full-staging/UNSIGNED-radio-v7-13-programs-lautfm-14-20261123.json"
BROADCASTER={
 "go-station-000204":(
    "ledzeppelinhits",
    "https://you.radio/station/exclusivehits-led-zeppelin-hits",
    "https://manager.uber.radio/static/uploads/station/068f1883-27ae-4e57-98d5-bd6e8cc9a10a.jpg"),
 "go-station-000272":(
    "deeppurple",
    "https://you.radio/station/exclusiveradio-deep-purple",
    "https://manager.uber.radio/static/uploads/station/40cdc2d3-c395-400a-9a78-75c6b85f9fa7.jpg"),
 "go-station-000274":(
    "ledzeppelin",
    "https://you.radio/station/exclusiveradio-led-zeppelin",
    "https://manager.uber.radio/static/uploads/station/356587c2-2712-4884-9d54-84d4f53dfc2d.jpg"),
 "go-station-000299":(
    "ironmaiden",
    "https://you.radio/station/exclusiveradio-iron-maiden",
    "https://manager.uber.radio/static/uploads/station/a1f58d1b-8bdc-4c05-9c2e-20399d7ce1a7.jpg"),
 "go-station-000311":(
    "ramones",
    "https://you.radio/station/exclusiveradio-ramones",
    "https://manager.uber.radio/static/uploads/station/e7447a7c-86cf-4313-8191-d1e764c88c2c.jpg"),
}


def verify(network:bool)->dict:
    doc=json.loads(SOURCE.read_text(encoding="utf-8"))
    if (doc.get("release_sequence")!=7 or len(doc["stations"])!=296
            or sum(s["logo"] is not None for s in doc["stations"])!=189):
        raise ValueError("Missing prior LAUT signed-identity verification")
    stations={x["go_station_id"]:x for x in doc["stations"]}
    records=[]
    for goid,(slug,page,cdn) in BROADCASTER.items():
        st=stations[goid]
        if (st["status"]["state"]!="active" or st["logo"] is not None
                or not any("/"+slug+"/" in s["url"].lower()
                           and "streaming.exclusive.radio" in s["url"].lower()
                           for s in st["streams"])
                or urlparse(page).hostname!="you.radio"
                or urlparse(cdn).hostname!="manager.uber.radio"
                or not urlparse(cdn).path.startswith("/static/uploads/station/")):
            raise ValueError("Untrusted broadcaster/page/stream identity "+goid)
        rec={"go_station_id":goid,"stream_program_slug":slug,
             "broadcaster_station_page":page,
             "broadcaster_station_image_url":cdn,
             "station_dom_verified_in_browser":True,
             "download_verified_sha":False,
             "editorial_publication_approved":False,
             "status":"NO_NETWORK"}
        if network:
            data=probe_image(cdn)
            if data.get("verified_bytes") is True:
                rec.update({"status":"OFFICIAL_IMAGE_BYTES_VERIFIED",
                            "download_verified_sha":True,
                            "sha256":data["sha256"],
                            "mime_type":data["mime_type"],
                            "byte_size":data["byte_size"],
                            "width":data["width"],
                            "height":data["height"]})
            else:
                rec.update({"status":"OFFICIAL_IMAGE_NOT_AVAILABLE",
                            "error":data.get("reason")})
        records.append(rec)
    hashes={}
    for rec in records:
        sha=rec.get("sha256")
        if sha:
            hashes.setdefault(sha,[]).append(rec["go_station_id"])
    # The broadcaster intentionally uses the same artist tile for Led
    # Zeppelin regular and HITS. Their station IDs and stream slugs remain
    # DISTINCT; shared image SHA is safe *only* for this exact pair and not
    # for unrelated artists or a generic fallback.
    allowed_shared={"go-station-000204","go-station-000274"}
    for rec in records:
        sha=rec.get("sha256")
        if not sha or len(hashes[sha])==1:
            continue
        owners=set(hashes[sha])
        if owners==allowed_shared:
            rec["status"]="OFFICIAL_SHARED_ARTIST_STATION_TILE_VERIFIED"
        else:
            rec["status"]="DUPLICATED_GENERIC_IMAGE_UNSAFE"
            rec["editorial_publication_approved"]=False
    valid=[r for r in records if r["status"] in {
        "OFFICIAL_IMAGE_BYTES_VERIFIED",
        "OFFICIAL_SHARED_ARTIST_STATION_TILE_VERIFIED"} and
        r["width"]>=100 and r["height"]>=100]
    return {"scope":"TEST_V7_EXCLUSIVELY_5_BROADCASTER_ORIGINAL_TILES",
            "requested_stations":5,
            "verified_station_logo_count":len(valid),
            "verified_unique_sha_count":len({r["sha256"] for r in valid}),
            "shared_artist_pair_only":all(
                set(v)==allowed_shared for v in hashes.values() if len(v)>1),
            "main_or_test_pointer_edited":False,
            "publication_allowed":False,
            "records":records}


def main()->None:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--network",action="store_true")
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    report=verify(network=args.network)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",
                           encoding="utf-8")
    print(json.dumps({"result":"GO_V7_EXCLUSIVELY_OFFICIAL_FIVE_SHA_EVIDENCE",
                      "verified_stations":report["verified_station_logo_count"],
                      "unique_sha":report["verified_unique_sha_count"],
                      "requested":report["requested_stations"],
                      "publication_allowed":False},sort_keys=True))


if __name__=="__main__":
    main()
