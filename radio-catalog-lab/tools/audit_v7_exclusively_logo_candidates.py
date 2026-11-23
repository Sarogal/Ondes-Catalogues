#!/usr/bin/env python3
"""Read-only station-specific myTuner images for five Exclusively radio channels.

The upstream you.radio/exclusive.radio site serves dynamic content. myTuner
station directory exposes a distinct station-logo image on each station page.
Require title + exact independently observed image filename + matching
stream programme slug before verifying downloaded bytes and SHA-256.

An image isn't editorially approved for publication until both provenance
and byte checks pass. This script only reports evidence, never changes
a catalog or writes a signed bundle.
"""
from __future__ import annotations

import argparse
from html import unescape
import json
from pathlib import Path
from urllib.parse import urlparse
from urllib.error import HTTPError, URLError
import ssl

from audit_open_radio_artwork_inventory import _request, inspect_bytes, MAX_HTML, MAX_IMAGE

ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/"radio-catalog-lab/full-staging/UNSIGNED-radio-v7-13-programs-lautfm-14-20261123.json"
CHANNELS={
 "go-station-000204":(
    "Exclusively Led Zeppelin - Only Hits","ledzeppelinhits",
    "https://mytuner-radio.com/fr/radio/exclusively-led-zeppelin-hits-498210/",
    "https://static2.mytuner.mobi/media/tvos_radios/ewuxpkuyy27s.png"),
 "go-station-000272":(
    "Exclusively Deep Purple","deeppurple",
    "https://mytuner-radio.com/radio/exclusively-deep-purple-472990/",
    "https://static2.mytuner.mobi/media/tvos_radios/pvq8m248eldt.png"),
 "go-station-000274":(
    "Exclusively Led Zeppelin","ledzeppelin",
    "https://mytuner-radio.com/radio/exclusively-led-zeppelin-471681/",
    "https://static2.mytuner.mobi/media/tvos_radios/2vahc9bvseyy.png"),
 "go-station-000299":(
    "Exclusively Iron Maiden","ironmaiden",
    "https://mytuner-radio.com/radio/exclusively-iron-maiden-473710/",
    "https://static2.mytuner.mobi/media/tvos_radios/nkuzdhvtyn7e.png"),
 "go-station-000311":(
    "Exclusively Ramones","ramones",
    "https://mytuner-radio.com/es/emisora/exclusively-ramones-473274/",
    "https://static2.mytuner.mobi/media/tvos_radios/k83snrz55vtm.png"),
}


def stations()->dict:
    obj=json.loads(SOURCE.read_text(encoding="utf-8"))
    if (obj["release_sequence"]!=7 or len(obj["stations"])!=296 or
            sum(s["logo"] is not None for s in obj["stations"])!=189):
        raise ValueError("Unexpected reviewed v7 + 14 LAUT logo source")
    return {s["go_station_id"]:s for s in obj["stations"]}


def audit(network:bool)->dict:
    byid=stations()
    out=[]
    for goid,(title,slug,page,logo_url) in CHANNELS.items():
        st=byid[goid]
        if (st["status"]["state"]!="active" or st["logo"] is not None
                or title.casefold() not in st["display_name"].casefold()
                or not any("/"+slug+"/" in u["url"].lower() and
                           "streaming.exclusive.radio" in u["url"].lower()
                           for u in st["streams"])):
            raise ValueError("Untrusted Exclusively station/channel mapping: "+goid)
        row={"go_station_id":goid,"program":slug,
             "station_name":title,"directory_page":page,
             "directory_station_logo_url":logo_url,
             "page_provenance_verified":False,
             "download_verified_sha":False,
             "publication_allowed":False,
             "status":"OFFLINE_PROVENANCE_ONLY"}
        if network:
            try:
                html,mime,final=_request(page,max_bytes=MAX_HTML,accept="text/html")
                if urlparse(final).hostname!="mytuner-radio.com":
                    raise ValueError("Untrusted directory page redirect")
                if mime not in {"text/html","application/xhtml+xml",""}:
                    raise ValueError("Station directory isn't HTML")
                text=unescape(html.decode("utf-8",errors="replace"))
                if (title.casefold() not in text.casefold()
                        or logo_url.split("/")[-1] not in text):
                    raise ValueError("Station-specific directory logo not on expected page")
                row["page_provenance_verified"]=True
                data,image_mime,final_image=_request(
                    logo_url,max_bytes=MAX_IMAGE,accept="image/png,image/jpeg,image/webp")
                if urlparse(final_image).hostname!="static2.mytuner.mobi":
                    raise ValueError("Directory logo redirected outside trusted host")
                meta=inspect_bytes(data,content_type=image_mime)
                if meta["width"]<80 or meta["height"]<80:
                    raise ValueError("Too small to be a station logo")
                row.update({"status":"STATION_PAGE_IMAGE_SHA_VERIFIED",
                            "download_verified_sha":True,
                            "sha_evidence":meta})
            except (ValueError,HTTPError,URLError,TimeoutError,
                    OSError,ssl.SSLError) as err:
                row["status"]="PROVENANCE_OR_IMAGE_NOT_VERIFIED"
                row["error_type"]=type(err).__name__
        out.append(row)
    return {"scope":"TEST_V7_EXCLUSIVELY_5_STATION_LOGOS_READ_ONLY",
            "catalog_seq":7,
            "missing_source_stations":5,
            "verified_page_and_image_count":sum(r["download_verified_sha"] and
                r["page_provenance_verified"] for r in out),
            "publication_allowed":False,
            "records":out}


def main()->None:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--network",action="store_true")
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    result=audit(network=args.network)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",
                           encoding="utf-8")
    print(json.dumps({"result":"GO_V7_EXCLUSIVELY_LOGO_EVIDENCE_ONLY",
                      "verified":result["verified_page_and_image_count"],
                      "expected":5,"publication_allowed":False}))


if __name__=="__main__":
    main()
