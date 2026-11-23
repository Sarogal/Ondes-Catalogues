#!/usr/bin/env python3
"""READ-ONLY exact-site-image SHA qualification for 4 additional GO TEST v8 stations.

Station logo/source page associations were inspected on the original
publisher websites (Rockaxis, NTS The Pit, RSTLSS, Rock FM / Regenbogen 2)
on 2026-11-23. These are first-party channel/brand graphics, never album art.
An image URL alone is not approval: verify exact station identity, HTTP image
bytes, decoded image format/dimensions and distinct SHA-256 fingerprints.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit
from audit_open_radio_artwork_inventory import probe_image

ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/"radio-catalog-lab/full-staging/UNSIGNED-radio-v8-metalon-3-official-logos-20261123.json"
STATIONS={
    "go-station-000006":{
        "name":"Rockaxis Radio",
        "homepage":"https://www.rockaxis.com/",
        "stream_contains":"mdstrm.com/",
        "official_page":"https://www.rockaxis.com/",
        "page_label":"Rockaxis | Plataforma de contenidos y servicios",
        "image_url":"https://www.rockaxis.com/img/logoNO.png",
    },
    "go-station-000042":{
        "name":"The Pit | NTS",
        "homepage":"https://www.nts.live/infinite-mixtapes/the-pit",
        "stream_contains":"ntslive.net/mixtape34",
        "official_page":"https://www.nts.live/infinite-mixtapes/the-pit",
        "page_label":"The Pit - Infinite Mixtapes | Listen on NTS",
        "image_url":"https://media2.ntslive.co.uk/resize/1600x1600/9c9efb53-ce34-4a5e-997b-f8251be464a1_1668038400.jpeg",
    },
    "go-station-000091":{
        "name":"RSTLSS",
        "homepage":"https://rstlss.com/",
        "stream_contains":"stream.radiosolution.fr/rstlss.mp3",
        "official_page":"https://rstlss.com/",
        "page_label":"RSTLSS — Radio, podcasts et vidéos metal & rock",
        "image_url":"https://rstlss.com/logo-wordmark.png",
    },
    "go-station-000101":{
        "name":"REGENBOGEN 2 - METAL",
        "homepage":"https://www.regenbogen2.de/webradio/metal",
        "stream_contains":"stream.dar.fm/145322",
        "official_page":"https://www.rockfm.de/webradio/metal",
        "page_label":"Metal",
        "image_url":"https://image.atsw.de/atsw/production/2025-08/rockfm_cover_metal.jpg?width=360&height=360",
    },
}


def gather(network:bool)->dict:
    doc=json.loads(SOURCE.read_text(encoding="utf-8"))
    if doc["release_sequence"]!=8 or len(doc["stations"])!=296:
        raise ValueError("Expected unsigned v8 Metal ON source")
    byid={s["go_station_id"]:s for s in doc["stations"]}
    result=[]
    for id_,known in STATIONS.items():
        row=byid[id_]
        if (row["logo"] is not None or row["status"]["state"]!="active"
                or row["display_name"]!=known["name"]
                or row["homepage"]!=known["homepage"]
                or not any(known["stream_contains"] in s["url"] for s in row["streams"])):
            raise ValueError("Publisher station identity or original stream changed "+id_)
        logo_url=known["image_url"]
        host=urlsplit(logo_url).hostname
        if host not in {"www.rockaxis.com","media2.ntslive.co.uk","rstlss.com","image.atsw.de"}:
            raise ValueError("Unexpected official image host")
        evidence={
            "go_station_id":id_,
            "station_name":known["name"],
            "publisher_page":known["official_page"],
            "publisher_page_title_observed":known["page_label"],
            "browser_observed_station_image":logo_url,
            "source_evidence":"broadcaster_website_page_metadata_or_brand_logo",
            "editorial_review_required":True,
            "image_bytes_verified":False,
            "status":"OFFLINE_ONLY",
            "publication_allowed":False
        }
        if network:
            probe=probe_image(logo_url)
            if probe["verified_bytes"] is True:
                evidence.update({
                    "sha256":probe["sha256"],"byte_size":probe["byte_size"],
                    "mime_type":probe["mime_type"],
                    "width":probe["width"],"height":probe["height"],
                    "image_bytes_verified":True,
                    "status":"FIRST_PARTY_IMAGE_SHA_VERIFIED_PENDING_EDITORIAL",
                })
            else:
                evidence["status"]="OFFICIAL_IMAGE_NOT_VERIFIABLE"
                evidence["reason"]=probe.get("reason")
        result.append(evidence)
    bysha={}
    for r in result:
        if r.get("sha256"):
            bysha.setdefault(r["sha256"],[]).append(r["go_station_id"])
    for r in result:
        if r.get("sha256") and len(bysha[r["sha256"]])>1:
            r["image_bytes_verified"]=False
            r["status"]="SHARED_GENERIC_IMAGE_REJECTED"
    return {
        "scope":"GO_V8_FOUR_FIRSTPARTY_STATION_IMAGES_READ_ONLY",
        "source_release_sequence":8,
        "audited_station_count":4,
        "image_sha_verified_count":sum(x["image_bytes_verified"] for x in result),
        "unique_image_sha_count":len(bysha),
        "publication_allowed":False,
        "catalog_mutated":False,
        "records":result,
    }


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--network",action="store_true")
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    data=gather(args.network)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({
        "result":"GO_RADIO_V8_FOUR_SOURCE_LOGO_EVIDENCE_ONLY",
        "validated":data["image_sha_verified_count"],
        "of":4,
        "published":False
    },sort_keys=True))


if __name__=="__main__":
    main()
