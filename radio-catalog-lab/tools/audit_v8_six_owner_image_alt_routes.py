#!/usr/bin/env python3
"""Read-only six alternative broadcaster logos, browser-style user-agent only after source HTTPS/DNS validation.

Re-probe six previously inaccessible first-party images with alternative 
provider-hosted URLs; preserve strict HTTPS, DNS and image SHA gates.
Existing source URLs and streams checked before any image access.
"""
from __future__ import annotations
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit,urljoin,unquote
from urllib.error import URLError,HTTPError
import argparse,json,ssl
import audit_open_radio_artwork_inventory as image_safe
from audit_open_radio_artwork_inventory import _request,inspect_bytes,MAX_IMAGE,MAX_HTML
image_safe.UA = "Mozilla/5.0 (compatible; GrossesOndesArtworkAudit/1.0; +https://grosses-ondes.fr)"
ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/"radio-catalog-lab/full-staging/UNSIGNED-radio-v8-60-official-sha-logos-20261123.json"
SOURCES={
"go-station-000017":("ARfm","http://arfm.co.uk/","108.163.245.230:9016",
    "https://arfm.co.uk/","https://arfm.co.uk/wp-content/uploads/2021/10/ARFM-White-Logo-2024-2-100x100.png","arfm.co.uk"),
"go-station-000216":("Pure Rock KNAC.COM","https://knac.com/","stream.rcast.net/71987",
    "https://knac.com/","https://i0.wp.com/knac.com/wp-content/uploads/2025/10/knaclogo_transparent_8-bit_658x260.png?fit=560%2C221&ssl=1","i0.wp.com"),
"go-station-000042":("The Pit | NTS","https://www.nts.live/infinite-mixtapes/the-pit","stream-mixtape-geo.ntslive.net/mixtape34",
    "https://nts.live/mobile/infinite-mixtapes","https://media.ntslive.co.uk/crop/128x128/069b6b6c-dd48-4ee2-8e35-2c2ca6b831cc_1668038400.png","media.ntslive.co.uk"),
"go-station-000067":("True Black Metal Radio","http://trueblackmetalradio.com/#/home","trueblackmetalradio.com:666/radio",
    "https://trueblackmetalradio.com/","https://trueblackmetalradio.com/assets/images/tbmr.png","trueblackmetalradio.com"),
"go-station-000107":("Rock FM 105.5","https://rockfm.com.ni/","securestream.us/radio/8050",
    "https://rockfm.com.ni/","https://rockfm.com.ni/wp-content/uploads/2016/08/Logo-Rock-fm-02.png","rockfm.com.ni"),
"go-station-000155":("idobi Howl","http://idobi.com/","idobihowl.idobi.com",
    "https://idobi.com/","https://idobi.com/wp-content/themes/idobi-2022/assets/img/idobiHowl_2022logo_Dark.png","idobi.com"),
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
            or sum(s["logo"] is None for s in active)!=36):
        raise ValueError("Expected 60-logo unsigned v8 input")
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
                row["page_verified"]=False;row["page_error"]=type(exc).__name__+": "+str(exc)[:140]
            try:
                data,mime,final=_request(image,max_bytes=MAX_IMAGE,accept="image/png,image/jpeg,image/webp")
                if urlsplit(final).hostname!=host:raise ValueError("Image redirect changed the host")
                row.update(inspect_bytes(data,content_type=mime))
                row["image_sha_verified"]=True
                row["status"]="FIRSTPARTY_ORIGINAL_SHA_VALIDATED"
            except (HTTPError,URLError,OSError,ssl.SSLError,TimeoutError,ValueError) as exc:
                row["status"]="ORIGINAL_IMAGE_NOT_VERIFIED";row["image_error"]=type(exc).__name__+": "+str(exc)[:140]
        else:row["status"]="OFFLINE_STATION_VERIFIED"
        output.append(row)
    used=[r["sha256"] for r in output if r["image_sha_verified"]]
    assert len(used)==len(set(used))
    return {"scope":"GO_V8_SIX_RETRY_OWNER_LOGOS_READ_ONLY",
            "count":6,"shas_verified":len(used),
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
