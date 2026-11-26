#!/usr/bin/env python3
"""Discover replacement stream hints for existing stations. Never replace a URL.

Radio Browser identity is not broadcaster ownership. Search by exact station
identity regardless of genre tags, keep only digests in the durable report.
"""
import argparse
import json
import unicodedata
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

from radio_daily_maintenance_preview import catalogue_rows, digest, age, IDENT
from radio_daily_v9_generator import BASELINE
from radio_daily_qualification_dossiers import MAX_BYTES
from radio_daily_discovery import fetch_page, resolve_api_mirrors, is_public_stream
from radio_daily_editorial_preview import homepage_url
from radio_catalog_daily_candidate_reconcile import index_catalog, checked_uuid
from radio_stream_recheck_ledger import parse_day, SHA256_RE

MAX_SEARCH=4
PAGE_SIZE=50
MAX_HINTS=8
ELIGIBLE={"availability_recheck","quarantine_review","inconclusive"}
KINDS={"known_uuid_and_exact_identity","new_uuid_exact_identity"}
STATUSES={"candidates_observed","no_candidate_observed","incomplete_search","service_held"}

def name_key(value):
    return unicodedata.normalize("NFC",value).strip().casefold() if isinstance(value,str) else ""

def page_key(value):
    url=homepage_url(value)
    if not url:
        return None
    p=urlsplit(url)
    return (p.hostname.removeprefix("www."),p.path.rstrip("/") or "/")

def match(station,row,owners,occupied):
    try:
        uid=checked_uuid(row.get("stationuuid"))
    except ValueError:
        return None
    sid=station["go_station_id"]
    owner=owners.get(uid)
    if owner and owner!=sid:
        return None
    if name_key(row.get("name"))!=name_key(station.get("display_name")):
        return None
    page=page_key(station.get("homepage"))
    if not page or page_key(row.get("homepage"))!=page:
        return None
    country=station.get("country_code")
    code=row.get("countrycode")
    if country and code!=country:
        return None
    current={x["uuid"] for x in station.get("radio_browser_uuids",[]) if x.get("state")=="current"}
    if owner and uid not in current:
        return None
    # An unknown UUID requires a known country, not just a shared brand page.
    if not owner and (not country or code!=country):
        return None
    url=row.get("url_resolved") or row.get("url") or row.get("streamUrl")
    if not is_public_stream(url) or url in occupied:
        return None
    return {"stationuuid":uid,"streamSha256":digest(url),
            "identityHint":"known_uuid_and_exact_identity" if owner else "new_uuid_exact_identity",
            "directoryReachableHint":row.get("lastcheckok") in (True,1,"1"),
            "broadcasterVerified":False,"technicalVerified":False,"publicationAllowed":False}

def validate_hint(h):
    if (not isinstance(h,dict) or checked_uuid(h.get("stationuuid"))!=h["stationuuid"]
            or not SHA256_RE.fullmatch(h.get("streamSha256") or "")
            or h.get("identityHint") not in KINDS or type(h.get("directoryReachableHint")) is not bool
            or any(h.get(k) is not False for k in ("broadcasterVerified","technicalVerified","publicationAllowed"))
            or set(h)!={"stationuuid","streamSha256","identityHint","directoryReachableHint",
                       "broadcasterVerified","technicalVerified","publicationAllowed"}):
        raise ValueError("invalid repair hint")

def build(raw,maintenance,discovery,*,expected=BASELINE,prior=None,limit=0,search=None):
    day=parse_day(maintenance.get("scanDate"))
    stations,streams=catalogue_rows(raw,expected)
    doc=json.loads(raw)
    by_id={s["go_station_id"]:s for s in doc["stations"]}
    owners,_,_=index_catalog(doc)
    occupied={u for u,_ in streams.values()}
    occupied.update(u for s in doc["stations"] for v in s["streams"] for u in v.get("previous_urls",[]))
    if (type(limit) is not int or not 0<=limit<=MAX_SEARCH
            or maintenance.get("schemaVersion")!=1 or maintenance.get("catalogBaselineSha256")!=expected
            or maintenance.get("publicationAllowed") is not False or maintenance.get("approvedCount")!=0
            or discovery.get("schemaVersion")!=1 or discovery.get("publicationAllowed") is not False
            or discovery.get("scanDate")!=day or not isinstance(discovery.get("candidates"),list)
            or len(discovery["candidates"])>20000 or not isinstance(maintenance.get("records"),list)):
        raise ValueError("invalid repair input")
    eligible=set()
    seen=set()
    for row in maintenance["records"]:
        sid=row.get("goStationId")
        if (sid not in stations or sid in seen or row.get("catalogueStatus")!=stations[sid]
                or row.get("approved") is not False or row.get("publicationAllowed") is not False):
            raise ValueError("invalid maintenance row")
        seen.add(sid)
        if row.get("reviewStatus") in ELIGIBLE and row.get("positiveStreamCount")==0:
            eligible.add(sid)
    if seen!=set(stations):
        raise ValueError("incomplete maintenance inventory")
    entries={}
    if prior is not None:
        if (prior.get("schemaVersion")!=1 or prior.get("catalogBaselineSha256")!=expected
                or prior.get("publicationAllowed") is not False or prior.get("approvedCount")!=0
                or parse_day(prior["scanDate"])>day or not isinstance(prior.get("records"),list)):
            raise ValueError("invalid repair register")
        for row in prior["records"]:
            sid=row.get("goStationId")
            if (sid not in stations or sid in entries or row.get("approved") is not False
                    or row.get("publicationAllowed") is not False or row.get("searchStatus") not in STATUSES
                    or parse_day(row["lastAttemptDate"])>day or not isinstance(row.get("hints"),list)
                    or len(row["hints"])>MAX_HINTS):
                raise ValueError("invalid repair row")
            for h in row["hints"]:
                validate_hint(h)
            checked=row.get("hintsObservedDate")
            if checked is not None and parse_day(checked)>row["lastAttemptDate"]:
                raise ValueError("future hint")
            if row["hints"] and checked is None:
                raise ValueError("undated hint")
            entries[sid]=row
    queue=sorted((sid for sid in eligible if entries.get(sid,{}).get("lastAttemptDate")!=day),
                 key=lambda sid:(entries.get(sid,{}).get("lastAttemptDate",""),sid))
    if limit and queue and search is None:
        raise ValueError("explicit directory search required")
    attempted=0
    service_failures=0
    for sid in queue[:limit]:
        station=by_id[sid]
        old=entries.get(sid,{})
        attempted+=1
        try:
            rows=search(station["display_name"])
            if not isinstance(rows,list) or len(rows)>PAGE_SIZE or any(not isinstance(x,dict) for x in rows):
                raise ValueError("invalid directory response")
        except (OSError,ValueError,RuntimeError):
            service_failures+=1
            entries[sid]={"goStationId":sid,"lastAttemptDate":day,"searchStatus":"service_held",
                          "hintsObservedDate":old.get("hintsObservedDate"),"hints":old.get("hints",[]),
                          "approved":False,"publicationAllowed":False}
            break
        # A full page is not exhaustive. Retain any actual hints but mark the search incomplete.
        hints={}
        for row in rows+discovery["candidates"]:
            hint=match(station,row,owners,occupied)
            if hint:
                hints[(hint["stationuuid"],hint["streamSha256"])]=hint
        ordered=[hints[k] for k in sorted(hints)]
        status=("incomplete_search" if len(rows)==PAGE_SIZE or len(ordered)>MAX_HINTS else
                "candidates_observed" if ordered else "no_candidate_observed")
        entries[sid]={"goStationId":sid,"lastAttemptDate":day,"searchStatus":status,
                      "hintsObservedDate":day,"hints":ordered[:MAX_HINTS],
                      "approved":False,"publicationAllowed":False}
    records=[]
    for sid,row in sorted(entries.items()):
        # Keep search history but never present stale evidence as current.
        hdate=row.get("hintsObservedDate")
        records.append(dict(row,maintenanceEligible=sid in eligible,
                            hintsFresh=bool(hdate and age(day,hdate)<7)))
    return {"schemaVersion":1,"scanDate":day,"catalogBaselineSha256":expected,
            "approvedCount":0,"publicationAllowed":False,"eligibleStationCount":len(eligible),
            "dueStationCount":len(queue),"attemptedCount":attempted,"serviceFailureCount":service_failures,
            "stationsWithFreshHints":sum(bool(r["hints"] and r["hintsFresh"] and r["maintenanceEligible"]) for r in records),
            "counts":dict(sorted(Counter(r["searchStatus"] for r in records).items())),"records":records}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("baseline","maintenance","discovery","output"):
        p.add_argument("--"+name,type=Path,required=True)
    p.add_argument("--previous",type=Path)
    p.add_argument("--limit",type=int,default=0)
    p.add_argument("--allow-network",action="store_true")
    a=p.parse_args()
    if a.limit and not a.allow_network:
        p.error("network must be explicit")
    def load(path):
        if path.stat().st_size>MAX_BYTES:
            raise ValueError("oversize repair input")
        return path.read_bytes()
    hosts=None
    def search(name):
        nonlocal hosts
        if hosts is None:
            hosts=resolve_api_mirrors()[:2]
        return fetch_page(hosts,"name",name,0,PAGE_SIZE)
    result=build(load(a.baseline),json.loads(load(a.maintenance)),json.loads(load(a.discovery)),
                 prior=json.loads(load(a.previous)) if a.previous else None,limit=a.limit,
                 search=search if a.limit else None)
    payload=json.dumps(result,ensure_ascii=False,indent=2)+"\n"
    if len(payload.encode())>MAX_BYTES:
        raise ValueError("oversize repair output")
    a.output.write_text(payload,encoding="utf-8")
    print("RADIO_REPAIR_PREVIEW_ONLY",{k:v for k,v in result.items() if k!="records"})

if __name__=="__main__":
    main()
