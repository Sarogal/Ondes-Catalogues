#!/usr/bin/env python3
"""Read-only five publisher logo original-image candidates, no catalog mutation.

ARfm, Alternativa by Mix, Pure Rock KNAC.COM, NTS The Pit, Rock FM 105.5
owner-hosted logos only; independently check original image SHA bytes.
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
BASE=ROOT/"radio-catalog-lab/full-staging/UNSIGNED-radio-v8-56-official-sha-logos-20261123.json"
SOURCES={
"go-station-000017":("ARfm","http://arfm.co.uk/","108.163.245.230:9016",
    "https://arfm.co.uk/","https://arfm.co.uk/wp-content/uploads/2021/10/ARFM-LOGO-2024-Final-Black.png","arfm.co.uk"),
"go-station-000032":("Alternativa by MIX (iHeart Radio) - Online - ACIR Online / iHeart Radio - Ciudad de México",
    "https://www.iheart.com/live/alternativa-by-mix-8053/","ACIR12_s01AAC.aac",
    "https://www.iheart.com/live/alternativa-by-mix-8053/",
    "https://i.iheart.com/v3/re/new_assets/5ceb5aa23a3ce4f7d3a1371c?ops=fit(960%2C960)%2Cresize(0%2C390)","i.iheart.com"),
"go-station-000216":("Pure Rock KNAC.COM","https://knac.com/","stream.rcast.net/71987",
    "https://knac.com/",
    "https://knac.com/wp-content/uploads/2025/10/knaclogo_transparent_8-bit_658x260.png","knac.com"),
"go-station-000042":("The Pit | NTS","https://www.nts.live/infinite-mixtapes/the-pit","stream-mixtape-geo.ntslive.net/mixtape34",
    "https://www.nts.live/infinite-mixtapes/the-pit",
    "https://media3.ntslive.co.uk/resize/100x100/9c9efb53-ce34-4a5e-997b-f8251be464a1_1668038400.jpeg","media3.ntslive.co.uk"),
"go-station-000107":("Rock FM 105.5","https://rockfm.com.ni/","securestream.us/radio/8050",
    "https://rockfm.com.ni/",
    "https://rockfm.com.ni/wp-content/uploads/2020/06/cropped-una-logo-rock-1-180x180.png","rockfm.com.ni"),
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
            or sum(s["logo"] is None for s in active)!=40):
        raise ValueError("Expected 56-logo unsigned v8 input")
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
    return {"scope":"GO_V8_FIVE_OFFICIAL_RADIO_LOGO_IMAGES_READ_ONLY",
            "count":5,"shas_verified":len(used),
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
