#!/usr/bin/env python3
"""Read-only audit four specific official logos from published rock and metal station pages.

Original ROCK FM Classic Rock channel tile, BOLLOCKS brand and Blown brand;
Tattoo Metal logo URL historically indexed on its broadcaster site, may be stale.
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
BASE=ROOT/"radio-catalog-lab/full-staging/UNSIGNED-radio-v8-53-official-sha-logos-20261123.json"
SOURCES={
"go-station-000281":("ROCK FM Classic Rock","http://www.my-radios.com/es/radio/escuchar/30420/ROCK-FM-CLASSIC-ROCK","audiotainment-sw.streamabc.net/atsw-classicrock",
    "https://www.rockfm.de/webradio/classicrock","https://image.atsw.de/atsw/production/2025-08/rockfm_cover_classicrock.jpg?width=360&height=360","image.atsw.de"),
"go-station-000209":("BOLLOCKS Rock & Metal Radio","http://bollocksradio.com/","s44.myradiostream.com/6588",
    "https://www.bollocksradio.com/","https://image.jimcdn.com/app/cms/image/transf/dimension=198x10000:format=png/path/s924f1217ff669ab4/image/ia97fe5aee521791f/version/1752539932/bollocksradio.png","image.jimcdn.com"),
"go-station-000242":("Blown","http://crucialvelocity.ca/","ais-sa2.cdnstream1.com/1370_128",
    "https://crucialvelocity.ca/","https://crucialvelocity.ca/BlownLogo.jpg","crucialvelocity.ca"),
"go-station-000283":("Tattoo metal","https://usa14.fastcast4u.com/proxy/tattoometal?mp=/1","usa14.fastcast4u.com/proxy/tattoometal",
    "https://tattoometalradio.com/","https://tattoometalradio.com/wp-content/uploads/2020/06/Tattoo-Metal-Web-Logo.png","tattoometalradio.com"),
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
            or sum(s["logo"] is None for s in active)!=43):
        raise ValueError("Expected 53-logo v8 input")
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
    return {"scope":"GO_V8_FOUR_INDEPENDENT_MORE_RADIOS_ORIGINAL_AUDIT",
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
