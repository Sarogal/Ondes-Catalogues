#!/usr/bin/env python3
"""Audit existing signed logo descriptors without changing the catalog or cache.

Group by exact source URL, retain only digests and decoded metadata. A changed
image or failed fetch is never authorization to replace or delete artwork.
"""
import argparse
import datetime as dt
import hashlib
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

from radio_daily_v9_generator import BASELINE, encode
from radio_daily_baseline_verify import strict_json, validate_shape
from radio_daily_maintenance_preview import catalogue_rows, age, digest
from radio_catalog_logo_pilot_probe import checked_https_url, fetch_strict_https, decode_image, MAX_LOGO_BYTES
from radio_daily_qualification_dossiers import MAX_BYTES
from radio_stream_recheck_ledger import parse_day, SHA256_RE

MAX_SOURCES=8
HISTORY_DAYS=30
MIMES={"image/png","image/jpeg","image/webp"}

def metadata(logo):
    return {"imageSha256":logo["sha256"],"mime":logo["mime_type"],
            "width":logo["width"],"height":logo["height"],"byteLength":logo["byte_size"]}

def valid_metadata(o):
    return (isinstance(o,dict) and isinstance(o.get("imageSha256"),str)
            and SHA256_RE.fullmatch(o["imageSha256"]) and o.get("mime") in MIMES
            and all(type(o.get(k)) is int and 64<=o[k]<=4096 for k in ("width","height"))
            and type(o.get("byteLength")) is int and 0<o["byteLength"]<=MAX_LOGO_BYTES)

def source_policy(url):
    try:
        p=urlsplit(url)
        checked_https_url(url,p.hostname or "")
        return "query_source_held" if p.query else "eligible"
    except (ValueError,TypeError):
        return "unsafe_or_unsupported_source_held"

SOURCE_PREFIX="go-logo-source-v1:"
MANAGED_PREVIEW_HOST="radio-preview.example.org"

def managed_url(url):
    p=urlsplit(url)
    return p.hostname==MANAGED_PREVIEW_HOST or "/objects/sha256/" in p.path

def source_reference(logo, url):
    ref=SOURCE_PREFIX+logo["sha256"]+":"+url
    if len(ref)>500 or source_policy(url)!="eligible" or managed_url(url):
        raise ValueError("invalid official artwork source")
    return ref

def official_source(station):
    """Signed editorial reference bound to exact logo digest, or legacy URL."""
    logo=station["logo"]
    refs=[r for r in station["editorial"]["evidence_refs"] if r.startswith(SOURCE_PREFIX)]
    if not logo:
        if refs:
            raise ValueError("artwork source without logo")
        return None
    if refs:
        if len(refs)!=1:
            raise ValueError("ambiguous official artwork source")
        prefix=SOURCE_PREFIX+logo["sha256"]+":"
        if not refs[0].startswith(prefix):
            raise ValueError("artwork provenance digest mismatch")
        url=refs[0][len(prefix):]
        if source_reference(logo,url)!=refs[0]:
            raise ValueError("invalid artwork provenance")
        return url
    return None if managed_url(logo["url"]) else logo["url"]

def build(raw,day,*,expected=BASELINE,prior=None,limit=0,fetch=fetch_strict_https,decode=decode_image):
    day=parse_day(day)
    if type(limit) is not int or not 0<=limit<=MAX_SOURCES:
        raise ValueError("invalid artwork maintenance budget")
    catalogue_rows(raw,expected)
    doc=strict_json(raw)
    validate_shape(doc)
    groups={}
    for station in doc["stations"]:
        logo=station["logo"]
        if logo:
            url=official_source(station)
            if url is None:
                continue
            key=digest(url)
            group=groups.setdefault(key,{"url":url,"expected":{}})
            if group["url"]!=url:
                raise ValueError("source digest collision")
            group["expected"][station["go_station_id"]]=metadata(logo)
    histories={key:[] for key in groups}
    if prior is not None:
        if (prior.get("schemaVersion")!=1 or prior.get("catalogBaselineSha256")!=expected
                or prior.get("publicationAllowed") is not False or prior.get("approvedLogoCount")!=0
                or parse_day(prior["scanDate"])>day or not isinstance(prior.get("sources"),list)):
            raise ValueError("invalid logo maintenance register")
        seen=set()
        for row in prior["sources"]:
            key=row.get("sourceSha256")
            if (key not in groups or key in seen or row.get("publicationAllowed") is not False
                    or not isinstance(row.get("observations"),list) or len(row["observations"])>HISTORY_DAYS):
                raise ValueError("invalid source history")
            seen.add(key)
            dates=[]
            for o in row["observations"]:
                date=parse_day(o["date"])
                status=o.get("retrieval")
                if (date>day or status not in ("decoded","failed_review")
                        or (status=="decoded" and not valid_metadata(o.get("image")))
                        or (status=="failed_review" and o.get("image") is not None)):
                    raise ValueError("invalid logo observation")
                dates.append(date)
                if age(day,date)<HISTORY_DAYS:
                    item={"date":date,"retrieval":status}
                    if status=="decoded":
                        item["image"]={k:o["image"][k] for k in ("imageSha256","mime","width","height","byteLength")}
                    histories[key].append(item)
            if dates!=sorted(set(dates)):
                raise ValueError("invalid artwork observation dates")
    queue=[]
    for key,g in groups.items():
        h=histories[key]
        if source_policy(g["url"])!="eligible":
            continue
        if h:
            last=h[-1]
            unchanged=(last["retrieval"]=="decoded" and all(last["image"]==x for x in g["expected"].values()))
            # Slow periodic checks for unchanged images; retry other evidence
            # on a later date, never several times on the same day.
            if age(day,last["date"])<(7 if unchanged else 1):
                continue
        queue.append(key)
    queue.sort(key=lambda k:(histories[k][-1]["date"] if histories[k] else "",k))
    selected=queue[:limit]
    for key in selected:
        url=groups[key]["url"]
        try:
            checked_https_url(url,urlsplit(url).hostname)
            data,mime=fetch(url,urlsplit(url).hostname)
            if not isinstance(data,bytes) or not 0<len(data)<=MAX_LOGO_BYTES:
                raise ValueError("invalid image size")
            decoded,width,height=decode(data)
            image={"imageSha256":hashlib.sha256(data).hexdigest(),"mime":decoded,
                   "width":width,"height":height,"byteLength":len(data)}
            if mime!=decoded or not valid_metadata(image):
                raise ValueError("invalid decoded image")
            o={"date":day,"retrieval":"decoded","image":image}
        except Exception:
            o={"date":day,"retrieval":"failed_review"}
        histories[key].append(o)
    records=[]
    for s in sorted(doc["stations"],key=lambda x:x["go_station_id"]):
        logo=s["logo"]
        source=official_source(s)
        key=digest(source) if source else None
        state="missing_logo"
        last=None
        changed_days=[]
        if logo and source is None:
            state="official_source_missing_review"
        elif logo:
            state=source_policy(source)
            h=histories[key]
            if state=="eligible":
                state="awaiting_check"
                if h:
                    last=h[-1]
                    if last["retrieval"]=="failed_review":
                        state="source_unavailable_review"
                    elif last["image"]==metadata(logo):
                        state="unchanged"
                    elif last["image"]["imageSha256"]==logo["sha256"]:
                        state="descriptor_mismatch_review"
                    else:
                        state="changed_image_review"
                        for o in reversed(h):
                            if (o["retrieval"]!="decoded" or o["image"]!=last["image"]
                                    or age(day,o["date"])>7):
                                break
                            changed_days.append(o["date"])
                        if len(changed_days)>=2 and day in changed_days:
                            state="repeated_changed_image_review"
        records.append({"goStationId":s["go_station_id"],"catalogueStatus":s["status"]["state"],
                        "sourceSha256":key,"expectedImageSha256":logo["sha256"] if logo else None,
                        "observedImageSha256":last.get("image",{}).get("imageSha256") if last else None,
                        "lastObservationDate":last["date"] if last else None,"changedDates":sorted(changed_days),
                        "reviewStatus":state,"logoApproved":False,"publicationAllowed":False})
    return {"schemaVersion":1,"scanDate":day,"catalogBaselineSha256":expected,"publicationAllowed":False,
            "approvedLogoCount":0,"catalogChanged":False,"stationCount":len(records),"sourceCount":len(groups),
            "attemptedCount":len(selected),"observedSourceCount":sum(bool(h) for h in histories.values()),
            "counts":dict(sorted(Counter(x["reviewStatus"] for x in records).items())),
            "records":records,"sources":[{"sourceSha256":k,"observations":h,"publicationAllowed":False}
                                        for k,h in sorted(histories.items())]}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--baseline",type=Path,required=True)
    p.add_argument("--previous",type=Path)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--limit",type=int,default=0)
    p.add_argument("--allow-network",action="store_true")
    p.add_argument("--baseline-sha256",default=BASELINE)
    a=p.parse_args()
    if a.limit and not a.allow_network:
        p.error("network must be explicit")
    def read(path):
        if path.stat().st_size>MAX_BYTES:
            raise ValueError("oversize artwork maintenance input")
        return path.read_bytes()
    report=build(read(a.baseline),dt.datetime.now(dt.timezone.utc).date().isoformat(),
                 expected=a.baseline_sha256,prior=strict_json(read(a.previous)) if a.previous else None,limit=a.limit)
    payload=encode(report)
    if len(payload)>MAX_BYTES:
        raise ValueError("oversize artwork maintenance report")
    a.output.write_bytes(payload)
    print("RADIO_LOGO_MAINTENANCE_PREVIEW_ONLY",{k:v for k,v in report.items() if k not in ("records","sources")})

if __name__=="__main__":
    main()
