#!/usr/bin/env python3
"""Read-only follow-up on four additional original official radio images.

True Black Metal, Szent Korona, 0 N Heavy Metal and Almost Hell Radio are
all sourced from the respective official live radio page.
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
BASE=ROOT/"radio-catalog-lab/full-staging/UNSIGNED-radio-v8-46-official-sha-logos-20261123.json"
SOURCES={
"go-station-000067":("True Black Metal Radio","http://trueblackmetalradio.com/#/home","trueblackmetalradio.com:666/radio",
    "https://trueblackmetalradio.com/","https://trueblackmetalradio.com/assets/images/tbmr.png","trueblackmetalradio.com"),
"go-station-000076":("Szent Korona Rádió","https://szentkoronaradio.com/","szkrcast.ddns.net/radio/8000",
    "https://szentkoronaradio.com/","https://szentkoronaradio.com/wp-content/uploads/2026/04/cropped-szkrlogo.png","szentkoronaradio.com"),
"go-station-000277":("0 N - Heavy Metal on Radio","http://www.0nradio.com/","0n-heavymetal.radionetz.de",
    "https://www.0nradio.com/","https://www.0nradio.com/images/stationen/thumb1/0-n-heavy-metal-81-1.jpg","www.0nradio.com"),
"go-station-000237":("Almost Hell Radio","https://almosthellradio.duckdns.org/public/almost_hell_radio","almosthellradio.duckdns.org/listen/almost_hell_radio",
    "https://almosthellradio.duckdns.org/public/almost_hell_radio","https://almosthellradio.duckdns.org/api/station/almost_hell_radio/art/b96e94af3165befc0f2180a2-1788904855.jpg","almosthellradio.duckdns.org"),
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
            or sum(s["logo"] is None for s in active)!=50):
        raise ValueError("Expected 46-logo v8 input")
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
    return {"scope":"GO_V8_FOUR_FURTHER_METAL_STATION_ORIGINALS_READ_ONLY",
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
