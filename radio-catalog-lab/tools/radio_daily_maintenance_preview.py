#!/usr/bin/env python3
"""Read-only maintenance of every stream in the pinned TEST catalogue.

A byte sample is not a liveness certificate. Quarantine/restoration are review
hints only. No URL, audio, catalogue mutation or publication is emitted.
"""
import argparse
import datetime as dt
import hashlib
import http.client
import json
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from radio_daily_v9_generator import BASELINE
from radio_daily_qualification_dossiers import MAX_BYTES
from radio_stream_technical_probe import probe_url, PinnedHttpTransport
from radio_stream_recheck_ledger import parse_day
from radio_daily_hls_preview import observe as observe_hls

MAX_PROBES=20
MAX_WORKERS=4
MAX_HLS=4
ROUTES={"direct","hls","playlist_deferred"}
HLS_VERDICTS={"advancing_hls_audio_frame_indication","advancing_hls_manifest_only",
              "ordinary_playlist","unsupported_hls_features","finite_hls_review",
              "long_target_duration_review","changed_or_finite_manifest_review",
              "manifest_not_advanced","manifest_or_connection_review"}
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
    sequence=doc.get("release_sequence")
    if (type(sequence) is not int or sequence<8 or (expected==BASELINE and sequence!=8)
            or not isinstance(doc.get("stations"),list)):
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

def build(raw,day,*,expected=BASELINE,prior=None,limit=0,workers=1,probe=None,hls_probe=None):
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
                route=h.get("route","direct")
                hv=h.get("hlsVerdict")
                if (route not in ROUTES or (route=="hls" and hv not in HLS_VERDICTS)
                        or (route!="hls" and hv is not None)
                        or (route=="playlist_deferred" and h["outcome"]!="inconclusive")
                        or (route=="hls" and h["outcome"]!=(
                            "audio_hint" if hv=="advancing_hls_audio_frame_indication" else "inconclusive"))):
                    raise ValueError("invalid maintenance route")
                if age(day,date)<HISTORY_DAYS:
                    observation={"date":date,"outcome":h["outcome"],"route":route}
                    if hv is not None:
                        observation["hlsVerdict"]=hv
                    history[k].append(observation)
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
        sample=probe(url)
        result=outcome(sample,sha)
        pending=sample.get("verdict")=="playlist_pending"
        return k,{"date":day,"outcome":result,
                  "route":"playlist_deferred" if pending else "direct"}
    if workers==1:
        checked=dict(map(check,selected))
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            checked=dict(pool.map(check,selected))
    def hls_order(k):
        dates=[h["date"] for h in history[k] if h.get("route")=="hls"]
        return (dates[-1] if dates else "",k)
    pending=sorted((k for k,v in checked.items() if v["route"]=="playlist_deferred"),key=hls_order)
    hls_selected=pending[:MAX_HLS] if hls_probe is not None else []
    def check_hls(k):
        try:
            result=hls_probe(streams[k][0])
            verdict=result.get("verdict")
            if verdict not in HLS_VERDICTS:
                verdict="manifest_or_connection_review"
            if verdict=="advancing_hls_audio_frame_indication" and not result.get("frameCodec"):
                verdict="manifest_or_connection_review"
        except (OSError,ValueError,http.client.HTTPException,UnicodeError):
            verdict="manifest_or_connection_review"
        return k,{"date":day,"route":"hls","hlsVerdict":verdict,
                  "outcome":"audio_hint" if verdict=="advancing_hls_audio_frame_indication" else "inconclusive"}
    if hls_selected:
        with ThreadPoolExecutor(max_workers=min(2,workers)) as pool:
            checked.update(pool.map(check_hls,hls_selected))
    for k,v in checked.items():
        history[k].append(v)
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
            "sampleCounts":dict(sorted(Counter(v["outcome"] for v in checked.values()).items())),
            "hlsAttemptedCount":len(hls_selected),"hlsDeferredCount":len(pending)-len(hls_selected),
            "hlsVerdictCounts":dict(sorted(Counter(v["hlsVerdict"] for v in checked.values() if v["route"]=="hls").items())),
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
                 limit=a.limit,workers=a.workers,probe=probe,
                 hls_probe=observe_hls if a.limit else None)
    payload=json.dumps(report,ensure_ascii=False,indent=2)+"\n"
    if len(payload.encode())>MAX_BYTES:
        raise ValueError("oversize maintenance report")
    a.output.write_text(payload,encoding="utf-8")
    print("RADIO_MAINTENANCE_PREVIEW_ONLY",{k:v for k,v in report.items() if k not in ("records","streams")})

if __name__=="__main__":
    main()
