#!/usr/bin/env python3
"""Confirm directory replacement hints against the pinned broadcaster page.

Review only: rehydrate raw addresses in memory, match the stored digest,
require station-bound declarations, and retain dated technical hints.
"""
import argparse
import hashlib
import json
import http.client
from collections import Counter
from pathlib import Path
from urllib.parse import urljoin

from radio_daily_repair_preview import match, validate_hint, name_key, page_key, PAGE_SIZE, MAX_HINTS
from radio_daily_maintenance_preview import catalogue_rows, digest, age, outcome
from radio_daily_v9_generator import BASELINE
from radio_daily_qualification_dossiers import MAX_BYTES
from radio_catalog_daily_candidate_reconcile import index_catalog
from radio_daily_editorial_preview import Page, station_nodes, homepage_url, fetch_html, related_host
from radio_daily_discovery import fetch_page, resolve_api_mirrors
from radio_stream_technical_probe import PinnedHttpTransport, probe_url
from radio_stream_recheck_ledger import parse_day, SHA256_RE

MAX_CHECKS=4
STATUSES={"directory_held","directory_changed","broadcaster_held","broadcaster_unlinked",
          "audio_hint","unavailable_hint","inconclusive"}
POSITIVE={"audio_hint"}
DECLARATIONS={"typed_station","unique_named_player"}

def declaration(station, final, body, url):
    p=Page()
    p.feed(body.decode("utf-8",errors="replace"))
    name=name_key(station["display_name"])
    nodes=list(station_nodes(p.structured))
    typed=set()
    for node in nodes:
        if name_key(node.get("name"))==name:
            for field in ("contentUrl","streamUrl"):
                if isinstance(node.get(field),str):
                    typed.add(urljoin(final,node[field]))
    if url in typed:
        return "typed_station"
    # A generic brand page or a page with multiple players is not enough.
    players={urljoin(final,v) for v in p.audio_urls}
    if (not nodes and len(name)>=5 and name not in {"radio","metal","punk","hard rock"}
            and any(name_key(v)==name for v in p.identity) and players=={url}):
        return "unique_named_player"
    return None

def build(raw,repair,*,expected=BASELINE,prior=None,limit=0,search=None,fetch=None,probe=None):
    day=parse_day(repair.get("scanDate"))
    stations,streams=catalogue_rows(raw,expected)
    doc=json.loads(raw)
    by_id={s["go_station_id"]:s for s in doc["stations"]}
    owners,_,_=index_catalog(doc)
    occupied={u for u,_ in streams.values()}
    occupied.update(u for s in doc["stations"] for v in s["streams"] for u in v.get("previous_urls",[]))
    if (type(limit) is not int or not 0<=limit<=MAX_CHECKS
            or repair.get("schemaVersion")!=1 or repair.get("catalogBaselineSha256")!=expected
            or repair.get("approvedCount")!=0 or repair.get("publicationAllowed") is not False
            or not isinstance(repair.get("records"),list)):
        raise ValueError("invalid confirmation input")
    candidates={}
    seen=set()
    for row in repair["records"]:
        sid=row.get("goStationId")
        if (sid not in stations or sid in seen or row.get("approved") is not False
                or row.get("publicationAllowed") is not False or not isinstance(row.get("hints"),list)
                or len(row["hints"])>MAX_HINTS):
            raise ValueError("invalid repair row")
        seen.add(sid)
        for h in row["hints"]:
            validate_hint(h)
            observed=parse_day(row["hintsObservedDate"])
            if observed>day:
                raise ValueError("future repair hint")
            if row.get("maintenanceEligible") is True and age(day,observed)<7:
                k=(sid,h["stationuuid"],h["streamSha256"])
                if k in candidates:
                    raise ValueError("duplicate repair candidate")
                candidates[k]=h
    # Same proposed endpoint or UUID claimed by two stations is ambiguous.
    conflicts=set()
    for position in (1,2):
        groups={}
        for k in candidates:
            groups.setdefault(k[position],set()).add(k[0])
        conflicts.update(k for k in candidates if len(groups[k[position]])>1)
    history={k:[] for k in candidates}
    if prior is not None:
        if (prior.get("schemaVersion")!=1 or prior.get("catalogBaselineSha256")!=expected
                or prior.get("approvedCount")!=0 or prior.get("publicationAllowed") is not False
                or parse_day(prior["scanDate"])>day or not isinstance(prior.get("records"),list)):
            raise ValueError("invalid confirmation register")
        seen=set()
        for row in prior["records"]:
            k=(row["goStationId"],row["stationuuid"],row["streamSha256"])
            if k in seen or row.get("approved") is not False or row.get("publicationAllowed") is not False:
                raise ValueError("invalid prior confirmation")
            seen.add(k)
            if not isinstance(row.get("observations"),list) or len(row["observations"])>30:
                raise ValueError("invalid confirmation history")
            dates=[]
            for o in row["observations"]:
                date=parse_day(o["date"])
                status=o.get("status")
                mode=o.get("declaration")
                page=o.get("pageSha256")
                if (date>day or status not in STATUSES or
                        (status in ("audio_hint","unavailable_hint","inconclusive") and
                         (mode not in DECLARATIONS or not SHA256_RE.fullmatch(page or ""))) or
                        (status not in ("audio_hint","unavailable_hint","inconclusive") and (mode is not None or page is not None))):
                    raise ValueError("invalid confirmation observation")
                dates.append(date)
                if k in history and age(day,date)<30:
                    history[k].append({"date":date,"status":status,"declaration":mode,"pageSha256":page})
            if dates!=sorted(set(dates)):
                raise ValueError("duplicate confirmation dates")
    queue=sorted((k for k in candidates if k not in conflicts and
                  (not history[k] or history[k][-1]["date"]!=day)),
                 key=lambda k:(history[k][-1]["date"] if history[k] else "",k))
    if limit and queue and any(x is None for x in (search,fetch,probe)):
        raise ValueError("explicit confirmation services required")
    attempted=0
    def record(k,status,mode=None,page=None):
        history[k].append({"date":day,"status":status,"declaration":mode,"pageSha256":page})
    for k in queue[:limit]:
        sid,uid,sha=k
        station=by_id[sid]
        attempted+=1
        try:
            rows=search(station["display_name"])
            if not isinstance(rows,list) or len(rows)>PAGE_SIZE:
                raise ValueError("invalid directory result")
            urls=set()
            for row in rows:
                h=match(station,row,owners,occupied)
                if h and h["stationuuid"]==uid and h["streamSha256"]==sha:
                    urls.add(row.get("url_resolved") or row.get("url") or row.get("streamUrl"))
        except (ValueError,OSError,RuntimeError,TypeError,AttributeError):
            record(k,"directory_held")
            continue
        if len(urls)!=1:
            record(k,"directory_changed")
            continue
        url=next(iter(urls))
        page=homepage_url(station.get("homepage"))
        try:
            final,body=fetch(page)
            if (not related_host(final,page) or homepage_url(final)!=final
                    or page_key(final)!=page_key(page) or not isinstance(body,bytes) or len(body)>256*1024):
                raise ValueError("unexpected broadcaster response")
            mode=declaration(station,final,body,url)
        except (ValueError,OSError,http.client.HTTPException,TypeError,AttributeError):
            record(k,"broadcaster_held")
            continue
        if not mode:
            record(k,"broadcaster_unlinked")
            continue
        try:
            status=outcome(probe(url),sha)
        except (ValueError,OSError,http.client.HTTPException):
            status="inconclusive"
        record(k,status,mode,hashlib.sha256(body).hexdigest())
    records=[]
    for k,obs in sorted(history.items()):
        recent=[x for x in obs if age(day,x["date"])<=7]
        positives=[]
        for o in reversed(recent):
            if o["status"]!="audio_hint":
                break
            positives.append(o["date"])
        state=("identity_collision_held" if k in conflicts else
               "repeated_audio_review" if len(positives)>=2 and day in positives else
               recent[-1]["status"] if recent else "awaiting_confirmation")
        records.append({"goStationId":k[0],"stationuuid":k[1],"streamSha256":k[2],
                        "observations":obs,"positiveDates":sorted(positives),"reviewStatus":state,
                        "approved":False,"publicationAllowed":False})
    return {"schemaVersion":1,"scanDate":day,"catalogBaselineSha256":expected,
            "approvedCount":0,"publicationAllowed":False,"attemptedCount":attempted,
            "candidateCount":len(candidates),"counts":dict(sorted(Counter(r["reviewStatus"] for r in records).items())),
            "records":records}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("baseline","repair","output"):
        p.add_argument("--"+name,required=True,type=Path)
    p.add_argument("--previous",type=Path)
    p.add_argument("--limit",type=int,default=0)
    p.add_argument("--allow-network",action="store_true")
    a=p.parse_args()
    if a.limit and not a.allow_network:
        p.error("network must be explicit")
    def load(path):
        if path.stat().st_size>MAX_BYTES:
            raise ValueError("oversize confirmation input")
        return path.read_bytes()
    hosts=None
    def search(name):
        nonlocal hosts
        if hosts is None:
            hosts=resolve_api_mirrors()[:2]
        return fetch_page(hosts,"name",name,0,PAGE_SIZE)
    transport=PinnedHttpTransport()
    report=build(load(a.baseline),json.loads(load(a.repair)),
                 prior=json.loads(load(a.previous)) if a.previous else None,
                 limit=a.limit,search=search,fetch=fetch_html,
                 probe=lambda u:probe_url(u,transport.request))
    payload=json.dumps(report,ensure_ascii=False,indent=2)+"\n"
    if len(payload.encode())>MAX_BYTES:
        raise ValueError("oversize confirmation output")
    a.output.write_text(payload,encoding="utf-8")
    print("RADIO_REPAIR_CONFIRMATION_PREVIEW_ONLY",{k:v for k,v in report.items() if k!="records"})

if __name__=="__main__":
    main()
