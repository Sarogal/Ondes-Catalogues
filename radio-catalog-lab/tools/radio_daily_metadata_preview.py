#!/usr/bin/env python3
"""Accumulate bounded ICY artist hints by exact stream, never admit stations."""
import argparse
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from radio_daily_continuity_preview import observe_url
from radio_daily_qualification_dossiers import index, safe_digest
from radio_stream_recheck_ledger import parse_day, SHA256_RE
from radio_stream_technical_probe import validate_endpoint

MAX_STATIONS = 6
MAX_INPUT = 12 * 1024 * 1024
MAX_HINTS = 90

def valid_hint(h):
    return (isinstance(h,dict) and isinstance(h.get("artistHint"),str)
            and 2 <= len(h["artistHint"]) <= 100
            and not any(ord(c)<32 for c in h["artistHint"])
            and not re.search(r"https?://|www\.|@|[?=]",h["artistHint"],re.I)
            and isinstance(h.get("titleSha256"),str) and SHA256_RE.fullmatch(h["titleSha256"]))

def select_queue(queue, retained, limit):
    """Reserve capacity for advanced, old and new streams; no UUID starvation."""
    if not limit:
        return []
    def order(item):
        _, _, uid, _, _ = item
        return (retained.get(uid, {}).get("observedDate", ""), uid)
    advanced = sorted((x for x in queue if not x[0]), key=order)
    old = sorted((x for x in queue if x[1]), key=order)
    new = sorted((x for x in queue if not x[1]), key=order)
    selected, used = [], set()
    for _ in range(limit):
        for lane in (advanced, old, new):
            if len(selected) >= limit:
                break
            while lane and lane[0][2] in used:
                lane.pop(0)
            if lane:
                item = lane.pop(0)
                selected.append(item)
                used.add(item[2])
    return selected

def collect(discovery, reconciliation, continuity, decisions, *, previous=None, limit=0, observe=None):
    if observe is None:
        observe=lambda url: observe_url(url, metadata=True)
    day=parse_day(discovery["scanDate"])
    if not 0 <= limit <= MAX_STATIONS:
        raise ValueError("metadata budget")
    for report in (discovery,continuity,decisions):
        if report.get("schemaVersion")!=1 or report.get("publicationAllowed") is not False or report.get("scanDate")!=day:
            raise ValueError("metadata input")
    if (reconciliation.get("schemaVersion")!=1 or reconciliation.get("scanDate")!=day
            or reconciliation.get("automaticAdmissionAllowed") is not False or reconciliation.get("catalogChanged") is not False
            or continuity.get("technicallyQualifiedCount")!=0 or decisions.get("approvedCount")!=0):
        raise ValueError("untrusted input")
    current,rec=index(discovery,"candidates"),index(reconciliation,"candidates")
    cont,dec=index(continuity,"records"),index(decisions,"records")
    if set(current)!=set(rec):
        raise ValueError("candidate mismatch")
    old={}
    if previous is not None:
        if (previous.get("schemaVersion")!=1 or previous.get("publicationAllowed") is not False
                or previous.get("approvedCount")!=0 or parse_day(previous["scanDate"])>day):
            raise ValueError("prior metadata input")
        old=index(previous,"records")
        for row in old.values():
            if (row.get("publicationAllowed") is not False or row.get("approved") is not False
                    or not SHA256_RE.fullmatch(row.get("streamSha256") or "")
                    or parse_day(row["observedDate"])>day
                    or not isinstance(row.get("observations"),list) or len(row["observations"])>MAX_HINTS
                    or any(not valid_hint(h) or parse_day(h["date"])>day for h in row["observations"])):
                raise ValueError("prior metadata row")
    retained={uid:dict(row,observedInScan=False) for uid,row in old.items() if uid not in current}
    queue=[]
    for uid,source in sorted(current.items()):
        url=source.get("streamUrl")
        sha=safe_digest(url)
        if rec[uid]["classification"]!="unmapped_candidate" or not sha:
            continue
        prior=old.get(uid)
        if prior and prior["streamSha256"]==sha:
            retained[uid]=dict(prior,observedInScan=True)
            if prior["observedDate"]==day:
                continue
        c,d=cont.get(uid,{}),dec.get(uid,{})
        if (c.get("streamSha256")!=sha or c.get("verdict")!="continuous_icy_frame_indication"
                or c.get("technicalQualified") is not False or c.get("publicationAllowed") is not False
                or d.get("streamSha256")!=sha or d.get("approved") is not False
                or d.get("publicationAllowed") is not False or d.get("decision") not in
                ("advanced_candidate","editorial_review","technical_review","ready_for_staging_review")):
            continue
        try:
            validate_endpoint(url)
        except ValueError:
            continue
        queue.append((d["decision"]!="advanced_candidate",uid in retained,uid,url,sha))
    selected=select_queue(queue, retained, limit)
    def check(item):
        _,_,uid,url,sha=item
        try:
            evidence=observe(url)
        except Exception:
            evidence={"verdict":"metadata_connection_review","titleHints":[]}
        prior=retained.get(uid,{})
        hints=[dict(h) for h in prior.get("observations",[]) if prior.get("streamSha256")==sha]
        for h in evidence.get("titleHints",[])[:3]:
            if valid_hint(h):
                observation={"date":day,"artistHint":h["artistHint"],"titleSha256":h["titleSha256"]}
                if observation not in hints:
                    hints.append(observation)
        hints=sorted(hints,key=lambda x:(x["date"],x["artistHint"],x["titleSha256"]))[-MAX_HINTS:]
        verdict=evidence.get("verdict")
        if verdict not in {"icy_artist_title_hint","metadata_not_advertised","metadata_interval_out_of_budget",
                           "metadata_no_parseable_title","metadata_non_live_response","metadata_connection_review",
                           "playlist_requires_separate_validation"}:
            verdict="metadata_connection_review"
        return uid,{"stationuuid":uid,"streamSha256":sha,"observedDate":day,"observedInScan":True,
                    "approved":False,"publicationAllowed":False,"verdict":verdict,"observations":hints}
    with ThreadPoolExecutor(max_workers=2) as pool:
        for uid,row in pool.map(check,selected):
            retained[uid]=row
    records=[retained[k] for k in sorted(retained)]
    return {"schemaVersion":1,"scanDate":day,"publicationAllowed":False,"approvedCount":0,
            "attemptedCount":len(selected),"stationsWithArtistHints":sum(bool(r["observations"]) for r in records),
            "distinctArtistHints":len({h["artistHint"].casefold() for r in records for h in r["observations"]}),
            "records":records}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ("discovery","reconciliation","continuity","decisions","output"):
        p.add_argument("--"+k,type=Path,required=True)
    p.add_argument("--previous",type=Path)
    p.add_argument("--limit",type=int,default=0)
    p.add_argument("--allow-network",action="store_true")
    a=p.parse_args()
    if a.limit and not a.allow_network:
        p.error("network must be explicit")
    def load(path):
        if path.stat().st_size>MAX_INPUT:
            raise ValueError("oversized metadata input")
        return json.loads(path.read_text())
    report=collect(*(load(getattr(a,k)) for k in ("discovery","reconciliation","continuity","decisions")),
                   previous=load(a.previous) if a.previous else None,limit=a.limit)
    payload=json.dumps(report,ensure_ascii=False,indent=2)+"\n"
    if len(payload.encode())>MAX_INPUT:
        raise ValueError("oversized metadata report")
    a.output.write_text(payload,encoding="utf-8")
    print("RADIO_ICY_METADATA_PREVIEW_ONLY",{k:v for k,v in report.items() if k!="records"})

if __name__=="__main__":
    main()
