#!/usr/bin/env python3
"""Read-only secure official SVG radio mark -> immutable PNG SHA proof.

SVG sources must be direct official owner assets (not third party art),
referenced by official publisher page and sanitized against external URL,
script, foreignObject, and other dangerous SVG tags before CairoSVG render.
No publication or signing.
"""
from __future__ import annotations
import argparse,hashlib,json,ssl,io
from pathlib import Path
from urllib.parse import urlsplit,urljoin,unquote
from urllib.error import HTTPError,URLError
from html.parser import HTMLParser
from defusedxml import ElementTree as DET
import cairosvg
from audit_open_radio_artwork_inventory import _request,inspect_bytes,MAX_HTML,MAX_IMAGE

ROOT=Path(__file__).resolve().parents[2]
CANDIDATE=ROOT/"radio-catalog-lab/full-staging/UNSIGNED-radio-v8-62-official-sha-logos-20261123.json"
SOURCES={
"go-station-000038":("РокРадіо Metal","https://rockradioua.online/","rockradioua.online:8433/metal_256",
    "https://rockradioua.online/",
    "https://rockradioua.online/wp-content/themes/rock-radio/assets/images/logo-regular-rockradio.svg",
    "rockradioua.online"),
"go-station-000157":("Tangra Mega Rock","http://www.radiotangra.com/","stream-bg-01.radiotangra.com:8000/Tangra-high",
    "https://radiotangra.com/",
    "https://radiotangra.com/wp-content/uploads/2023/02/Vector-Smart-Object.svg",
    "radiotangra.com"),
}
class Parser(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.images=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag in ("img","source"):
            for key in ("src","data-src"):
                if a.get(key):self.images.append(a[key])
        if tag=="meta" and (a.get("property")or"").lower() in ("og:image","og:image:url"):
            if a.get("content"):self.images.append(a["content"])
def identity(u):
    p=urlsplit(u);return p.hostname,unquote(p.path)
def safe_svg_to_png(data:bytes):
    if len(data)<128 or len(data)>850000 or b"\x00" in data:raise ValueError("SVG file size/content rejected")
    lower=data.lower()
    # Do not execute scripts, embed HTML, or allow external files/network references.
    for word in (b"<!doctype",b"<!entity",b"<script",b"<foreignobject",b"javascript:",b"@import",b"<image",b"<use ",b"file://",b"http://",b"https://"):
        if word in lower:raise ValueError("Unsafe SVG markup reference")
    root=DET.fromstring(data)
    if not root.tag.endswith("svg"):raise ValueError("Not SVG root")
    # Disallow remote refs even if obfuscated in XML attributes.
    for el in root.iter():
        for k,v in el.attrib.items():
            if k.endswith("href") and not v.startswith("#"):
                raise ValueError("External SVG href")
            if "url(" in v.lower() and "url(#" not in v.lower():
                raise ValueError("External SVG CSS URL")
    rendered=cairosvg.svg2png(bytestring=data,output_width=512)
    if len(rendered)>MAX_IMAGE:raise ValueError("Rendered PNG too large")
    inspect_bytes(rendered,content_type="image/png")
    return rendered
def audit(network=False):
    doc=json.loads(CANDIDATE.read_bytes())
    active=[x for x in doc["stations"] if x["status"]["state"]=="active"]
    if len(active)!=285 or len(doc["stations"])!=296 or len(doc["tombstones"])!=24 or doc["release_sequence"]!=8 or sum(x["logo"] is None for x in active)!=34:
        raise ValueError("Expected unsigned 62-logo source")
    idx={s["go_station_id"]:s for s in active}
    rows=[]
    for sid,(name,home,stream,page,url,host) in SOURCES.items():
        st=idx[sid]
        if st["display_name"]!=name or st["homepage"]!=home or st["logo"] is not None or not any(stream in x["url"] for x in st["streams"]):
            raise ValueError("Source station identity mismatch "+sid)
        if urlsplit(url).hostname!=host or urlsplit(url).scheme!="https":raise ValueError("Unapproved original SVG host")
        item={"id":sid,"station_name":name,"publisher_page":page,"original_svg_url":url,
              "source_page_match":False,"verified_svg":False,"verified_png":False,
              "signed":False,"published":False}
        if network:
            try:
                raw,mime,final=_request(page,max_bytes=MAX_HTML,accept="text/html")
                if mime not in ("text/html","application/xhtml+xml",""):raise ValueError("Page not HTML")
                parser=Parser();parser.feed(raw.decode("utf-8",errors="replace"))
                item["source_page_match"]=any(identity(urljoin(final,u))==identity(url) for u in parser.images)
                item["page_fetched"]=True
            except (HTTPError,URLError,OSError,ssl.SSLError,TimeoutError,ValueError) as exc:
                item["page_fetched"]=False;item["page_error"]=type(exc).__name__+":"+str(exc)[:110]
            try:
                raw,mime,final=_request(url,max_bytes=MAX_IMAGE,accept="image/svg+xml")
                if mime not in ("image/svg+xml","application/octet-stream","text/xml","application/xml","") or urlsplit(final).hostname!=host:
                    raise ValueError("Owner SVG MIME/host changed")
                png=safe_svg_to_png(raw);meta=inspect_bytes(png,content_type="image/png")
                item.update(original_svg_sha256=hashlib.sha256(raw).hexdigest(),
                            original_svg_byte_size=len(raw),original_svg_mime_type=mime,
                            rendered_png=meta)
                item["verified_svg"]=True;item["verified_png"]=True;item["status"]="OWNER_ORIGINAL_SVG_SAFE_RASTER_PNG_SHA_VERIFIED"
            except (HTTPError,URLError,OSError,ssl.SSLError,TimeoutError,ValueError) as exc:
                item["status"]="ORIGINAL_SVG_UNVERIFIED"
                item["file_error"]=type(exc).__name__+":"+str(exc)[:110]
        else:item["status"]="OFFLINE_RADIO_IDENTITY_OK"
        rows.append(item)
    return {"scope":"GO_V8_TWO_OFFICIAL_SVG_RADIO_LOGOS_SAFE_PNG_READ_ONLY",
            "targets":2,"original_svg_verified":sum(x["verified_svg"] for x in rows),
            "derived_png_verified":sum(x["verified_png"] for x in rows),
            "owner_page_matches":sum(x["source_page_match"] for x in rows),
            "signed":False,"published":False,"rows":rows}
def main():
    p=argparse.ArgumentParser();p.add_argument("--network",action="store_true");p.add_argument("--output",type=Path,required=True)
    a=p.parse_args();r=audit(a.network)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(r,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:r[k] for k in ("scope","targets","original_svg_verified","derived_png_verified","owner_page_matches")},sort_keys=True))
    for x in r["rows"]:print(x["id"],x["station_name"],x["status"],x.get("rendered_png",{}).get("sha256","NO_SHA"),x["source_page_match"],x.get("file_error",""))
if __name__=="__main__":main()
