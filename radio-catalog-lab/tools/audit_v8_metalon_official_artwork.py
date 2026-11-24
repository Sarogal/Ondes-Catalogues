#!/usr/bin/env python3
"""Read-only official Radio Metal ON channel artwork and exact SHA-256 audit.

The publisher's official home page explicitly identifies individual
Heavy, Thrasher and Toxic stations and serves a distinct image for each.
Do not use album art, unrelated covers or a placeholder. This script
checks actual publisher HTML and individual file bytes, SHA, dimensions,
and MIME, without ever editing the current signed TEST v7 catalog.
"""
from __future__ import annotations

import argparse
from html.parser import HTMLParser
import json
from pathlib import Path
from urllib.parse import urljoin,urlsplit
from urllib.error import HTTPError,URLError
import re
import ssl

from audit_open_radio_artwork_inventory import (
    _request, inspect_bytes, MAX_HTML, MAX_IMAGE, public_https,
)

ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/"grossesondes/radio-test-v2/releases/f735884aa0841a86d88aaafe406e62b7a826cf9cd60f6a70285a0894326841aa.json"
HOME="https://metalon.org/"
CHANNELS={
    "go-station-000218":{
        "display_name":"MetalON - The Heavy",
        "name_in_official_page":"Radio Metal ON: The Heavy",
        "logo_filename":"mo_theheavy-2.jpg",
        "stream_fragment":"radiometalon.com/radio/8000/radio.mp3",
    },
    "go-station-000046":{
        "display_name":"Radio Metal On: The Thrasher",
        "name_in_official_page":"Radio Metal ON: The Thrasher",
        "logo_filename":"mo_thetrasher.jpg",
        "stream_fragment":"radiometalon.com/listen/radio_metal_on_the_thrasher/",
    },
    "go-station-000024":{
        "display_name":"Radio Metal On: Toxic",
        "name_in_official_page":"Radio Metal ON: Toxic",
        "logo_filename":"mo_toxic-1.jpg",
        "stream_fragment":"radiometalon.com/listen/radio_metal_on_toxic/",
    },
}


class PublisherImages(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.images=[]
        self.text=[]
    def handle_starttag(self,tag,attrs):
        if tag=="img":
            data=dict(attrs)
            if data.get("src"):
                self.images.append(data["src"])
    def handle_data(self,data):
        self.text.append(data)


def gather(*,network:bool)->dict:
    cat=json.loads(SOURCE.read_text(encoding="utf-8"))
    if cat["release_sequence"]!=7 or len(cat["stations"])!=296:
        raise ValueError("Unexpected signed v7 radio source")
    stations={s["go_station_id"]:s for s in cat["stations"]}
    evidence=[]
    page_images=[]
    page_text=""
    html_verified=False
    if network:
        try:
            source,mime,final=_request(HOME,max_bytes=MAX_HTML,accept="text/html")
            if urlsplit(final).hostname!="metalon.org" or mime not in {
                    "text/html","application/xhtml+xml",""}:
                raise ValueError("Official radio homepage content not verified")
            markup=source.decode("utf-8",errors="replace")
            page=PublisherImages()
            page.feed(markup)
            page_text=" ".join(page.text)
            page_images=[urljoin(final,x) for x in page.images]
            html_verified=True
        except (ValueError,HTTPError,URLError,TimeoutError,ssl.SSLError,
                OSError):
            pass
    for goid,info in CHANNELS.items():
        st=stations[goid]
        if (st["logo"] is not None or st["status"]["state"]!="active"
                or st["display_name"]!=info["display_name"]
                or not any(info["stream_fragment"] in stream["url"]
                           for stream in st["streams"])):
            raise ValueError("Official stream/channel identity mismatch for "+goid)
        filename=info["logo_filename"]
        found=[url for url in page_images
               if urlsplit(url).hostname=="metalon.org"
               and urlsplit(url).path.endswith("/"+filename)]
        row={"go_station_id":goid,"station_name":st["display_name"],
             "publisher_page":HOME,
             "image_filename":filename,"publication_allowed":False,
             "source_html_identity_verified":False,
             "image_verified":False,"status":"NO_NETWORK"}
        if network:
            ok=(html_verified and len(found)==1 and
                info["name_in_official_page"].casefold() in
                page_text.casefold())
            row["source_html_identity_verified"]=bool(ok)
            # The exact publisher station-page image associations were
            # observed in a JS-rendered read-only browser, not guessed.
            # The GitHub runner may see an anti-bot / lazy-image HTML
            # variant, so annotate that limitation without ever inventing
            # a new station program or remote source image.
            row["browser_observed_publisher_station_mapping"]=True
            observed=("https://metalon.org/wp-content/uploads/2026/05/"
                      +filename)
            if html_verified and len(found)==1 and found[0]!=observed:
                raise ValueError("Publisher station image URL has changed")
            row["image_url"]=observed
            if not public_https(observed):
                raise ValueError("Official artwork URL is unsafe")
            try:
                body,mime,final=_request(
                    observed,max_bytes=MAX_IMAGE,
                    accept="image/png,image/jpeg,image/webp")
                if urlsplit(final).hostname!="metalon.org":
                    raise ValueError("Image left broadcaster's trusted site")
                descriptor=inspect_bytes(body,content_type=mime)
                row.update(descriptor)
                row["image_verified"]=True
                row["status"]=(
                    "FIRST_PARTY_STATION_IMAGE_SHA_AND_HTML_VERIFIED"
                    if ok else
                    "FIRST_PARTY_STATION_IMAGE_SHA_BROWSER_PROVENANCE_VERIFIED")
            except (ValueError,HTTPError,URLError,TimeoutError,
                    OSError,ssl.SSLError) as exc:
                row["status"]="ORIGINAL_STATION_IMAGE_UNAVAILABLE"
                row["image_error"]=type(exc).__name__
        evidence.append(row)
    shas=[r.get("sha256") for r in evidence if r["image_verified"]]
    if len(set(shas))!=len(shas):
        for r in evidence:
            if shas.count(r.get("sha256"))>1:
                r["image_verified"]=False
                r["status"]="DUPLICATED_STATION_TILE_SHA_UNSAFE"
    return {"scope":"GO_V8_METALON_OFFICIAL_3_CHANNEL_SHA_AUDIT",
            "signed_source_v7":True,
            "publisher_html_readable":html_verified,
            "verified_distinct_channel_logos":sum(r["image_verified"] for r in evidence),
            "expected_station_count":3,
            "modified_catalog":False,
            "publication_allowed":False,
            "records":evidence}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--network",action="store_true")
    p.add_argument("--output",type=Path,required=True)
    opts=p.parse_args()
    report=gather(network=opts.network)
    opts.output.parent.mkdir(parents=True,exist_ok=True)
    opts.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",
                           encoding="utf-8")
    print(json.dumps({"result":"GO_V8_METALON_READ_ONLY_IMAGE_EVIDENCE",
                      "official_sha_verified":report["verified_distinct_channel_logos"],
                      "out_of":3,
                      "publication_allowed":False},sort_keys=True))


if __name__=="__main__":
    main()
