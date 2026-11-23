#!/usr/bin/env python3
"""Read-only official hosted radio channel image audit on PCRadio and Zeno.

Per-radio publisher-hosted image (not now-playing music cover) on two PCRadio
artist channels and two Zeno.FM operator channel pages.
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
BASE=ROOT/"radio-catalog-lab/full-staging/UNSIGNED-radio-v8-49-official-sha-logos-20261123.json"
SOURCES={
"go-station-000224":("Manowar Радио","https://pcradio.app/radio/manowar","stream.pcradio.ru/Manowar-hi",
    "https://pcradio.app/radio/manowar","https://media.pcradio.app/media/logos/180/1006416/logo_4xBMYN5h1n.jpg?v=20260529-media-restore","media.pcradio.app"),
"go-station-000257":("Pantera","https://pcradio.ru/","stream.pcradio.ru/Pantera-hi",
    "https://pcradio.app/radio/pantera","https://media.pcradio.app/media/logos/180/1006431/logo_dNQRgQqt2p.jpg?v=20260529-media-restore","media.pcradio.app"),
"go-station-000301":("Monsters of Rock USSR","https://zeno.fm/radio/monsters-of-rock-ussr/","stream-51.zeno.fm/6nbz7p2w908uv",
    "https://zeno.fm/radio/monsters-of-rock-ussr/","https://images.zeno.fm/1-zxYdHVz_G_5YIoTK0vcnJLxbhNLGqJWfpwNlkEb1M/rs:fill:304:304/q:75/g:ce:0:0/aHR0cHM6Ly9wcm94eS56ZW5vLmZtL2NvbnRlbnQvc3RhdGlvbnMvYWd4emZucGxibTh0YzNSaGRITnlNZ3NTQ2tGMWRHaERiR2xsYm5RWWdJRGc2Y2UxMXdnTUN4SU9VM1JoZEdsdmJsQnliMlpwYkdVWWdJQ3d6ZG1JeEFzTW9nRUVlbVZ1YncvaW1hZ2UvP3U9MTY2MTczNjkzMzAwMA","images.zeno.fm"),
"go-station-000239":("夜愿电台Nightwish Radio","https://zeno.fm/radio/yeyuan/","stream.zeno.fm/98wt67yfky8uv",
    "https://zeno.fm/radio/yeyuan/","https://images.zeno.fm/5KgfShHGVvYFHO0NL_ksyt2oscAkhsWWg5jsGU6YAX0/rs:fill:304:304/q:75/g:ce:0:0/aHR0cHM6Ly9wcm94eS56ZW5vLmZtL2NvbnRlbnQvc3RhdGlvbnMvYWd4emZucGxibTh0YzNSaGRITnlNZ3NTQ2tGMWRHaERiR2xsYm5RWWdJQ3c5cWlWNUFnTUN4SU9VM1JoZEdsdmJsQnliMlpwYkdVWWdJQ3c0ZENDdHdrTW9nRUVlbVZ1YncvaW1hZ2UvP3U9MTY2MTYzNzQ0MzAwMA","images.zeno.fm"),
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
            or sum(s["logo"] is None for s in active)!=47):
        raise ValueError("Expected 49-logo v8 input")
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
    return {"scope":"GO_V8_FOUR_PCRADIO_ZENO_CHANNEL_IMAGES_READ_ONLY",
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
