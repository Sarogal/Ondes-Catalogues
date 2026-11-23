#!/usr/bin/env python3
"""Read-only first-party laut.fm station logo discovery for signed TEST v7.

Resolve each station by its actual audio/homepage slug, call the public
laut.fm station JSON API, require matching station name, inspect ONLY the
station logo fields (not album art), then verify image bytes/MIME/dimensions
and SHA-256 from first-party LAUT servers.

This tool NEVER modifies catalog, signs data, changes station IDs or publishes.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import ssl
from urllib.parse import urlparse, unquote
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

from audit_open_radio_artwork_inventory import probe_image, public_https

ROOT=Path(__file__).resolve().parents[2]
DRAFT=ROOT/"radio-catalog-lab/full-staging/UNSIGNED-radio-v7-13-programs-dedupe-20261123.json"
NAME=re.compile(r"^[a-z0-9][a-z0-9_-]{1,80}$")
ORDER=["station_640x640","station_500x500","station_200x200",
       "station_120x120","station_100x100","station"]
LAUT_HOSTS={"api.laut.fm","assets.laut.fm"}
OTHER_ASSET_PREFIX=("assets.laut.fm",)


def radio_slug(s:dict)->str|None:
    urls=[x["url"] for x in s["streams"]]+[s.get("homepage") or ""]
    for v in urls:
        if not isinstance(v,str):
            continue
        parsed=urlparse(v)
        host=(parsed.hostname or "").lower()
        path=unquote(parsed.path).strip("/")
        slug=None
        if (host=="stream.laut.fm" or host.endswith(".stream.laut.fm")
            or host=="laut.fm" or host=="www.laut.fm"):
            # Strip query; the stream's root path is the LAUT station slug.
            slug=path.split("/")[0] if path else None
        if slug and NAME.fullmatch(slug.lower()):
            return slug.lower()
    return None


def source_stations()->list[tuple[dict,str]]:
    doc=json.loads(DRAFT.read_text(encoding="utf-8"))
    if doc["release_sequence"]!=7 or len(doc["stations"])!=296:
        raise ValueError("Wrong unsigned v7 source")
    out=[]
    for s in doc["stations"]:
        if s["status"]["state"]!="active" or s["logo"] is not None:
            continue
        slug=radio_slug(s)
        if slug:
            out.append((s,slug))
    if len(out)!=14:
        raise ValueError("Expected exactly 14 missing LAUT logos, found "+str(len(out)))
    if len({x["go_station_id"] for x,_ in out})!=14:
        raise ValueError("Duplicate GO ID")
    return out


def get_metadata(slug:str)->dict:
    if not NAME.fullmatch(slug):
        raise ValueError("Unsafe laut.fm station slug")
    url="https://api.laut.fm/station/"+slug
    req=Request(url,headers={"User-Agent":"GrossesOndesRadioAudit/1.0",
                            "Accept":"application/json"})
    with urlopen(req,timeout=15) as response:
        if response.status!=200 or response.geturl()!=url:
            raise ValueError("Station API HTTP or redirect unexpectedly changed")
        data=response.read(300*1024+1)
        if len(data)>300*1024:
            raise ValueError("Station metadata oversized")
        obj=json.loads(data)
    if not isinstance(obj,dict) or obj.get("name","").casefold()!=slug.casefold():
        raise ValueError("Station metadata identity does not match audio slug")
    return obj


def images_in_station(obj:dict)->dict[str,str]:
    images=obj.get("images")
    if not isinstance(images,dict):
        return {}
    accepted={}
    for k in ORDER:
        v=images.get(k)
        if not isinstance(v,str) or not public_https(v):
            continue
        if urlparse(v).hostname not in LAUT_HOSTS:
            continue
        accepted[k]=v
    return accepted


def gather(*,network:bool)->dict:
    out=[]
    for station,slug in source_stations():
        row={"go_station_id":station["go_station_id"],
             "catalog_station_name":station["display_name"],
             "verified_stream_slug":slug,
             "official_station_api":"https://api.laut.fm/station/"+slug,
             "metadata_name_matches_slug":False,
             "official_logo_url":None,
             "verified_sha256":None,
             "mime_type":None,
             "byte_size":None,
             "width":None,
             "height":None,
             "status":"OFFLINE_AUDIT_ONLY",
             "approval_for_publication":False}
        if network:
            try:
                obj=get_metadata(slug)
                row["metadata_name_matches_slug"]=True
                links=images_in_station(obj)
                row["available_official_image_types"]=sorted(links)
                if not links:
                    row["status"]="NO_STATION_LOGO_IN_OFFICIAL_API"
                else:
                    k=next(key for key in ORDER if key in links)
                    url=links[k]
                    row["official_image_key"]=k
                    row["official_logo_url"]=url
                    # This bounded downloader refuses private hosts/oversize etc.
                    verified=probe_image(url)
                    if verified.get("verified_bytes") is True:
                        row.update({
                            "verified_sha256":verified["sha256"],
                            "mime_type":verified["mime_type"],
                            "byte_size":verified["byte_size"],
                            "width":verified["width"],
                            "height":verified["height"],
                            "status":"OFFICIAL_LAUTFM_IMAGE_SHA_VERIFIED",
                        })
                    else:
                        row["status"]="IMAGE_UNAVAILABLE_OR_SHA_UNVERIFIED"
                        row["image_error"]=verified.get("reason")
            except (HTTPError,URLError,ValueError,TimeoutError,
                    ssl.SSLError, OSError,TypeError) as err:
                row["status"]="OFFICIAL_STATION_METADATA_NOT_VERIFIED"
                row["error_type"]=type(err).__name__
        out.append(row)
    return {"schema_version":1,"scope":"TEST_V7_LAUTFM_14_FIRST_PARTY_LOGOS_READ_ONLY",
            "stations":len(out),
            "official_metadata_verified":sum(x["metadata_name_matches_slug"] for x in out),
            "logo_bytes_verified":sum(x["status"]=="OFFICIAL_LAUTFM_IMAGE_SHA_VERIFIED" for x in out),
            "catalog_modified":False,"publication_allowed":False,
            "records":out}


def main()->None:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--network",action="store_true")
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    report=gather(network=a.network)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",
                        encoding="utf-8")
    print(json.dumps({
        "status":"GO_V7_LAUTFM_LOGO_EVIDENCE_ONLY",
        "stations":report["stations"],
        "metadata_verified":report["official_metadata_verified"],
        "logo_sha_verified":report["logo_bytes_verified"],
        "publication_allowed":False,
    },sort_keys=True))


if __name__=="__main__":
    main()
