#!/usr/bin/env python3
"""Read-only v8 audit of 7 original channel logos from broadcaster pages."""
from __future__ import annotations
import argparse,json,ssl
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit,urljoin,unquote
from urllib.error import HTTPError,URLError
from audit_open_radio_artwork_inventory import _request,inspect_bytes,MAX_HTML,MAX_IMAGE

ROOT=Path(__file__).resolve().parents[2]
DRAFT=ROOT/"radio-catalog-lab/full-staging/UNSIGNED-radio-v8-metalon-3-independent-3-firstparty-7-maximum-3-broadcaster-7-indep6-20261123.json"
# (Exact signed station name, original catalogue homepage, stream token,
# publisher channel page, first-party publisher-channel image, verified image host)
SOURCES={
"go-station-000168":("1.FM - High Voltage Radio","http://www.1.fm/","highvoltage_mobile_mp3",
 "https://www.1.fm/station/highvoltage",
 "https://www.1.fm/covers/5474d5e2-640.webp","www.1.fm"),
"go-station-000102":("ISKC Extreme Metal","https://iskcrocks.com/","/ExtremeMetal",
 "https://iskcrocks.com/?attachment_id=14831",
 "https://iskcrocks.com/wp-content/uploads/2025/03/Extreme-Metal.jpg","iskcrocks.com"),
"go-station-000294":("RPR1. Heavy Metal","https://www.rpr1.de/","stream.rpr1.de/metal/",
 "https://www.rpr1.de/webradio/heavy-metal",
 "https://image.atsw.de/atsw/production/2025-10/1200x1200pxl_metal.jpg?width=360&height=360","image.atsw.de"),
"go-station-000273":("Virgin Radio Metal","https://www.virginradio.fr/","virgin-radio-metal.mp3",
 "https://virginradio.fr/radio/webradio/9/virgin-radio-metal",
 "https://virginradio.fr/media/radio/thumb/300x300_67d1cbb8d7753-fr-metal.png","virginradio.fr"),
"go-station-000150":("RTBF Classic 21 - Metal","http://www.rtbf.be/radio/liveradio/webradio-classic21-metal","/wr-c21-metal-128.mp3",
 "https://www.rtbf.be/radio/liveradio/classic21_metal",
 "https://static-oaos.rtbf.be/assets/png/logotype/dark/classic21-Metal.png?r=20251208","static-oaos.rtbf.be"),
"go-station-000298":("Rock Radio Hard & Heavy SLO","https://www.rockradio.si/","stream.nextmedia.si/proxy/rocks_2",
 "https://www.rockradio.si/live/rock-radio-hard-and-heavy",
 "https://www.datocms-assets.com/49761/1744368504-11.png?auto=format&fit=max&w=1200","www.datocms-assets.com"),
"go-station-000042":("The Pit | NTS","https://www.nts.live/infinite-mixtapes/the-pit","mixtape34",
 "https://www.nts.live/infinite-mixtapes/the-pit",
 "https://media2.ntslive.co.uk/resize/1600x1600/9c9efb53-ce34-4a5e-997b-f8251be464a1_1668038400.jpeg","media2.ntslive.co.uk"),
}
class ImgParser(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.images=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag in ("img","source"):
            for k in ("src","data-src"):
                if a.get(k):self.images.append(a[k])
        if tag=="meta" and ((a.get("property") or "").lower() in ("og:image","og:image:url") or (a.get("name") or "").lower() in ("twitter:image","twitter:image:src")):
            if a.get("content"):self.images.append(a["content"])
def normalize(v):
    p=urlsplit(v);return p.hostname,unquote(p.path)
def audit(network=False):
    doc=json.loads(DRAFT.read_bytes())
    active=[x for x in doc["stations"] if x["status"]["state"]=="active"]
    if (doc["release_sequence"]!=8 or len(doc["stations"])!=296 or len(doc["tombstones"])!=24 or len(active)!=285 or sum(x["logo"] is None for x in active)!=67):
        raise ValueError("Expected unsigned v8 with 29 original logos")
    stations={x["go_station_id"]:x for x in active}
    rows=[]
    for sid,(name,home,stream,page,image,host) in SOURCES.items():
        s=stations[sid]
        if (s["display_name"]!=name or s["homepage"]!=home or s["logo"] is not None or not any(stream in x["url"] for x in s["streams"])):
            raise ValueError("Invalid station identity or stream "+sid)
        if urlsplit(image).scheme!="https" or urlsplit(image).hostname!=host:
            raise ValueError("Unsafe/unreviewed publisher image")
        row={"go_station_id":sid,"station_name":name,"publisher_page":page,
             "publisher_image":image,"image_source_host":host,
             "html_image_match":False,"image_sha_verified":False,
             "published":False,"catalog_changed":False}
        if network:
            try:
                data,mime,final=_request(page,max_bytes=MAX_HTML,accept="text/html")
                if mime not in ("text/html","application/xhtml+xml",""):
                    raise ValueError("Publisher page not HTML")
                parser=ImgParser();parser.feed(data.decode("utf-8",errors="replace"))
                row["publisher_html_verified"]=True
                row["html_image_match"]=any(normalize(urljoin(final,u))==normalize(image) for u in parser.images)
            except (HTTPError,URLError,TimeoutError,ssl.SSLError,OSError,ValueError) as e:
                row["page_error"]=type(e).__name__
            try:
                raw,mime,final=_request(image,max_bytes=MAX_IMAGE,accept="image/jpeg,image/png,image/webp")
                if urlsplit(final).hostname!=host:raise ValueError("Publisher image redirects outside verified host")
                row.update(inspect_bytes(raw,content_type=mime))
                row["image_sha_verified"]=True
                row["status"]="ORIGINAL_BROADCASTER_CHANNEL_IMAGE_SHA_VERIFIED"
            except (HTTPError,URLError,TimeoutError,ssl.SSLError,OSError,ValueError) as e:
                row["status"]="IMAGE_UNVERIFIED"
                row["image_error"]=type(e).__name__
        else:row["status"]="OFFLINE_STATION_ID_VERIFIED"
        rows.append(row)
    shas=[x["sha256"] for x in rows if x["image_sha_verified"]]
    if len(set(shas))!=len(shas):raise ValueError("Generic/doubled station image")
    return {"scope":"GO_V8_7_EXACT_CHANNEL_ORIGINAL_IMAGE_AUDIT","targets":7,
            "original_sha_verified":len(shas),
            "html_matches":sum(x["html_image_match"] for x in rows),
            "published":False,"catalog_changed":False,"rows":rows}
def main():
    p=argparse.ArgumentParser();p.add_argument("--network",action="store_true")
    p.add_argument("--output",type=Path,required=True);a=p.parse_args()
    r=audit(a.network);a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(r,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"result":r["scope"],"shas":r["original_sha_verified"],"html_matches":r["html_matches"],"published":False}))
    for x in r["rows"]:
        print(x["go_station_id"],x["station_name"],x["status"],x.get("sha256","NO_SHA"),x["html_image_match"])
if __name__=="__main__":main()
