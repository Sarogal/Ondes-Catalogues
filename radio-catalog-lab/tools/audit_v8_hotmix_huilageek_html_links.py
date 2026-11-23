#!/usr/bin/env python3
"""Read-only HTML source reconnaissance for 2 radio logo identities.

No ingestion. Detects if the publisher embeds channel-specific Hotmix
Metal logo ID or if Zeno channel embeds Grosses Ondes' original HuilaGeek
stream identifier; logs only bounded, sanitized metadata contexts.
"""
from __future__ import annotations
import argparse,json,re
from pathlib import Path
from urllib.parse import urlsplit
from audit_open_radio_artwork_inventory import _request
ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/"radio-catalog-lab/full-staging/UNSIGNED-radio-v8-66-official-sha-logos-20261123.json"
PAGES={
"hotmix_metal":"https://hotmixradio.com/en",
"hotmix_all_radios":"https://hotmixradio.com/en/radios",
"huilageek_exact_name":"https://zeno.fm/radio/huilageek-radio/",
"huilageek_similar_name":"https://zeno.fm/radio/HuilaGeek",
}
def main():
    a=argparse.ArgumentParser();a.add_argument("--network",action="store_true");a.add_argument("--output",type=Path,required=True)
    p=a.parse_args()
    c=json.loads(SOURCE.read_bytes())
    active={s["go_station_id"]:s for s in c["stations"] if s["status"]["state"]=="active"}
    assert len(active)==285 and sum(s["logo"] is None for s in active.values())==30
    assert active["go-station-000212"]["display_name"]=="Hotmix meal"
    assert "hotmix-metal-en-mp3" in active["go-station-000212"]["streams"][0]["url"]
    assert active["go-station-000136"]["display_name"]=="HuilaGeek Radio"
    stream=active["go-station-000136"]["streams"][0]["url"].split("?")[0].split("/")[-1]
    assert stream=="8smiwwvtfxxvv"
    rows=[]
    for label,url in PAGES.items():
        r={"label":label,"publisher_page":url,"html_verified":False,"catalog_changed":False,
           "potentially_verified_station_id":False,"owner_channel_image_verified":False}
        if p.network:
            try:
                b,m,final=_request(url,max_bytes=4*1024*1024,accept="text/html")
                if m not in ("text/html","application/xhtml+xml",""):raise ValueError("Not HTML")
                data=b.decode("utf-8",errors="replace")
                r["html_verified"]=True
                r["original_html_size"]=len(b)
                r["stream_uuid_matches"]=stream in data
                r["metal_word_count"]=len(re.findall(r"metal",data,re.I))
                r["hotmix_image_product_ids"]=list(dict.fromkeys(re.findall(r"(?:hotmix[.]radio|hotmix[.]radio%2F)(?:/|%2F)(\d+)(?:/|%2F)image_large",data,re.I)))[:70]
                r["station_references"]=[]
                keywords=["metal"] if label.startswith("hotmix") else ["huilageek","8smiwwvtfxxvv"]
                for token in keywords:
                    for m in list(re.finditer(re.escape(token),data,re.I))[:7]:
                        fragment=data[max(0,m.start()-280):min(len(data),m.end()+340)]
                        # Strip control characters and keep bounded source evidence only.
                        r["station_references"].append(re.sub(r"[\r\n\t]+"," ",fragment)[:650])
                if label.startswith("hotmix"):
                    import html as html_tools
                    from urllib.parse import unquote
                    tiles=[]
                    for match in re.finditer(r'<button\\b(?=[^>]*aria-label=["\\\']Metal["\\\'])[^>]*>(.{0,6000}?)</button>',data,re.I|re.S):
                        block=html_tools.unescape(match.group(1))
                        src=re.search(r'<img\\b[^>]*>',block,re.I|re.S)
                        tag=unquote(src.group(0)) if src else unquote(block[:1600])
                        ids=list(dict.fromkeys(re.findall(r'hotmix\\.radio/(\\d+)/image_large',tag,re.I)))
                        tiles.append({"station_name":"Metal","channel_ids":ids,"source_image_tag":tag[:800]})
                    r["metal_tile_source_evidence"]=tiles[:5]
                    r["channel_art_identified"]=bool(tiles) and all(len(item["channel_ids"])==1 for item in tiles) and len(set(item["channel_ids"][0] for item in tiles))==1
                else:
                    r["channel_art_identified"]=r["stream_uuid_matches"] is True
            except Exception as e:
                r["reason"]=type(e).__name__+":"+str(e)[:180]
        rows.append(r)
    result={"scope":"GO_V8_HOTMIX_HUILAGEEK_HTML_OWNER_CHANNEL_RECON_READ_ONLY",
            "published":False,"signed":False,"rows":rows}
    p.output.parent.mkdir(parents=True,exist_ok=True)
    p.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"scope":result["scope"],"network":p.network,"pages":[{"label":r["label"],"html_verified":r["html_verified"],"html_size":r.get("original_html_size"),"metal_word_count":r.get("metal_word_count"),"stream_matches":r.get("stream_uuid_matches"),"channel_image_ids":r.get("hotmix_image_product_ids"),"metal_tile_evidence":r.get("metal_tile_source_evidence"),"channel_identity_verified":r.get("channel_art_identified"),"reason":r.get("reason"),"samples":r.get("station_references",[])[:3]} for r in rows]},ensure_ascii=False)[:11500])
if __name__=="__main__":main()
