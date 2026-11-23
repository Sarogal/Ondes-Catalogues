#!/usr/bin/env python3
"""Read-only four original publisher logos for Rocker, idobi Howl, NuMetal and SFTD.

Only owner-published station images or their managed station hosting service.
No production or signed radio pointer edits.
Existing source URLs and streams checked before any image access.
"""
from __future__ import annotations
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit,urljoin,unquote
from urllib.error import URLError,HTTPError
import argparse,json,ssl
from audit_open_radio_artwork_inventory import _request,inspect_bytes,MAX_IMAGE,MAX_HTML
ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/"radio-catalog-lab/full-staging/UNSIGNED-radio-v8-57-official-sha-logos-20261123.json"
SOURCES={
"go-station-000062":("Rocker Rádió","http://rockerradio.online/","rockerradio.online/live.mp3",
    "https://rockerradio.online/",
    "https://rockerradio.online/wp-content/uploads/2020/04/rockerradio-logo.png","rockerradio.online"),
"go-station-000155":("idobi Howl","http://idobi.com/","idobihowl.idobi.com",
    "https://idobi.com/","https://idobi.com/wp-content/themes/idobi-2022/assets/img/idobiHowl_2022logo_Dark.png","idobi.com"),
"go-station-000240":("NuMetal 1.0 -JubsTones","https://stream.zeno.fm/zg3ps1ckoeiuv","stream.zeno.fm/zg3ps1ckoeiuv",
    "https://zeno.fm/radio/numetal-1-0-jubstones/",
    "https://images.zeno.fm/ZaR6c9kJYMJqqg62lrFe4r2EkjiqNZ8LtSaRA0otsao/rs:fill:304:304/q:75/g:ce:0:0/aHR0cHM6Ly9wcm94eS56ZW5vLmZtL2NvbnRlbnQvc3RhdGlvbnMvMjZmOTA1YmEtMjEzYi00MzJmLThjN2EtMzRjNjAwODZjMDgyL2ltYWdlLz91PTE3MzE3NzE1NTUwMDA","images.zeno.fm"),
"go-station-000245":("SFTD RADIO","https://songs4deaf.blogspot.com/","hyades.shoutca.st:8270",
    "https://songs4deaf.blogspot.com/",
    "https://blogger.googleusercontent.com/img/b/R29vZ2xl/AVvXsEiG3U8xzH7WkkbamBdqveLLeHFgClJqQNjrZdeFMddW1HTDsfSTRm2cqA1oqjhqvEHz_G_dQU4JF-4xbRE2OQ1Gd176YKmd9eaMtbNxjN1Lg7TKaqU4Nr7K7xw19yuekg3wOm-EgXcIr_sX1Zr6GrYF91wCclg6NYTG0LyX8hr69rLz4IUm9jSR76ja4qLS/w640-h110/3540469131_logo.jpg",
    "blogger.googleusercontent.com"),
}
class Img(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.assets=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=="img":
            for k in ("src","data-src","data-lazy-src"):
                if a.get(k):self.assets.append(a[k])
        if tag=="meta" and (a.get("property") or "").lower() in ("og:image","og:image:url"):
            if a.get("content"):self.assets.append(a["content"])
def canon(s):
    p=urlsplit(s);return p.hostname,unquote(p.path)
def audit(network=False):
    cat=json.loads(BASE.read_bytes())
    active=[s for s in cat["stations"] if s["status"]["state"]=="active"]
    if (cat["release_sequence"]!=8 or len(cat["stations"])!=296
            or len(cat["tombstones"])!=24 or len(active)!=285
            or sum(s["logo"] is None for s in active)!=39):
        raise ValueError("Expected v8 unsigned 57-logo input")
    stations={s["go_station_id"]:s for s in active}
    output=[]
    for sid,(name,home,stream,page,image,host) in SOURCES.items():
        s=stations[sid]
        if s["logo"] is not None or s["display_name"]!=name or s["homepage"]!=home or not any(stream in u["url"] for u in s["streams"]):
            raise ValueError("Wrong station metadata or stream "+sid)
        if urlsplit(image).scheme!="https" or urlsplit(image).hostname!=host:
            raise ValueError("Unexpected image source origin")
        row={"id":sid,"name":name,"publisher_page":page,"publisher_image":image,
             "page_image_match":False,"image_sha_verified":False,
             "signed":False,"published":False}
        if network:
            try:
                html,mime,final=_request(page,max_bytes=MAX_HTML,accept="text/html")
                if mime not in ("text/html","application/xhtml+xml",""):raise ValueError("Unexpected broadcaster page")
                parser=Img();parser.feed(html.decode("utf-8",errors="replace"))
                row["page_verified"]=True
                row["page_image_match"]=any(canon(urljoin(final,u))==canon(image) for u in parser.assets)
            except (HTTPError,URLError,OSError,ssl.SSLError,TimeoutError,ValueError) as exc:
                row["page_verified"]=False;row["page_error"]=type(exc).__name__
            try:
                data,mime,final=_request(image,max_bytes=MAX_IMAGE,accept="image/png,image/jpeg,image/webp")
                if urlsplit(final).hostname!=host:raise ValueError("Image redirect changed the host")
                row.update(inspect_bytes(data,content_type=mime))
                row["image_sha_verified"]=True
                row["status"]="FIRSTPARTY_ORIGINAL_SHA_VALIDATED"
            except (HTTPError,URLError,OSError,ssl.SSLError,TimeoutError,ValueError) as exc:
                row["status"]="ORIGINAL_IMAGE_NOT_VERIFIED";row["image_error"]=type(exc).__name__
        else:row["status"]="OFFLINE_STATION_VERIFIED"
        output.append(row)
    used=[r["sha256"] for r in output if r["image_sha_verified"]]
    assert len(used)==len(set(used))
    return {"scope":"GO_V8_FOUR_ADDITIONAL_INDEPENDENT_RADIO_ORIGINALS_AUDIT",
            "count":4,"shas_verified":len(used),
            "html_matches":sum(r["page_image_match"] for r in output),
            "signed":False,"published":False,"records":output}
def main():
    p=argparse.ArgumentParser();p.add_argument("--network",action="store_true")
    p.add_argument("--output",type=Path,required=True);opts=p.parse_args()
    r=audit(opts.network)
    opts.output.parent.mkdir(parents=True,exist_ok=True)
    opts.output.write_text(json.dumps(r,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({x:r[x] for x in ("scope","count","shas_verified","html_matches","published")},sort_keys=True))
    for x in r["records"]:
        print(x["id"],x["name"],x["status"],x.get("sha256","NO_SHA"),x["page_image_match"])
if __name__=="__main__":main()
