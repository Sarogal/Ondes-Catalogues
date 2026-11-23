#!/usr/bin/env python3
"""Audit real first-party images for seven signed-v7 radio identities (READ ONLY).

Sources were inspected on publishers' official websites. This audit checks
that each target is still active/without logo, matches its expected homepage
and stream, and that the image bytes are a valid decoded image with SHA-256.
It records but never silently substitutes HTML image mappings, and NEVER
publishes an unsigned catalogue or changes the signed TEST pointer.
"""
from __future__ import annotations
import argparse
from html.parser import HTMLParser
import json
from pathlib import Path
from urllib.parse import unquote,urljoin,urlsplit
from urllib.error import HTTPError,URLError
import ssl
from audit_open_radio_artwork_inventory import _request,inspect_bytes,MAX_HTML,MAX_IMAGE

ROOT=Path(__file__).resolve().parents[2]
CANDIDATE=ROOT/"radio-catalog-lab/full-staging/UNSIGNED-radio-v8-metalon-3-independent-3-firstparty-7-maximum-3-20261123.json"
TARGETS={
 "go-station-000186":{
  "name":"Best of Rock FM - Metal",
  "homepage":"https://www.best-of-rock.fm/",
  "official_page":"https://www.best-of-rock.fm/",
  "image_url":"https://www.best-of-rock.fm/images/channels/metal.png",
  "stream_fragment":"bestofrockfm.stream.vip/metal/",
  "identity":"official Metal subchannel image",
 },
 "go-station-000014":{
  "name":"Metal Heart",
  "homepage":"https://www.metalheartradio.com/cs/",
  "official_page":"https://www.metalheartradio.com/cs/",
  "image_url":"https://www.metalheartradio.com/assets/images/logo-mhr.png",
  "stream_fragment":"metalheartradio64aac",
  "identity":"station brand image",
 },
 "go-station-000284":{
  "name":"Epic Rock Radio",
  "homepage":"https://www.epicrockradio.com/",
  "official_page":"https://www.epicrockradio.com/",
  "image_url":"https://www.epicrockradio.com/images/ERR_Banner_Transparent_2024.png",
  "stream_fragment":"securestreams6.autopo.st:2222/stream",
  "identity":"station branded banner",
 },
 "go-station-000286":{
  "name":"Prog Rock and Metal",
  "homepage":"https://www.progrockandmetal.net/",
  "official_page":"https://www.progrockandmetal.net/",
  "image_url":"https://www.progrockandmetal.net/PRM-BLACK.jpg",
  "stream_fragment":"centova.radioservers.biz/proxy/progrock/stream",
  "identity":"station branded image",
 },
 "go-station-000271":{
  "name":"Metal Radio",
  "homepage":"https://metalradio.at/",
  "official_page":"https://metal-radio.at/",
  "image_url":"https://metal-radio.at/metal_radio_100.png",
  "stream_fragment":"stream.radiotechnikum.at:80/METALRadio",
  "identity":"station brand image",
 },
 "go-station-000295":{
  "name":"TotalRock Radio",
  "homepage":"https://totalrock.com/",
  "official_page":"https://totalrock.com/",
  "image_url":"https://totalrock.com/wp-content/uploads/2018/04/New-TR-Icon-170x170.jpg",
  "stream_fragment":"s3.citrus3.com:8056/stream",
  "identity":"official square station logo image",
 },
 "go-station-000138":{
  "name":"Radio Diabolus",
  "homepage":"https://www.radio-diabolus.rocks/",
  "official_page":"https://radio-diabolus.dk/site/",
  "image_url":"https://radio-diabolus.dk/site/wp-content/uploads/elementor/thumbs/rdlogo-neueschriftart2-rqx3mof6kyz6l1ytuqsxll905ubzgio2puvsrzqex6.png",
  "stream_fragment":"dunkelhost.com:7800/stream",
  "identity":"station brand wordmark on broadcaster's redirected canonical site",
 }
}
class Images(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True);self.urls=[]
    def handle_starttag(self,tag,attrs):
        if tag not in ("img","source","meta"):return
        a=dict(attrs)
        for key in ("src","data-src","data-lazy-src","content"):
            if a.get(key):self.urls.append(a[key])
        if a.get("srcset"):
            self.urls.extend(t.strip().split()[0] for t in a["srcset"].split(",") if t.strip())

def normalized(url):
    p=urlsplit(url)
    return p.hostname,unquote(p.path),p.query

def audit(network=False):
    doc=json.loads(CANDIDATE.read_bytes())
    st={s["go_station_id"]:s for s in doc["stations"]}
    active=[s for s in doc["stations"] if s["status"]["state"]=="active"]
    if (doc["release_sequence"]!=8 or len(doc["stations"])!=296
        or len(doc["tombstones"])!=24 or len(active)!=285
        or sum(s["logo"] is None for s in active)!=80):
        raise ValueError("Unsigned 16-logo v8 candidate not available")
    records=[]
    for sid,info in TARGETS.items():
        station=st[sid]
        if (station["display_name"]!=info["name"] or station["logo"] is not None
                or station["status"]["state"]!="active"
                or station["homepage"]!=info["homepage"]
                or not any(info["stream_fragment"] in u["url"] for u in station["streams"])):
            raise ValueError("Wrong signed radio identity "+sid)
        expected_host=urlsplit(info["official_page"]).hostname
        image_host=urlsplit(info["image_url"]).hostname
        if image_host!=expected_host or urlsplit(info["image_url"]).scheme!="https":
            raise ValueError("Non first-party original source "+sid)
        row={"go_station_id":sid,"station_name":info["name"],
             "publisher_page":info["official_page"],
             "image_url":info["image_url"],
             "image_identity":info["identity"],
             "publisher_html_mapping_verified":False,
             "real_image_sha_verified":False,
             "publication_allowed":False,"catalog_changed":False}
        if network:
            try:
                page,mime,final=_request(info["official_page"],max_bytes=MAX_HTML,accept="text/html")
                if urlsplit(final).hostname!=expected_host or mime not in {"text/html","application/xhtml+xml",""}:
                    raise ValueError("Publisher page origin/format changed")
                images=Images();images.feed(page.decode("utf-8",errors="replace"))
                found=[urljoin(final,u) for u in images.urls]
                row["publisher_html_mapping_verified"]=any(
                    normalized(u)==normalized(info["image_url"]) for u in found)
                row["official_page_verified"]=True
            except (HTTPError,URLError,TimeoutError,ssl.SSLError,OSError,ValueError) as exc:
                row["official_page_verified"]=False
                row["page_error"]=type(exc).__name__
            try:
                blob,mime,final=_request(info["image_url"],max_bytes=MAX_IMAGE,
                                          accept="image/png,image/jpeg,image/webp")
                if urlsplit(final).hostname!=image_host:
                    raise ValueError("Official logo redirected away from publisher")
                decoded=inspect_bytes(blob,content_type=mime)
                row.update(decoded)
                row["real_image_sha_verified"]=True
                row["status"]="OFFICIAL_ORIGINAL_SHA_VALIDATED"
            except (HTTPError,URLError,TimeoutError,ssl.SSLError,OSError,ValueError) as exc:
                row["status"]="PUBLISHER_IMAGE_NOT_VERIFIED"
                row["image_error"]=type(exc).__name__
        else:row["status"]="NO_NETWORK"
        records.append(row)
    shas=[r["sha256"] for r in records if r["real_image_sha_verified"]]
    if len(shas)!=len(set(shas)):raise ValueError("Generic duplicated first-party image SHAs")
    return {"scope":"GO_V8_SEVEN_BROADCASTER_SOURCE_IMAGES_READ_ONLY",
            "targets":7,"sha_verified":len(shas),
            "html_mappings_verified":sum(x["publisher_html_mapping_verified"] for x in records),
            "catalog_changed":False,"publication_allowed":False,"records":records}
def main():
    p=argparse.ArgumentParser();p.add_argument("--network",action="store_true")
    p.add_argument("--output",type=Path,required=True);a=p.parse_args()
    r=audit(a.network);a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(r,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"result":r["scope"],"targets":7,"sha_verified":r["sha_verified"],
                      "html_verified":r["html_mappings_verified"],
                      "publication_allowed":False},sort_keys=True))
    for row in r["records"]:
        print(row["go_station_id"],row["station_name"],row["status"],
              row.get("sha256","NO_SHA"),row["publisher_html_mapping_verified"])
if __name__=="__main__": main()
