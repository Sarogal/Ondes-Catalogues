#!/usr/bin/env python3
"""Read-only original broadcaster logo asset probe for eight additional stations.

Sources selected from official broadcaster websites, not directory art.
Validates current v8 station identity, broadcaster site, known stream,
image HTTPS host, bounded original image bytes, SHA256, MIME, dimensions.
Each report documents any unverified page->image association. No publishing.
"""
import argparse,json,ssl
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import urljoin,urlsplit,unquote
from urllib.error import HTTPError,URLError
from audit_open_radio_artwork_inventory import _request,inspect_bytes,MAX_HTML,MAX_IMAGE

ROOT=Path(__file__).resolve().parents[2]
CANDIDATE=ROOT/"radio-catalog-lab/full-staging/UNSIGNED-radio-v8-35-official-sha-logos-20261123.json"
# id: [signed-station-name, original-homepage, stream-substring,
#      official broadcaster page, first-party image or broadcaster's own CDN, allowed image hostname]
SOURCES={
"go-station-000018":(
    "Nuclear Fallout Radio","https://www.nuclearfalloutradio.com/","radioforge.com:5170",
    "https://www.nuclearfalloutradio.com/",
    "https://www.nuclearfalloutradio.com/wp-content/uploads/cropped-cropped-NFR_HEAD_NEW_REV2.jpg",
    "www.nuclearfalloutradio.com"),
"go-station-000028":(
    "X Transmission FM","http://xtransmissionfm.com/","x_transmission_fm",
    "https://xtransmissionfm.com/",
    "https://xtransmissionfm.com/wp-content/uploads/2015/08/377264_182537345163897_1845871290_n.jpg",
    "xtransmissionfm.com"),
"go-station-000035":(
    "METAL ONLY - http://www.metal-only.de,METAL ONLY - http://www.metal-only.de - 24h Black Death Heavy Metal Rock und mehr!",
    None,"metal-only.sp.radio.fm/stream",
    "https://www.metal-only.de/",
    "https://www.metal-only.de/fileadmin/tpl/img/metal-only.png",
    "www.metal-only.de"),
"go-station-000310":(
    "Heavy Music Atmospheric Radio","https://www.heavy-music.net/","stream.heavy-music.net:8176",
    "https://heavy-music.net/",
    "https://www.heavy-music.net/images/logo-share.png",
    "www.heavy-music.net"),
"go-station-000303":(
    "Heavy Metal History radio","https://heavymetalhistory.net/","stream.zeno.fm/8j4omrwrk2puv",
    "https://heavymetalhistory.net/",
    "https://heavymetalhistory.net/pic/hmh.png",
    "heavymetalhistory.net"),
"go-station-000302":(
    "METALSCENA netRADIO","https://www.metalscena.sk/","listen.radioking.com/radio/263218",
    "https://metalscena.sk/",
    "https://metalscena.sk/wp-content/uploads/2025/02/cropped-Metalscena_logo_2025.png",
    "metalscena.sk"),
"go-station-000197":(
    "Prog Palace Radio's The Armory","https://www.progpalaceradio.com/the-armory/","streemlion.com/progpalace64",
    "https://www.progpalaceradio.com/the-armory/",
    "https://www.progpalaceradio.com/wp-content/uploads/2021/04/progpalaceradioguitarstamp4vector-e1618438690529.png",
    "www.progpalaceradio.com"),
"go-station-000088":(
    "Metal Heads","https://metalheads.com.br/","brascast.com:9194",
    "https://metalheads.com.br/",
    "https://minharadioonline.net/contents/187/cover/xm996ad2da974e60ed301ce66f332ed149_187_1779459868.jpg",
    "minharadioonline.net"),
}
class Parser(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.assets=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag in ("img","source"):
            for k in ("src","data-src","data-lazy-src"):
                if a.get(k):self.assets.append(a[k])
            if a.get("srcset"):self.assets.extend(x.strip().split()[0] for x in a["srcset"].split(",") if x.strip())
        elif tag=="meta" and ((a.get("property") or "").lower() in ("og:image","og:image:url") or (a.get("name") or "").lower() in ("twitter:image","twitter:image:src")):
            if a.get("content"):self.assets.append(a["content"])
def canonical(s):
    p=urlsplit(s);return p.hostname,unquote(p.path)
def audit(network=False):
    cat=json.loads(CANDIDATE.read_bytes())
    active=[s for s in cat["stations"] if s["status"]["state"]=="active"]
    if (cat["release_sequence"]!=8 or len(cat["stations"])!=296 or len(active)!=285
            or len(cat["tombstones"])!=24 or sum(s["logo"] is None for s in active)!=61):
        raise ValueError("Expected previously verified unsigned 35-logo candidate")
    by_id={s["go_station_id"]:s for s in active}
    rows=[]
    for sid,(name,home,stream,page,asset,asset_host) in SOURCES.items():
        st=by_id[sid]
        if (st["display_name"]!=name or st["homepage"]!=home
            or st["logo"] is not None or st["status"]["state"]!="active"
            or not any(stream in item["url"] for item in st["streams"])):
            raise ValueError("Wrong station, identity, or live stream "+sid)
        if urlsplit(page).scheme!="https" or urlsplit(asset).scheme!="https" or urlsplit(asset).hostname!=asset_host:
            raise ValueError("Unverified publisher image host")
        record={"go_station_id":sid,"station_name":name,"original_page":page,
                "image_url":asset,"publisher_asset_host":asset_host,
                "page_html_matched":False,"image_sha_verified":False,
                "catalog_changed":False,"release_signed":False,"published":False}
        if network:
            try:
                body,media,final=_request(page,max_bytes=MAX_HTML,accept="text/html")
                if media not in ("text/html","application/xhtml+xml",""):
                    raise ValueError("Publisher HTML not found")
                parser=Parser();parser.feed(body.decode("utf-8",errors="replace"))
                record["page_html_verified"]=True
                record["page_html_matched"]=any(canonical(urljoin(final,u))==canonical(asset) for u in parser.assets)
            except (HTTPError,URLError,TimeoutError,ssl.SSLError,OSError,ValueError) as e:
                record["page_html_verified"]=False
                record["page_error"]=type(e).__name__
            try:
                body,media,final=_request(asset,max_bytes=MAX_IMAGE,accept="image/png,image/jpeg,image/webp")
                if urlsplit(final).hostname!=asset_host:
                    raise ValueError("Original publisher image redirected to another host")
                record.update(inspect_bytes(body,content_type=media))
                record["image_sha_verified"]=True
                record["status"]="ORIGINAL_FIRST_PARTY_IMAGE_SHA_VALIDATED"
            except (HTTPError,URLError,TimeoutError,ssl.SSLError,OSError,ValueError) as e:
                record["status"]="IMAGE_UNVERIFIED"
                record["image_error"]=type(e).__name__
        else:record["status"]="OFFLINE_IDENTITY_VALIDATED"
        rows.append(record)
    shas=[r["sha256"] for r in rows if r["image_sha_verified"]]
    if len(shas)!=len(set(shas)):raise ValueError("Shared generic asset detected")
    return {"scope":"GO_V8_EIGHT_FURTHER_BROADCASTER_ORIGINAL_LOGOS_READ_ONLY",
            "targets":len(SOURCES),"original_shas_verified":len(shas),
            "publisher_html_matches":sum(r["page_html_matched"] for r in rows),
            "catalog_changed":False,"published":False,"rows":rows}
def main():
    args=argparse.ArgumentParser()
    args.add_argument("--network",action="store_true")
    args.add_argument("--output",type=Path,required=True)
    a=args.parse_args()
    report=audit(a.network)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({x:report[x] for x in ("scope","targets","original_shas_verified","publisher_html_matches","published")},sort_keys=True))
    for r in report["rows"]:
        print(r["go_station_id"],r["station_name"],r["status"],r.get("sha256","NO_SHA"),r["page_html_matched"])
if __name__=="__main__":main()
