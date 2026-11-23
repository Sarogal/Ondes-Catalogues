#!/usr/bin/env python3
"""Second publisher-site seven-radio logo probe for signed-catalog TEST v8 (read only).

No logos copied from third-party directories; compares exact station names,
publisher website identity and current stream with reviewed official page
image URL. Distinguishes verified image bytes from unproven page associations.
"""
from __future__ import annotations
import argparse,json
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import urlsplit,unquote,urljoin
from urllib.error import HTTPError,URLError
import ssl
from audit_open_radio_artwork_inventory import _request,inspect_bytes,MAX_HTML,MAX_IMAGE

ROOT=Path(__file__).resolve().parents[2]
CANDIDATE=ROOT/"radio-catalog-lab/full-staging/UNSIGNED-radio-v8-metalon-3-independent-3-firstparty-7-maximum-3-broadcaster-7-20261123.json"
TARGETS={
 "go-station-000107":{
  "name":"Rock FM 105.5","homepage":"https://rockfm.com.ni/","page":"https://rockfm.com.ni/",
  "image":"https://rockfm.com.ni/wp-content/uploads/2016/08/Logo-Rock-fm-02.png",
  "stream":"securestream.us/radio/8050/radio.mp3"},
 "go-station-000236":{
  "name":"Overdrive Live! Station","homepage":"https://www.overdrivelive.net/","page":"https://overdrivelive.net/",
  "image":"https://overdrivelive.net/wp-content/uploads/2026/08/favicon_overdrivelive-150x150.png",
  "stream":"stream.overdrivelive.net:8000/alternative_128.mp3"},
 "go-station-000234":{
  "name":"Metalwar","homepage":"https://metalwar.gr/","page":"https://www.metalwar.gr/",
  "image":"https://www.metalwar.gr/wp-content/uploads/2023/01/metalwar.gr-Back-LOGO-LOW.webp",
  "stream":"c2.radioboss.fm:8674"},
 "go-station-000217":{
  "name":"Código Metal Radio","homepage":"https://www.codigometal.cl/","page":"https://www.codigometal.cl/",
  "image":"https://www.codigometal.cl/logo_redes.jpg",
  "stream":"streaming.viphosting.cl/8012/stream"},
 "go-station-000225":{
  "name":"Metal Invasion Radio","homepage":"https://metal-invasion.fr/","page":"https://metal-invasion.fr/",
  "image":"https://metal-invasion.fr/wp-content/uploads/2017/05/cropped-Banniere-Final-metal-invasion.fr_.png",
  "stream":"radio.metal-invasion.fr/radio/8000/stream96"},
 "go-station-000213":{
  "name":"The Generator","homepage":"https://thegenerator.co.nz/","page":"https://thegenerator.co.nz/",
  "image":"https://thegenerator.co.nz/wp-content/uploads/2020/12/logo_2021.png",
  "stream":"s1.myradiostream.com/:14268"},
 "go-station-000182":{
  "name":"PureRock.US - America's Pure Rock","homepage":"http://www.purerock.us/","page":"https://www.purerock.us/",
  "image":"https://www.purerock.us/images/Pure-Rock-New.png",
  "stream":"rosetta.shoutca.st:8524"},
}

class Images(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True);self.urls=[]
    def handle_starttag(self,tag,attrs):
        if tag not in ("img","meta","source"):return
        a=dict(attrs)
        for k in ("src","data-src","data-lazy-src","content"):
            if a.get(k):self.urls.append(a[k])
        if a.get("srcset"):
            self.urls.extend(piece.strip().split()[0] for piece in a["srcset"].split(",") if piece.strip())

def norm(src):
    p=urlsplit(src)
    return ((p.hostname or "").removeprefix("www."),unquote(p.path),p.query)
def audit(network=False):
    doc=json.loads(CANDIDATE.read_bytes())
    active=[s for s in doc["stations"] if s["status"]["state"]=="active"]
    if (doc["release_sequence"]!=8 or len(doc["stations"])!=296
            or len(doc["tombstones"])!=24 or len(active)!=285
            or sum(s["logo"] is None for s in active)!=73):
        raise ValueError("Expected unsigned 23-logo v8 source")
    by_id={s["go_station_id"]:s for s in active}
    out=[]
    for sid,c in TARGETS.items():
        st=by_id[sid]
        if (st["logo"] is not None or st["display_name"]!=c["name"]
                or st["homepage"]!=c["homepage"]
                or not any(c["stream"] in s["url"] for s in st["streams"])):
            raise ValueError("Unmatched station identity "+sid)
        page_host=urlsplit(c["page"]).hostname
        image_host=urlsplit(c["image"]).hostname
        if (not page_host or not image_host or
                page_host.removeprefix("www.")!=image_host.removeprefix("www.")
                or urlsplit(c["page"]).scheme!="https" or urlsplit(c["image"]).scheme!="https"):
            raise ValueError("Not exact safe publisher source")
        row={"go_station_id":sid,"station_name":c["name"],
             "publisher_page":c["page"],"image_url":c["image"],
             "publisher_html_mapping_verified":False,
             "publisher_page_verified":False,"sha_verified":False,
             "published":False,"catalog_modified":False}
        if network:
            try:
                data,mime,final=_request(c["page"],max_bytes=MAX_HTML,accept="text/html")
                if urlsplit(final).hostname!=page_host or mime not in ("","text/html","application/xhtml+xml"):
                    raise ValueError("Official page not recognized")
                parser=Images();parser.feed(data.decode("utf-8",errors="replace"))
                row["publisher_page_verified"]=True
                row["publisher_html_mapping_verified"]=any(
                    norm(urljoin(final,x))==norm(c["image"]) for x in parser.urls)
            except (HTTPError,URLError,OSError,TimeoutError,ssl.SSLError,ValueError) as exc:
                row["page_error"]=type(exc).__name__
            try:
                data,mime,final=_request(c["image"],max_bytes=MAX_IMAGE,accept="image/png,image/jpeg,image/webp")
                if urlsplit(final).hostname!=image_host:raise ValueError("Image source host changed")
                row.update(inspect_bytes(data,content_type=mime))
                row["sha_verified"]=True
                row["status"]="PUBLISHER_IMAGE_SHA_VALIDATED"
            except (HTTPError,URLError,OSError,TimeoutError,ssl.SSLError,ValueError) as exc:
                row["status"]="PUBLISHER_IMAGE_UNVERIFIED";row["image_error"]=type(exc).__name__
        else:row["status"]="NO_NETWORK"
        out.append(row)
    shas=[x["sha256"] for x in out if x["sha_verified"]]
    if len(shas)!=len(set(shas)):
        raise ValueError("Shared/generic publisher SHA detected")
    return {"scope":"GO_V8_7_MORE_FIRSTPARTY_RADIO_LOGOS_READ_ONLY",
            "target_count":7,"verified_count":len(shas),
            "confirmed_html_mapping_count":sum(x["publisher_html_mapping_verified"] for x in out),
            "catalog_modified":False,"publication_allowed":False,"records":out}
def main():
    p=argparse.ArgumentParser()
    p.add_argument("--network",action="store_true")
    p.add_argument("--output",type=Path,required=True);a=p.parse_args()
    report=audit(a.network)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:report[k] for k in ("scope","target_count","verified_count","confirmed_html_mapping_count","publication_allowed")},sort_keys=True))
    for r in report["records"]:
        print(r["go_station_id"],r["station_name"],r["status"],r.get("sha256","NO_SHA"),r["publisher_html_mapping_verified"])
if __name__=="__main__":main()
