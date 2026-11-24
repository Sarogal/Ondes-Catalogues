#!/usr/bin/env python3
"""Read-only open discovery of missing GO v7 logo candidates by exact Radio Browser UUID.

The source is the actual signed TEST v7 (285 active stations, 96 without logos).
Retrieve exact official Radio Browser station UUID entries in bounded batches,
never search by ambiguous genre or name, then fetch candidate favicon image
bytes through the shared HTTPS/DNS safety gate and calculate SHA-256.

An image seen in Radio Browser is ONLY A CANDIDATE. Images already assigned
to an unrelated station, non-HTTPS links, shared generic placeholders, name
mismatches and image provider redirects are NOT considered approved. A second
stage may select first-party station images from this evidence only after
all shard results are joined and de-duplicated across the full 96-station set.

No catalogue edits, no signing, no publication, no private keys.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlencode,urlsplit
from urllib.error import HTTPError,URLError
import ssl

from audit_open_radio_artwork_inventory import (
    _request, public_https, probe_image,
)

ROOT=Path(__file__).resolve().parents[2]
CATALOG=ROOT/"grossesondes/radio-test-v2/releases/f735884aa0841a86d88aaafe406e62b7a826cf9cd60f6a70285a0894326841aa.json"
EXPECTED_SHA="f735884aa0841a86d88aaafe406e62b7a826cf9cd60f6a70285a0894326841aa"
BASE="https://de1.api.radio-browser.info"
MAX_RESPONSE=450*1024
UA_UUID_RE=re.compile(r"^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$")
IGNORE={"radio","rock","metal","the","live","music","online","fm","stream","web","by","station","and","in","24","7","radioonline","radiofm"}
GENERIC_NAMES={"default","unknown","logo","noimage","no-logo","placeholder","radio","favicon","image"}


def original_missing()->tuple[list[dict],dict[str,list[str]]]:
    raw=CATALOG.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=EXPECTED_SHA:
        raise ValueError("Signed TEST v7 content digest mismatch")
    j=json.loads(raw)
    if j["release_sequence"]!=7 or len(j["stations"])!=296:
        raise ValueError("Unexpected signed source v7")
    active=[s for s in j["stations"] if s["status"]["state"]=="active"]
    missing=sorted([s for s in active if s["logo"] is None],
                   key=lambda s:s["go_station_id"])
    if len(active)!=285 or len(missing)!=96:
        raise ValueError("Not the approved 96 logo-missing v7 stations")
    prior={}
    for s in active:
        if s["logo"] is not None:
            prior.setdefault(s["logo"]["sha256"],[]).append(s["go_station_id"])
    return missing,prior


def hostname(url:str)->str:
    if not url:
        return ""
    try:
        return (urlsplit(url).hostname or "").lower().removeprefix("www.")
    except ValueError:
        return ""


def same_brand_domain(a:str,b:str)->bool:
    a=hostname(a);b=hostname(b)
    if not a or not b:
        return False
    return (a==b or a.endswith("."+b) or b.endswith("."+a) or
            # Only compare two registrable levels for ordinary TLDs; false
            # positives with co.uk/com.br are avoided by the exact test above.
            (len(a.split("."))==2 and
             len(b.split("."))==2 and a==b) or
            (len(a.split("."))>2 and len(b.split("."))>2 and
             a.split(".")[-2:]==b.split(".")[-2:]
             and a.split(".")[-2] not in {"com","co","org","net"}))


def tokens(name:str)->set[str]:
    return set(x for x in re.findall(r"[^\W_]+",name.casefold(),flags=re.UNICODE)
               if len(x)>2 and x not in IGNORE)


def close_station_name(old:str,current:str)->bool:
    a=tokens(old);b=tokens(current)
    if not a or not b:
        return SequenceMatcher(None,old.casefold(),current.casefold()).ratio()>=.75
    shared=a&b
    # Single-word identities like WSOU have a strong exact-match token.
    if len(a)==1 and a.issubset(b):
        return True
    if len(b)==1 and b.issubset(a):
        return True
    ratio=len(shared)/max(1,min(len(a),len(b)))
    return ratio>=.55 or SequenceMatcher(None,old.casefold(),current.casefold()).ratio()>=.75


def uuid_rows(uuid_list:list[str])->tuple[dict[str,dict],str]:
    if not uuid_list:
        return {},"EMPTY"
    if len(uuid_list)>18 or any(not UA_UUID_RE.fullmatch(x) for x in uuid_list):
        raise ValueError("Unsafe UUID batch")
    address=BASE+"/json/stations/byuuid?"+urlencode({"uuids":",".join(uuid_list),"limit":100})
    try:
        data,mime,final=_request(address,max_bytes=MAX_RESPONSE,accept="application/json")
        if hostname(final)!=hostname(BASE) or mime not in {
            "application/json","application/json; charset=utf-8","text/json",""
        }:
            raise ValueError("Unexpected Radio Browser response domain or MIME")
        rows=json.loads(data)
        if not isinstance(rows,list) or len(rows)>100:
            raise ValueError("Oversized/malformed Radio Browser stations list")
        allowed=set(uuid_list)
        result={}
        for item in rows:
            uuid=item.get("stationuuid") if isinstance(item,dict) else None
            if uuid in allowed and uuid not in result:
                result[uuid]=item
        return result,"OK"
    except (ValueError,HTTPError,URLError,TimeoutError,ssl.SSLError,
            OSError,UnicodeDecodeError) as exc:
        return {},type(exc).__name__


def classify(st:dict,rb:dict)->tuple[str,str,str]:
    favicon=(rb.get("favicon") or "").strip()
    currentname=str(rb.get("name") or "").strip()
    if not favicon:
        return "EMPTY_FAVICON",favicon,""
    if not public_https(favicon):
        return "UNSAFE_FAVICON_URL",favicon,""
    if not close_station_name(st["display_name"],currentname):
        return "MISMATCHED_STATION_NAME",favicon,""
    if not (same_brand_domain(st.get("homepage") or "",rb.get("homepage") or "")
            or same_brand_domain(st["streams"][0]["url"],rb.get("url_resolved") or "")
            or same_brand_domain(st["streams"][0]["url"],rb.get("url") or "")):
        return "STATION_UUID_VERIFIED_HOMEPAGE_UNCONFIRMED",favicon,""
    if (same_brand_domain(favicon,st.get("homepage") or "")
            or same_brand_domain(favicon,rb.get("homepage") or "")):
        return "FIRST_PARTY_LOGO_SOURCE_CANDIDATE",favicon,"first_party"
    return "THIRD_PARTY_LOGO_SOURCE_CANDIDATE",favicon,"third_party"


def inspect_station(st:dict,uuid_map:dict[str,dict],network:bool)->dict:
    aliases=[x["uuid"] for x in st["radio_browser_uuids"]
             if x.get("state")=="current" and UA_UUID_RE.fullmatch(x["uuid"])]
    out={"go_station_id":st["go_station_id"],"station_name":st["display_name"],
         "catalog_homepage":st.get("homepage"),"radio_browser_uuids":aliases,
         "matched_directory_entries":0,"candidate_logos":[]}
    seen=set()
    for uuid in aliases:
        item=uuid_map.get(uuid)
        if not item:
            continue
        out["matched_directory_entries"]+=1
        label,logo,confidence=classify(st,item)
        entry={"radio_browser_uuid":uuid,
               "radio_browser_name":item.get("name"),
               "directory_homepage":item.get("homepage"),
               "directory_stream":item.get("url"),
               "directory_favicon":logo,
               "identity_gate":label,"confidence":confidence,
               "image_sha256":None,"image_bytes_verified":False,
               "publication_allowed":False}
        if logo and logo not in seen and label in {
            "FIRST_PARTY_LOGO_SOURCE_CANDIDATE",
            "THIRD_PARTY_LOGO_SOURCE_CANDIDATE",
        } and network:
            img=probe_image(logo)
            entry["image_bytes_verified"]=img.get("verified_bytes") is True
            if entry["image_bytes_verified"]:
                for k in ("sha256","byte_size","width","height","mime_type"):
                    entry["image_"+k if k=="sha256" else k]=img[k]
            else:
                entry["image_problem"]=img.get("reason")
        out["candidate_logos"].append(entry)
        if logo:seen.add(logo)
    return out


def collect(shard:int,shards:int,network:bool)->dict:
    missing,prior=original_missing()
    if not 0<=shard<shards<=24:
        raise ValueError("Invalid shard")
    selection=[s for i,s in enumerate(missing) if i%shards==shard]
    ids=sorted({x["uuid"] for s in selection for x in s["radio_browser_uuids"]
                if x.get("state")=="current" and UA_UUID_RE.fullmatch(x["uuid"])})
    uuid_map={}
    api_states=[]
    if network:
        # Up to 18 UUIDs per authenticated directory query.
        for i in range(0,len(ids),18):
            block=ids[i:i+18]
            found,state=uuid_rows(block)
            uuid_map.update(found)
            api_states.append({"uuid_count":len(block),"state":state,"found":len(found)})
    with ThreadPoolExecutor(max_workers=6) as workers:
        jobs={workers.submit(inspect_station,s,uuid_map,network):s for s in selection}
        records=[future.result() for future in as_completed(jobs)]
    records.sort(key=lambda x:x["go_station_id"])
    # Conservative v7 cross-check only local to image descriptors already
    # assigned to OTHER station; global candidate cross-check happens later.
    for r in records:
        for item in r["candidate_logos"]:
            sha=item.get("image_sha256")
            if sha and sha in prior:
                item["existing_logo_sha_already_used_by"]=prior[sha]
                item["approval_risk"]="SHARED_WITH_EXISTING_CATALOG_STATIONS"
    return {
        "scope":"GO_TEST_V7_96_MISSING_LOGOS_RB_UUID_PROVENANCE_ONLY",
        "catalog_content_sha256":EXPECTED_SHA,
        "active_radios":285,
        "missing_logo_descriptors":96,
        "shard":shard,"shards":shards,
        "selected_station_count":len(selection),
        "api_calls":api_states,
        "directory_entries_found":sum(r["matched_directory_entries"] for r in records),
        "first_party_images_sha_verified":sum(
            p["image_bytes_verified"] and p["confidence"]=="first_party"
            for r in records for p in r["candidate_logos"]),
        "other_images_sha_verified":sum(
            p["image_bytes_verified"] and p["confidence"]=="third_party"
            for r in records for p in r["candidate_logos"]),
        "publication_allowed":False,
        "modified_catalog":False,
        "records":records,
    }


def main()->None:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--shard",type=int,required=True)
    p.add_argument("--shards",type=int,default=8)
    p.add_argument("--network",action="store_true")
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    result=collect(a.shard,a.shards,a.network)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",
                        encoding="utf-8")
    print(json.dumps({
        "result":"GO_V8_RADIO_BROWSER_UUID_DISCOVERY_READ_ONLY",
        "shard":a.shard,"shards":a.shards,
        "stations":result["selected_station_count"],
        "directory_entries_found":result["directory_entries_found"],
        "first_party_verified":result["first_party_images_sha_verified"],
        "third_party_verified":result["other_images_sha_verified"],
        "publication_allowed":False,
    },sort_keys=True))


if __name__=="__main__":
    main()
