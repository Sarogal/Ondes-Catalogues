#!/usr/bin/env python3
"""Read-only maintenance of every stream in the pinned TEST catalogue.

A byte sample is not a liveness certificate. Quarantine/restoration are review
hints only. No URL, audio, catalogue mutation or publication is emitted.
"""
import argparse
import datetime as dt
import hashlib
import json
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from radio_daily_v9_generator import BASELINE
from radio_daily_qualification_dossiers import MAX_BYTES
from radio_stream_technical_probe import probe_url, PinnedHttpTransport
from radio_stream_recheck_ledger import parse_day

MAX_PROBES=20
MAX_WORKERS=4
HISTORY_DAYS=30
RECENT_DAYS=7
FAILURE_DAYS=3
STATES={"active","quarantined"}
OUTCOMES={"audio_hint","unavailable_hint","inconclusive"}
IDENT=re.compile(r"[a-zA-Z0-9_-]{1,100}")

def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()

def age(day,value):
    return (dt.date.fromisoformat(day)-dt.date.fromisoformat(parse_day(value))).days

def catalogue_rows(raw,expected):
    if hashlib.sha256(raw).hexdigest()!=expected:
        raise ValueError("maintenance baseline mismatch")
    doc=json.loads(raw)
    if doc.get("release_sequence")!=8 or not isinstance(doc.get("stations"),list):
        raise ValueError("unexpected baseline")
    stations={}
    streams={}
    for s in doc["stations"]:
        sid=s.get("go_station_id")
        status=s.get("status",{}).get("state")
        if not isinstance(sid,str) or not IDENT.fullmatch(sid) or sid in stations or status not in STATES:
            raise ValueError("invalid station identity")
        stations[sid]=status
        variants=s.get("streams")
        if not isinstance(variants,list) or not variants or len(variants)>100:
            raise ValueError("invalid station streams")
        for v in variants:
            vid=v.get("stream_id")
            url=v.get("url")
            if not isinstance(vid,str) or not IDENT.fullmatch(vid) or not isinstance(url,str) or not url:
                raise ValueError("invalid stream identity")
            k=(sid,vid)
            if k in streams:
                raise ValueError("duplicate stream identity")
            streams[k]=(url,digest(url))
    return stations,streams

def outcome(sample,sha):
    if sample.get("streamSha256")!=sha:
        raise ValueError("probe fingerprint mismatch")
    if sample.get("verdict")=="audio_sample_ok" and sample.get("frameChain"):
        return "audio_hint"
    if sample.get("verdict")=="needs_review" and sample.get("reason") in (
            "http_not_successful","connection_or_protocol_error"):
        return "unavailable_hint"
    return "inconclusive"

def build(raw,day,*,expected=BASELINE,prior=None,limit=0,workers=1,probe=None):
    day=parse_day(day)
    if type(limit) is not int or not 0<=limit<=MAX_PROBES or type(workers) is not int or not 1<=workers<=MAX_WORKERS:
        raise ValueError("invalid maintenance budget")
    stations,streams=catalogue_rows(raw,expected)
    history={k:[] for k in streams}
    if prior is not None:
        if (prior.get("schemaVersion")!=1 or prior.get("publicationAllowed") is not False
                or prior.get("approvedCount")!=0 or parse_day(prior["scanDate"])>day
                or not isinstance(prior.get("streams"),list)):
            raise ValueError("invalid maintenance register")
        if prior.get("catalogBaselineSha256")!=expected:
            raise ValueError("maintenance register baseline mismatch")
        seen=set()
        for row in prior["streams"]:
            k=(row.get("goStationId"),row.get("streamId"))
            if (k in seen or k not in streams or row.get("streamSha256")!=streams[k][1]
                    or row.get("publicationAllowed") is not False or not isinstance(row.get("observations"),list)
                    or len(row["observations"])>HISTORY_DAYS):
                raise ValueError("invalid maintenance stream")
            seen.add(k)
            ds=[]
            for h in row["observations"]:
                date=parse_day(h["date"])
                if h.get("outcome") not in OUTCOMES or date>day:
                    raise ValueError("invalid maintenance observation")
                ds.append(date)
                if age(day,date)<HISTORY_DAYS:
                    history[k].append({"date":date,"outcome":h["outcome"]})
            if ds!=sorted(set(ds)):
                raise ValueError("duplicate or unordered observation")
    eligible=[k for k,h in history.items() if not h or h[-1]["date"]!=day]
    def order(k):
        return (history[k][-1]["date"] if history[k] else "",k)
    eligible.sort(key=order)
    retry=[k for k in eligible if history[k] and history[k][-1]["outcome"]=="unavailable_hint"]
    quarantine=[k for k in eligible if stations[k[0]]=="quarantined"]
    # Reserve up to one quarter each for failures and existing quarantine;
    # the remaining half rotates oldest/unseen endpoints fairly.
    selected=[]
    for lane in (retry,quarantine):
        selected.extend([k for k in lane if k not in selected][:limit//4])
    selected.extend([k for k in eligible if k not in selected][:limit-len(selected)])
    if selected and probe is None:
        raise ValueError("explicit probe required")
    def check(k):
        url,sha=streams[k]
        return k,outcome(probe(url),sha)
    if workers==1:
        checked=list(map(check,selected))
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            checked=list(pool.map(check,selected))
    for k,v in checked:
        history[k].append({"date":day,"outcome":v})
    rows=[]
    station_rows=[]
    for k,h in sorted(history.items()):
        rows.append({"goStationId":k[0],"streamId":k[1],"streamSha256":streams[k][1],
                     "observations":h,"publicationAllowed":False})
    by_station={sid:[] for sid in stations}
    for k,h in history.items():
        by_station[k[0]].append(h)
    for sid,status in sorted(stations.items()):
        hs=by_station[sid]
        recent=[h for h in hs if h and age(day,h[-1]["date"])<=RECENT_DAYS]
        positives=sum(h[-1]["outcome"]=="audio_hint" for h in recent)
        def repeated_failure(h):
            streak=[]
            for o in reversed(h):
                if o["outcome"]!="unavailable_hint" or age(day,o["date"])>RECENT_DAYS:
                    break
                streak.append(o["date"])
            return len(streak)>=FAILURE_DAYS
        repeated=sum(repeated_failure(h) for h in recent)
        if status=="quarantined" and positives:
            verdict="restoration_probe_review"
        elif status=="active" and repeated==len(hs):
            verdict="quarantine_review"
        elif positives:
            verdict="audio_sample_observed"
        elif any(h[-1]["outcome"]=="unavailable_hint" for h in recent):
            verdict="availability_recheck"
        elif recent:
            verdict="inconclusive"
        else:
            verdict="awaiting_probe"
        station_rows.append({"goStationId":sid,"catalogueStatus":status,"streamCount":len(hs),
                             "recentStreamCount":len(recent),"positiveStreamCount":positives,
                             "repeatedFailureStreamCount":repeated,"reviewStatus":verdict,
                             "approved":False,"publicationAllowed":False})
    return {"schemaVersion":1,"scanDate":day,"catalogBaselineSha256":expected,
            "publicationAllowed":False,"approvedCount":0,"stationCount":len(stations),
            "streamCount":len(streams),"checkedCount":len(checked),
            "everObservedStreamCount":sum(bool(h) for h in history.values()),
            "sampleCounts":dict(sorted(Counter(v for _,v in checked).items())),
            "reviewCounts":dict(sorted(Counter(r["reviewStatus"] for r in station_rows).items())),
            "streams":rows,"records":station_rows}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--baseline",type=Path,required=True)
    p.add_argument("--previous",type=Path)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--limit",type=int,default=0)
    p.add_argument("--workers",type=int,default=1)
    p.add_argument("--allow-network",action="store_true")
    a=p.parse_args()
    if a.limit and not a.allow_network:
        p.error("explicit network opt-in required")
    def read(path):
        if path.stat().st_size>MAX_BYTES:
            raise ValueError("oversize maintenance input")
        return path.read_bytes()
    transport=PinnedHttpTransport() if a.limit else None
    probe=(lambda u:probe_url(u,transport.request)) if transport else None
    report=build(read(a.baseline),dt.datetime.now(dt.timezone.utc).date().isoformat(),
                 prior=json.loads(read(a.previous)) if a.previous else None,
                 limit=a.limit,workers=a.workers,probe=probe)
    payload=json.dumps(report,ensure_ascii=False,indent=2)+"\n"
    if len(payload.encode())>MAX_BYTES:
        raise ValueError("oversize maintenance report")
    a.output.write_text(payload,encoding="utf-8")
    print("RADIO_MAINTENANCE_PREVIEW_ONLY",{k:v for k,v in report.items() if k not in ("records","streams")})

if __name__=="__main__":
    main()
