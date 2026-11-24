#!/usr/bin/env python3
"""Read-only 3-channel Radio MAXIMUM original-image verification for GO TEST v8.

Uses broadcaster's own /online page and three manually inspected channel
images. Matches exact signed-model station/stream identity, channel labels,
publisher image URLs, safe HTTPS/DNS and decoded SHA-256. Never auto-approves,
signs, publishes or edits a catalogue.
"""
from __future__ import annotations
import argparse
from html.parser import HTMLParser
import json
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit
from urllib.error import HTTPError, URLError
import ssl

from audit_open_radio_artwork_inventory import (
    _request, inspect_bytes, MAX_HTML, MAX_IMAGE,
)

ROOT=Path(__file__).resolve().parents[2]
CANDIDATE=ROOT/"radio-catalog-lab/full-staging/UNSIGNED-radio-v8-metalon-3-independent-3-firstparty-7-20261123.json"
HOME="https://maximum.ru/online"
CHANNELS={
    "go-station-000002": {
        "name":"Radio Maximum - Supernova",
        "alt":"SUPERNOVA",
        "stream":"maximum-unplugged.hostingradio.ru/maxunplugged96.aacp",
        "source":"https://maximum.ru/b/d/XS_d975tAlQXa91cOSXkSpxhI6gWWQ8KdoKmPd7GV5nvNwe0Y21o10ROCTMBoxQZhTpBpL_7WaXQC8Omvy2GX15bEG0PwNABBUM%3DNgbbbCI0OkXmItNxfuw0HA.webp",
    },
    "go-station-000041": {
        "name":"Radio Maximum - Heavy 80s",
        "alt":"HEAVY 80s",
        "stream":"maximum80.hostingradio.ru/max8096.aacp",
        "source":"https://maximum.ru/b/d/XS_d975tAlQXa9tcOSXkSpxhI6gWWQ8KdoKmPd7GV5nvNwe0Y21o10ROCTMBoxQZhTpBpL_7WaXQC8Omvy2GX15bEG0PwNABBUM%3DEHFyEg_-itFML68EXejnjw.webp",
    },
    "go-station-000263": {
        "name":"Radio Maximum - Heavy Monday",
        "alt":"Heavy Monday",
        "stream":"heavymonday.hostingradio.ru/heavymonday96.aacp",
        "source":"https://maximum.ru/b/d/XS_d975tAlEVac1XK230SJFobrEVWw8TZNSuLMuPG5jmPhalL38hwFVPDi9H-l8biCMIubfiQrLGQsGovSmGX15HSCNC0tcTXA%3D-l14gPD1AGgbDaBPcZdbbw.webp",
    },
}

class PublisherImages(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.pairs=[]
    def handle_starttag(self,tag,attrs):
        if tag.lower() != "img":
            return
        a=dict(attrs)
        alt=(a.get("alt") or "").strip().casefold()
        sources=[a.get(k) for k in ("src","data-src","data-original") if a.get(k)]
        if a.get("srcset"):
            sources.extend(part.strip().split()[0] for part in a["srcset"].split(",") if part.strip())
        for src in sources:
            self.pairs.append((alt,src))

def norm_url(value):
    p=urlsplit(value)
    return (p.scheme,p.hostname,unquote(p.path),p.query)

def audit(network=False):
    doc=json.loads(CANDIDATE.read_bytes())
    active=[x for x in doc["stations"] if x["status"]["state"]=="active"]
    if (doc["release_sequence"]!=8 or len(doc["stations"])!=296
            or len(doc["tombstones"])!=24 or len(active)!=285
            or sum(x["logo"] is None for x in active)!=83):
        raise ValueError("Expected existing unsigned v8 with 13 added logos")
    stations={s["go_station_id"]:s for s in active}
    for sid,info in CHANNELS.items():
        s=stations[sid]
        if (s["display_name"]!=info["name"] or s["logo"] is not None
                or urlsplit(s["homepage"]).hostname not in {"maximum.ru","www.maximum.ru"}
                or not any(info["stream"] in x["url"] for x in s["streams"])):
            raise ValueError("Radio Maximum catalogue/stream identity mismatch: "+sid)

    html_images=[]
    page_verified=False
    page_error=None
    if network:
        try:
            raw,mime,final=_request(HOME,max_bytes=MAX_HTML,accept="text/html")
            if urlsplit(final).hostname not in {"maximum.ru","www.maximum.ru"} or mime not in {"text/html","application/xhtml+xml",""}:
                raise ValueError("Not broadcaster's original HTML")
            parser=PublisherImages()
            parser.feed(raw.decode("utf-8",errors="replace"))
            html_images=[(alt,urljoin(final,src)) for alt,src in parser.pairs]
            page_verified=True
        except (HTTPError,URLError,TimeoutError,ssl.SSLError,OSError,ValueError) as e:
            page_error=type(e).__name__

    records=[]
    for sid,info in CHANNELS.items():
        url=info["source"]
        p=urlsplit(url)
        if p.scheme!="https" or p.hostname!="maximum.ru" or not p.path.startswith("/b/d/") or not p.path.endswith(".webp"):
            raise ValueError("Unsafe/unexpected publisher image locator")
        page_matches=[candidate for alt,candidate in html_images if
                      alt==info["alt"].casefold() and norm_url(candidate)==norm_url(url)]
        row={"go_station_id":sid,"station_name":info["name"],
             "publisher_page":HOME,"publisher_image":url,
             "publisher_page_read":page_verified,
             "channel_image_html_identity_verified":len(page_matches)>0,
             "image_bytes_verified":False,"publication_allowed":False,
             "catalog_mutated":False}
        if network:
            try:
                data,mime,final=_request(url,max_bytes=MAX_IMAGE,
                                           accept="image/webp,image/png,image/jpeg")
                if urlsplit(final).hostname!="maximum.ru":
                    raise ValueError("Publisher image redirected outside maximum.ru")
                row.update(inspect_bytes(data,content_type=mime))
                row["image_bytes_verified"]=True
                row["final_url"]=final
                row["status"]=("OFFICIAL_CHANNEL_IMAGE_SHA_AND_HTML_MATCH"
                               if page_matches else
                               "ORIGINAL_SHA_VERIFIED_HTML_MAPPING_NOT_CONFIRMED")
            except (HTTPError,URLError,TimeoutError,ssl.SSLError,OSError,ValueError) as e:
                row["status"]="PUBLISHER_IMAGE_UNAVAILABLE"
                row["image_error"]=type(e).__name__
        else:
            row["status"]="NO_NETWORK_READ_ONLY"
        records.append(row)
    verified=[r["sha256"] for r in records if r["image_bytes_verified"]]
    if len(verified)!=len(set(verified)):
        raise ValueError("Radio Maximum channel images share a generic SHA")
    return {"scope":"GO_V8_MAXIMUM_3_CHANNEL_ORIGINAL_SHA_READ_ONLY",
            "signed_v7_predecessor_preserved":True,
            "unsigned_v8_13_unchanged":True,"expected_stations":3,
            "publisher_page_read":page_verified,"publisher_page_error":page_error,
            "original_image_sha_verified":len(verified),
            "html_mapping_verified":sum(r["channel_image_html_identity_verified"] for r in records),
            "publication_allowed":False,"catalog_mutated":False,
            "records":records}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--network",action="store_true")
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    report=audit(network=args.network)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"result":report["scope"],
                      "publisher_html_verified":report["html_mapping_verified"],
                      "real_sha_verified":report["original_image_sha_verified"],
                      "out_of":3,"published":False},sort_keys=True))
if __name__=="__main__":
    main()
