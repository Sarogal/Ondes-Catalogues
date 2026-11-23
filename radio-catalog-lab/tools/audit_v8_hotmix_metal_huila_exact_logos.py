#!/usr/bin/env python3
"""Prove exact Hotmix Metal channel tile and HuilaGeek stream owner artwork.

Hotmix: Metal-labeled HTML button names radio product 214 twice. Only
product 214 original channel image is acceptable; fallback official Next
optimizer remains first-party. Verify actual Icecast mount station name.
HuilaGeek: Zeno page embeds the exact *existing* Zeno stream identifier
8smiwwvtfxxvv; exclude similarly named Radio HuilaGeek with different ID.
Artwork is station-card image from the precise matched Zeno page.
No writes outside evidence files in Actions temp; no release signing.
"""
from __future__ import annotations
import argparse,hashlib,html,json,re,ssl
from pathlib import Path
from urllib.parse import unquote,urlsplit
from urllib.error import HTTPError,URLError
from audit_open_radio_artwork_inventory import _request,inspect_bytes,MAX_IMAGE

ROOT=Path(__file__).resolve().parents[2]
CANDIDATE=ROOT/"radio-catalog-lab/full-staging/UNSIGNED-radio-v8-66-official-sha-logos-20261123.json"
HOTMIX_PAGE="https://hotmixradio.com/en"
HOTMIX_MOUNT="https://streaming.hotmixradio.com/status.xsl"
HOTMIX_ORIGINAL="https://checkout.hotmixradio.com/web/image/hotmix.radio/214/image_large/"
HOTMIX_OPTIMIZED=("https://hotmixradio.com/_next/image?"
                  "url=https%3A%2F%2Fcheckout.hotmixradio.com%2Fweb%2Fimage%2F"
                  "hotmix.radio%2F214%2Fimage_large%2F&w=384&q=75")
HUILA_PAGE="https://zeno.fm/radio/huilageek-radio/"
HUILA_DECOY="https://zeno.fm/radio/HuilaGeek"
HUILA_IMAGE=("https://images.zeno.fm/Wxzk-aa8aGVjeBSnx-fpKhDcaFYCKXZ6DmWY20NCvKY/"
             "rs:fill:304:304/q:75/g:ce:0:0/"
             "aHR0cHM6Ly9wcm94eS56ZW5vLmZtL2NvbnRlbnQvc3RhdGlvbnMv"
             "ODdlN2M1YTItZGJjZi00NmMxLWFiZDEtODUzNDZiNzBiZjI3L2ltYWdlLz91PTE3MDE2OTk5NjcwMDA")
STREAM_ID="8smiwwvtfxxvv"
def get_html(url):
    b,m,f=_request(url,max_bytes=2*1024*1024,accept="text/html")
    if m not in ("text/html","application/xhtml+xml","application/xml","text/xml","text/plain",""):raise ValueError("Not publisher HTML or stream status XML")
    return b.decode("utf-8",errors="replace")
def metal_tile_ids(data):
    found=[]
    for match in re.finditer(r'<button(?=[^>]*aria-label="Metal")[^>]*>(.{0,6500}?)</button>',data,re.I|re.S):
        text=unquote(html.unescape(match.group(1)))
        image=re.search(r'<img[^>]*>',text,re.I|re.S)
        if not image:raise ValueError("Metal button has no image")
        ids=set(re.findall(r'hotmix[.]radio/([0-9]+)/image_large',image.group(0),re.I))
        found.append(ids)
    return found
def audit(network=False):
    doc=json.loads(CANDIDATE.read_bytes())
    active={s["go_station_id"]:s for s in doc["stations"] if s["status"]["state"]=="active"}
    if len(active)!=285 or len(doc["stations"])!=296 or len(doc["tombstones"])!=24 or doc["release_sequence"]!=8 or sum(s["logo"] is None for s in active.values())!=30:
        raise ValueError("Expected 66-logo unsigned v8 predecessor")
    m=active["go-station-000212"]
    h=active["go-station-000136"]
    if m["display_name"]!="Hotmix meal" or m["logo"] is not None or "hotmix-metal-en-mp3" not in m["streams"][0]["url"]:
        raise ValueError("Wrong Hotmix Metal station")
    if h["display_name"]!="HuilaGeek Radio" or h["logo"] is not None or STREAM_ID not in h["streams"][0]["url"]:
        raise ValueError("Wrong HuilaGeek station")
    records=[]
    for sid,name,page,sources in (
        ("go-station-000212",m["display_name"],HOTMIX_PAGE,[HOTMIX_ORIGINAL,HOTMIX_OPTIMIZED]),
        ("go-station-000136",h["display_name"],HUILA_PAGE,[HUILA_IMAGE]),
    ):
        row={"go_station_id":sid,"name":name,"publisher_page":page,
             "verified_owner_channel":False,"original_image_verified":False,
             "signed":False,"published":False,"possible_original_images":[]}
        if network:
            try:
                if sid=="go-station-000212":
                    original=get_html(page)
                    tiles=metal_tile_ids(original)
                    assert len(tiles)>=1 and all(ids=={"214"} for ids in tiles),"No unique exact 214 Metal tile"
                    status=get_html(HOTMIX_MOUNT)
                    assert "/hotmix-metal-en-mp3" in status and "Hotmix Metal" in status
                    row["verified_owner_channel"]=True
                    row["publisher_verified_product_id"]="214"
                    row["owner_metal_buttons"]=len(tiles)
                    row["stream_mount_verified"]=True
                else:
                    html_exact=get_html(page)
                    html_decoy=get_html(HUILA_DECOY)
                    assert "HuilaGeek Radio" in html_exact
                    assert STREAM_ID in html_exact and STREAM_ID not in html_decoy
                    assert "87e7c5a2-db"+"cf-46c1-abd1-85346b70bf27" in html_exact
                    row["verified_owner_channel"]=True
                    row["matched_existing_stream_id"]=STREAM_ID
                    row["different_named_station_rejected"]=True
            except (HTTPError,URLError,OSError,ssl.SSLError,TimeoutError,ValueError,AssertionError) as e:
                row["proof_error"]=type(e).__name__+":"+str(e)[:130]
            for image in sources:
                evidence={"image_url":image,"valid":False}
                try:
                    payload,mime,final=_request(image,max_bytes=MAX_IMAGE,accept="image/png,image/jpeg,image/webp")
                    approved_hosts={"checkout.hotmixradio.com","hotmixradio.com"} if sid=="go-station-000212" else {"images.zeno.fm"}
                    if urlsplit(final).hostname not in approved_hosts:
                        raise ValueError("Unapproved publisher image host")
                    meta=inspect_bytes(payload,content_type=mime)
                    evidence.update(meta)
                    evidence["valid"]=True
                except (HTTPError,URLError,OSError,ssl.SSLError,TimeoutError,ValueError) as e:
                    evidence["error"]=type(e).__name__+":"+str(e)[:130]
                row["possible_original_images"].append(evidence)
            row["original_image_verified"]=any(x["valid"] for x in row["possible_original_images"])
            row["status"]="CHANNEL_ID_AND_IMAGE_SHA_VERIFIED" if row["verified_owner_channel"] and row["original_image_verified"] else "UNVERIFIED"
        else:row["status"]="OFFLINE_IDS_CHECKED"
        records.append(row)
    return {"scope":"GO_TEST_V8_HOTMIX_METAL_214_HUILAGEEK_MATCHED_STATION_SHA_AUDIT",
            "stations":2,"owner_channels_verified":sum(x["verified_owner_channel"] for x in records),
            "images_verified":sum(x["original_image_verified"] for x in records),
            "signed":False,"published":False,"records":records}
def main():
    p=argparse.ArgumentParser();p.add_argument("--network",action="store_true")
    p.add_argument("--output",type=Path,required=True);a=p.parse_args()
    r=audit(a.network);a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(r,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"scope":r["scope"],"owner_channels_verified":r["owner_channels_verified"],"images_verified":r["images_verified"]},sort_keys=True))
    for x in r["records"]:
        print(x["go_station_id"],x["status"],x["verified_owner_channel"],x.get("proof_error",""),
              [(y["image_url"],y.get("sha256","NOT_VERIFIED"),y.get("error","")) for y in x["possible_original_images"]])
if __name__=="__main__":main()
