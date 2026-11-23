#!/usr/bin/env python3
"""Read-only broadcaster-owned logo proof for BeGoodRadio and BloodStream Radio.

BeGoodRadio PNG is explicitly a network-wide brand, not 80s Metal-specific.
BloodStream SVG is owner favicon; validate and convert to a deterministic PNG.
Both rely on exact broadcaster name/homepage/stream proof against unsigned v8;
no changes to signed v7, primary pointer, or production.
"""
from __future__ import annotations
import argparse,hashlib,json,ssl
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError,URLError
from urllib.parse import urlsplit,urljoin,unquote
from audit_open_radio_artwork_inventory import _request,inspect_bytes,MAX_IMAGE,MAX_HTML
from audit_v8_two_official_svg_logos import safe_svg_to_png

ROOT=Path(__file__).resolve().parents[2]
BEFORE=ROOT/"radio-catalog-lab/full-staging/UNSIGNED-radio-v8-64-official-sha-logos-20261123.json"
SOURCES={
"go-station-000142":(
    "Begoodradio.com 80s metal","http://begoodradio.com/","bigrradio.cdnstream1.com/5212_128",
    "https://begoodradio.com/","https://begoodradio.com/logo.png",
    "begoodradio.com","image/png","publisher_brand_not_channel_specific"),
"go-station-000092":(
    "Radio Bloodstream","https://www.radiobloodstream.com/en/","uk1.internet-radio.com/proxy/bloodstream",
    "https://radiobloodstream.com/","https://radiobloodstream.com/favicon.svg",
    "radiobloodstream.com","image/svg+xml","publisher_icon_not_wordmark"),
}
class Images(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.images=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=="img":
            for k in ("src","data-src","data-lazy-src"):
                if a.get(k):self.images.append(a[k])
        if tag=="link" and "icon" in (a.get("rel") or "").lower() and a.get("href"):
            self.images.append(a["href"])
        if tag=="meta" and (a.get("property") or "").lower() in ("og:image","og:image:url"):
            if a.get("content"):self.images.append(a["content"])
def canonical(x):
    a=urlsplit(x);return a.hostname,unquote(a.path)
def audit(network=False):
    candidate=json.loads(BEFORE.read_bytes())
    active=[s for s in candidate["stations"] if s["status"]["state"]=="active"]
    if candidate["release_sequence"]!=8 or len(active)!=285 or len(candidate["stations"])!=296 or len(candidate["tombstones"])!=24 or sum(s["logo"] is None for s in active)!=32:
        raise ValueError("Expected 64-asset unsigned v8")
    byid={s["go_station_id"]:s for s in active}
    result=[]
    for sid,(name,home,stream,page,url,host,fmt,kind) in SOURCES.items():
        s=byid[sid]
        if s["display_name"]!=name or s["homepage"]!=home or s["logo"] is not None or not any(stream in t["url"] for t in s["streams"]):
            raise ValueError("Wrong station/stream identity for "+sid)
        if urlsplit(url).scheme!="https" or urlsplit(url).hostname!=host:raise ValueError("Wrong owner image host")
        row={"id":sid,"station":name,"publisher_page":page,"image_url":url,"asset_kind":kind,
            "owner_page_match":False,"source_verified":False,"png_verified":False,
            "published":False,"signed":False}
        if network:
            try:
                b,m,f=_request(page,max_bytes=MAX_HTML,accept="text/html")
                if m not in ("text/html","application/xhtml+xml",""):raise ValueError("Publisher page not HTML")
                p=Images();p.feed(b.decode("utf-8",errors="replace"))
                row["owner_page_match"]=any(canonical(urljoin(f,v))==canonical(url) for v in p.images)
                row["owner_page_verified"]=True
            except (HTTPError,URLError,OSError,ssl.SSLError,TimeoutError,ValueError) as e:
                row["owner_page_verified"]=False;row["owner_page_error"]=type(e).__name__+":"+str(e)[:100]
            try:
                content,mime,final=_request(url,max_bytes=MAX_IMAGE,accept=fmt)
                if urlsplit(final).hostname!=host:raise ValueError("Original asset redirected elsewhere")
                if fmt=="image/svg+xml":
                    if mime not in ("image/svg+xml","text/xml","application/xml","application/octet-stream",""):raise ValueError("Not original SVG")
                    png=safe_svg_to_png(content)
                else:
                    if mime not in ("image/png","application/octet-stream",""):raise ValueError("Not original PNG")
                    png=content
                row["original_sha256"]=hashlib.sha256(content).hexdigest()
                row["original_bytes"]=len(content)
                row["png_metadata"]=inspect_bytes(png,content_type="image/png")
                row["source_verified"]=True;row["png_verified"]=True
                row["status"]="PUBLISHER_OWNED_BRAND_ORIGINAL_SHA_VERIFIED"
            except (HTTPError,URLError,OSError,ssl.SSLError,TimeoutError,ValueError) as e:
                row["status"]="ORIGINAL_OWNER_IMAGE_UNVERIFIED"
                row["image_error"]=type(e).__name__+":"+str(e)[:125]
        else:row["status"]="OFFLINE_IDENTITY_VERIFIED"
        result.append(row)
    return {"scope":"GO_V8_TWO_OWNER_BRAND_BEG0OD_BLOODSTREAM_READ_ONLY",
        "targets":2,"shas_verified":sum(x["png_verified"] for x in result),
        "owner_page_matches":sum(x["owner_page_match"] for x in result),
        "signed":False,"published":False,"rows":result}
def main():
    p=argparse.ArgumentParser();p.add_argument("--network",action="store_true");p.add_argument("--output",type=Path,required=True)
    a=p.parse_args();r=audit(a.network);a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(r,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:r[k] for k in ("scope","targets","shas_verified","owner_page_matches","published")},sort_keys=True))
    for x in r["rows"]:
        print(x["id"],x["station"],x["status"],x.get("png_metadata",{}).get("sha256","NO_SHA"),x["owner_page_match"],x.get("image_error",""))
if __name__=="__main__":main()
