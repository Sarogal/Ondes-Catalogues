#!/usr/bin/env python3
"""Read-only status transition proposals for the pinned TEST catalogue.

Existing-stream recovery requires fresh, repeated continuity on the same
fingerprint. Quarantine requires independent days for every variant and must
not invalidate a historical redirect. No status is actually changed.
"""
import argparse
import hashlib
import http.client
import json
from collections import Counter
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from radio_daily_v9_generator import BASELINE, encode
from radio_daily_baseline_verify import strict_json, validate_shape
from radio_daily_maintenance_preview import build as maintenance_build, catalogue_rows, age
from radio_daily_continuity_preview import observe_url
from radio_daily_hls_preview import observe as observe_hls
from radio_daily_qualification_dossiers import MAX_BYTES
from radio_stream_recheck_ledger import parse_day

MAX_CHECKS=4
MAX_PROPOSALS=3
POSITIVE={"continuous_icy_frame_indication","advancing_hls_audio_frame_indication"}
OUTCOMES=POSITIVE|{"inconclusive"}

def build(raw,maintenance,repair_plan,*,expected=BASELINE,prior=None,limit=0,icy=None,hls=None):
    day=parse_day(maintenance.get("scanDate"))
    stations,streams=catalogue_rows(raw,expected)
    doc=strict_json(raw)
    validate_shape(doc)
    if type(limit) is not int or not 0<=limit<=MAX_CHECKS:
        raise ValueError("invalid status budget")
    m=maintenance_build(raw,day,expected=expected,prior=maintenance)
    if (m["records"]!=maintenance.get("records") or m["streams"]!=maintenance.get("streams")
            or maintenance.get("scanDate")!=day):
        raise ValueError("maintenance derived state mismatch")
    if (repair_plan.get("schemaVersion")!=1 or repair_plan.get("scanDate")!=day
            or repair_plan.get("catalogBaselineSha256")!=expected or repair_plan.get("publicationAllowed") is not False
            or repair_plan.get("approvedCount")!=0 or repair_plan.get("signed") is not False
            or repair_plan.get("candidateCatalogueWritten") is not False
            or not isinstance(repair_plan.get("proposals"),list)):
        raise ValueError("invalid repair plan")
    replacement=set()
    for row in repair_plan["proposals"]:
        sid=row.get("goStationId")
        if sid not in stations or row.get("approved") is not False or row.get("publicationAllowed") is not False:
            raise ValueError("invalid replacement proposal")
        replacement.add(sid)
    evidence={(x["goStationId"],x["streamId"]):x["observations"] for x in m["streams"]}
    histories={k:[] for k in streams if stations[k[0]]=="quarantined"}
    if prior is not None:
        if (prior.get("schemaVersion")!=1 or prior.get("catalogBaselineSha256")!=expected
                or prior.get("publicationAllowed") is not False or prior.get("approvedCount")!=0
                or parse_day(prior["scanDate"])>day or not isinstance(prior.get("streams"),list)):
            raise ValueError("invalid recovery register")
        seen=set()
        for row in prior["streams"]:
            k=(row.get("goStationId"),row.get("streamId"))
            if (k not in histories or k in seen or row.get("streamSha256")!=streams[k][1]
                    or row.get("publicationAllowed") is not False or not isinstance(row.get("observations"),list)
                    or len(row["observations"])>30):
                raise ValueError("invalid recovery stream")
            seen.add(k)
            dates=[]
            for o in row["observations"]:
                date=parse_day(o["date"])
                v=o.get("verdict")
                if date>day or v not in OUTCOMES or o.get("route") not in ("direct","hls"):
                    raise ValueError("invalid recovery observation")
                if v in POSITIVE and ((o["route"]=="hls")!=(v=="advancing_hls_audio_frame_indication")):
                    raise ValueError("invalid recovery route")
                dates.append(date)
                if age(day,date)<30:
                    histories[k].append({"date":date,"verdict":v,"route":o["route"]})
            if dates!=sorted(set(dates)):
                raise ValueError("invalid recovery dates")
    queue=[]
    for k,h in histories.items():
        samples=evidence[k]
        if (samples and samples[-1]["outcome"]=="audio_hint" and age(day,samples[-1]["date"])<=7
                and (not h or h[-1]["date"]!=day)):
            queue.append(k)
    queue.sort(key=lambda k:(histories[k][-1]["date"] if histories[k] else "",k))
    if limit and queue and (icy is None or hls is None):
        raise ValueError("explicit recovery services required")
    def check(k):
        route="hls" if evidence[k][-1].get("route")=="hls" else "direct"
        try:
            result=(hls if route=="hls" else icy)(streams[k][0])
            verdict=result.get("verdict")
            if route=="hls":
                verdict=verdict if verdict=="advancing_hls_audio_frame_indication" and result.get("frameCodec") else "inconclusive"
            else:
                verdict=verdict if verdict=="continuous_icy_frame_indication" else "inconclusive"
        except (OSError,ValueError,http.client.HTTPException):
            verdict="inconclusive"
        return k,{"date":day,"verdict":verdict,"route":route}
    selected=queue[:limit]
    if selected:
        with ThreadPoolExecutor(max_workers=2) as pool:
            for k,o in pool.map(check,selected):
                histories[k].append(o)
    redirects={t.get("redirect_to") for t in doc["tombstones"] if t.get("redirect_to")}
    by_id={s["go_station_id"]:s for s in doc["stations"]}
    output=[]
    candidates=[]
    for row in m["records"]:
        sid=row["goStationId"]
        own=[k for k in streams if k[0]==sid]
        decision="no_transition"
        proof=[]
        if stations[sid]=="quarantined":
            for k in own:
                good=[]
                for o in reversed(histories[k]):
                    if o["verdict"] not in POSITIVE or age(day,o["date"])>7:
                        break
                    good.append(o["date"])
                samples=evidence[k]
                # A later negative or inconclusive sample supersedes the recovery evidence.
                if (len(good)>=2 and day in good and samples and samples[-1]["outcome"]=="audio_hint"
                        and age(day,samples[-1]["date"])<=7):
                    proof.append({"streamId":k[1],"streamSha256":streams[k][1],"positiveDates":sorted(good)})
            if proof:
                decision="restore_existing_stream_review"
            elif row["positiveStreamCount"]:
                decision="await_repeated_continuity"
        elif row["reviewStatus"]=="quarantine_review":
            if sid in redirects:
                decision="redirect_target_held"
            elif sid in replacement:
                decision="replacement_available_review"
            elif all(evidence[k] and evidence[k][-1]["date"]==day for k in own):
                decision="quarantine_transition_review"
                for k in own:
                    dates=[]
                    for o in reversed(evidence[k]):
                        if o["outcome"]!="unavailable_hint" or age(day,o["date"])>7:
                            break
                        dates.append(o["date"])
                    proof.append({"streamId":k[1],"streamSha256":streams[k][1],"negativeDates":sorted(dates)})
            else:
                decision="refresh_all_variants"
        record={"goStationId":sid,"catalogueStatus":stations[sid],"decision":decision,"proof":proof,
                "stationSha256":hashlib.sha256(encode(by_id[sid])).hexdigest(),"approved":False,"publicationAllowed":False}
        output.append(record)
        if decision in ("restore_existing_stream_review","quarantine_transition_review"):
            candidates.append(record)
    # Hold mass transitions. Separate, bounded release review is required.
    proposals=[]
    if len(candidates)<=MAX_PROPOSALS:
        for row in candidates:
            proposals.append({"goStationId":row["goStationId"],"from":row["catalogueStatus"],
                              "to":"active" if row["decision"]=="restore_existing_stream_review" else "quarantined",
                              "stationSha256":row["stationSha256"],"approved":False,"publicationAllowed":False})
    return {"schemaVersion":1,"scanDate":day,"catalogBaselineSha256":expected,"approvedCount":0,
            "publicationAllowed":False,"candidateCatalogueWritten":False,"attemptedCount":len(selected),
            "massTransitionHeld":len(candidates)>MAX_PROPOSALS,"proposalCount":len(proposals),
            "counts":dict(sorted(Counter(x["decision"] for x in output).items())),
            "proposals":proposals,"records":output,
            "streams":[{"goStationId":k[0],"streamId":k[1],"streamSha256":streams[k][1],
                        "observations":h,"publicationAllowed":False} for k,h in sorted(histories.items())]}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("baseline","maintenance","repair-plan","output"):
        p.add_argument("--"+name,required=True,type=Path)
    p.add_argument("--previous",type=Path)
    p.add_argument("--limit",type=int,default=0)
    p.add_argument("--allow-network",action="store_true")
    p.add_argument("--baseline-sha256",default=BASELINE)
    a=p.parse_args()
    if a.limit and not a.allow_network:
        p.error("network must be explicit")
    def read(path):
        if path.stat().st_size>MAX_BYTES:
            raise ValueError("oversize status input")
        return path.read_bytes()
    report=build(read(a.baseline),strict_json(read(a.maintenance)),strict_json(read(a.repair_plan)),
                 expected=a.baseline_sha256,prior=strict_json(read(a.previous)) if a.previous else None,
                 limit=a.limit,icy=observe_url,hls=observe_hls)
    payload=encode(report)
    if len(payload)>MAX_BYTES:
        raise ValueError("oversize status output")
    a.output.write_bytes(payload)
    print("RADIO_STATUS_TRANSITION_PREVIEW_ONLY",{k:v for k,v in report.items() if k not in ("records","streams","proposals")})

if __name__=="__main__":
    main()
