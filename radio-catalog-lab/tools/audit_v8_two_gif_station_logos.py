#!/usr/bin/env python3
"""Read-only broadcaster GIF->PNG original art audit: HardRadio & Drachenblut.

Original GIF must be HTTPS on broadcaster first-party domain and appear on
its original owner webpage. GIF frame is decoded to RGBA PNG on the Actions
runner using Pillow; both original GIF and derived PNG SHA256 are reported.
Zero live catalog / signed pointer writes.
"""
from __future__ import annotations
from pathlib import Path
from urllib.parse import urlsplit,urljoin,unquote
from html.parser import HTMLParser
from urllib.error import URLError,HTTPError
from io import BytesIO
import argparse,hashlib,json,ssl
from PIL import Image
from audit_open_radio_artwork_inventory import _request,MAX_IMAGE,MAX_HTML,MIN_DIM,MAX_DIM

ROOT=Path(__file__).resolve().parents[2]
CANDIDATE=ROOT/"radio-catalog-lab/full-staging/UNSIGNED-radio-v8-60-official-sha-logos-20261123.json"
SOURCES={
"go-station-000146":("HardRadio","http://www.hardradio.com/","144.217.29.205",
    "https://www.hardradio.com/",
    "https://www.hardradio.com/logos/hardradio_chrome_375.gif",
    "www.hardradio.com"),
"go-station-000071":("Radio-Drachenblut","https://radio-drachenblut.ch/","radio-drachenblut.ch:8443",
    "https://radio-drachenblut.ch/",
    "https://radio-drachenblut.ch/top11.gif",
    "radio-drachenblut.ch"),
}
class PageAssets(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.links=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=="img":
            for k in ("src","data-src","data-lazy-src"):
                if a.get(k):self.links.append(a[k])
        if tag=="meta" and ((a.get("property")or"").lower() in ("og:image","og:image:url")):
            if a.get("content"):self.links.append(a["content"])
def ident(u):
    p=urlsplit(u)
    return p.hostname,unquote(p.path)
def convert(source:bytes):
    with Image.open(BytesIO(source)) as i:
        if i.format!="GIF" or i.width<MIN_DIM or i.height<MIN_DIM or i.width>MAX_DIM or i.height>MAX_DIM or i.width*i.height>12_000_000:
            raise ValueError("Not a valid broadcaster logo GIF")
        i.seek(0)
        png=BytesIO()
        i.convert("RGBA").save(png,format="PNG",optimize=False)
        result=png.getvalue()
        with Image.open(BytesIO(result)) as check:
            if check.format!="PNG" or check.size!=i.size:raise ValueError("PNG decode mismatch")
            check.verify()
        return result,i.width,i.height
def audit(network=False):
    c=json.loads(CANDIDATE.read_bytes());active=[s for s in c["stations"] if s["status"]["state"]=="active"]
    if c["release_sequence"]!=8 or len(c["stations"])!=296 or len(active)!=285 or len(c["tombstones"])!=24 or sum(s["logo"] is None for s in active)!=36:
        raise ValueError("Expected audited unsigned 60 logo v8 predecessor")
    index={s["go_station_id"]:s for s in active}
    rows=[]
    for sid,(name,home,stream,page,url,host) in SOURCES.items():
        station=index[sid]
        if station["logo"] is not None or station["display_name"]!=name or station["homepage"]!=home or not any(stream in s["url"] for s in station["streams"]):
            raise ValueError("Source radio identity or original stream mismatch "+sid)
        if urlsplit(url).hostname!=host or urlsplit(url).scheme!="https":raise ValueError("Unsafe original logo origin")
        row={"go_station_id":sid,"name":name,"publisher_page":page,"original_gif_url":url,
             "page_match":False,"original_gif_sha_verified":False,"derived_png_sha_verified":False,
             "signed":False,"published":False}
        if network:
            try:
                html,mime,final=_request(page,max_bytes=MAX_HTML,accept="text/html")
                if mime not in ("text/html","application/xhtml+xml",""):raise ValueError("Not broadcaster HTML")
                parser=PageAssets();parser.feed(html.decode("utf-8",errors="replace"))
                row["page_match"]=any(ident(urljoin(final,link))==ident(url) for link in parser.links)
                row["page_verified"]=True
            except (ValueError,HTTPError,URLError,OSError,ssl.SSLError,TimeoutError) as exc:
                row["page_verified"]=False;row["page_error"]=type(exc).__name__
            try:
                body,mime,final=_request(url,max_bytes=MAX_IMAGE,accept="image/gif")
                if urlsplit(final).hostname!=host or mime not in ("image/gif","application/octet-stream",""):
                    raise ValueError("Original host or GIF MIME invalid")
                png,w,h=convert(body)
                row.update(original_gif_sha256=hashlib.sha256(body).hexdigest(),
                           original_gif_byte_size=len(body),
                           derived_png_sha256=hashlib.sha256(png).hexdigest(),
                           derived_png_byte_size=len(png),
                           width=w,height=h,derived_png_mime_type="image/png")
                row["original_gif_sha_verified"]=True
                row["derived_png_sha_verified"]=True
                row["status"]="ORIGINAL_BROADCASTER_GIF_TO_CANONICAL_PNG_SHA_PASS"
            except (ValueError,HTTPError,URLError,OSError,ssl.SSLError,TimeoutError) as exc:
                row["status"]="GIF_OR_PNG_UNVERIFIED"
                row["file_error"]=type(exc).__name__+":"+str(exc)[:130]
        else:row["status"]="OFFLINE_RADIO_IDENTITY_PASS"
        rows.append(row)
    return {"scope":"GO_V8_HARDRADIO_DRACHENBLUT_GIF_PNG_READ_ONLY",
            "targets":2,"original_gifs_verified":sum(s["original_gif_sha_verified"] for s in rows),
            "derived_pngs_verified":sum(s["derived_png_sha_verified"] for s in rows),
            "publisher_page_matches":sum(s["page_match"] for s in rows),
            "published":False,"signed":False,"rows":rows}
def main():
    p=argparse.ArgumentParser();p.add_argument("--network",action="store_true");p.add_argument("--output",type=Path,required=True)
    args=p.parse_args();out=audit(args.network)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:out[k] for k in ("scope","targets","original_gifs_verified","derived_pngs_verified","publisher_page_matches")},sort_keys=True))
    for r in out["rows"]:print(r["go_station_id"],r["name"],r["status"],r.get("derived_png_sha256","NO_SHA"),r["page_match"],r.get("file_error",""))
if __name__=="__main__":main()
