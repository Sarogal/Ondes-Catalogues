#!/usr/bin/env python3
"""Unsigned maintenance plan, strictly separate from additive discovery v9.

The public workflow emits digest-only proposals, never a changed catalogue.
An explicit in-memory staging helper exercises the preservation contract.
Neither this plan nor its staging helper is a publishing authority.
"""
import argparse
import copy
import hashlib
import json
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

from radio_daily_v9_generator import BASELINE, encode, check_catalog
from radio_daily_baseline_verify import strict_json, validate_shape
from radio_daily_maintenance_preview import build as maintenance_build, catalogue_rows
from radio_daily_repair_confirmation import build as confirmation_build
from radio_daily_repair_preview import ELIGIBLE
from radio_daily_qualification_dossiers import MAX_BYTES
from radio_stream_technical_probe import validate_endpoint
from radio_stream_recheck_ledger import parse_day

def sha(data):
    return hashlib.sha256(data).hexdigest()

def plan(raw,maintenance,repair,confirmation,*,expected=BASELINE):
    day=parse_day(maintenance.get("scanDate"))
    catalogue_rows(raw,expected)
    doc=strict_json(raw)
    validate_shape(doc)
    if any(x.get("scanDate")!=day or x.get("publicationAllowed") is not False
           or x.get("approvedCount")!=0 or x.get("catalogBaselineSha256")!=expected
           for x in (maintenance,repair,confirmation)):
        raise ValueError("incompatible maintenance evidence")
    m=maintenance_build(raw,day,expected=expected,prior=maintenance)
    if m["records"]!=maintenance.get("records") or m["streams"]!=maintenance.get("streams"):
        raise ValueError("maintenance report does not match observation history")
    c=confirmation_build(raw,repair,expected=expected,prior=confirmation)
    if c["records"]!=confirmation.get("records"):
        raise ValueError("confirmation report does not match observation history")
    by_id={s["go_station_id"]:s for s in doc["stations"]}
    health={s["goStationId"]:s for s in m["records"]}
    grouped={}
    for row in c["records"]:
        grouped.setdefault(row["goStationId"],[]).append(row)
    proposals=[]
    deferred=[]
    for sid,rows in sorted(grouped.items()):
        h=health[sid]
        strong=[x for x in rows if x["reviewStatus"]=="repeated_continuity_review"]
        # Multiple plausible replacements require further identity resolution.
        if len(rows)!=1 or len(strong)!=1:
            deferred.append({"goStationId":sid,"reason":"multiple_candidates" if len(rows)>1 else rows[0]["reviewStatus"]})
            continue
        x=strong[0]
        if h["reviewStatus"] not in ELIGIBLE or h["positiveStreamCount"] or h["recentStreamCount"]!=h["streamCount"]:
            deferred.append({"goStationId":sid,"reason":"current_variants_need_recheck"})
            continue
        s=by_id[sid]
        stream_id="repair-"+x["streamSha256"][:24]
        if any(v["stream_id"]==stream_id for v in s["streams"]):
            raise ValueError("replacement stream id collision")
        proposals.append({"goStationId":sid,"stationuuid":x["stationuuid"],
                          "streamSha256":x["streamSha256"],"streamId":stream_id,
                          "operation":"append_candidate_fallback","existingStatus":s["status"]["state"],
                          "priority":max(v["priority"] for v in s["streams"])+1,
                          "continuityDates":x["continuityDates"],"stationSha256":sha(encode(s)),
                          "confirmationSha256":sha(encode(x)),
                          "approved":False,"publicationAllowed":False})
    # These are work items, not permission to change a catalogue status.
    reviews=[{"goStationId":s["goStationId"],"reviewStatus":s["reviewStatus"],
              "approved":False,"publicationAllowed":False} for s in m["records"]
             if s["reviewStatus"] in ("quarantine_review","restoration_probe_review")]
    return {"schemaVersion":1,"scanDate":day,"catalogBaselineSha256":expected,
            "publicationAllowed":False,"approvedCount":0,"signed":False,
            "candidateCatalogueWritten":False,"stationCount":len(by_id),
            "proposals":proposals,"deferred":deferred,"statusReviews":reviews,
            "proposalCount":len(proposals),"deferredCounts":dict(sorted(Counter(x["reason"] for x in deferred).items())),
            "statusReviewCounts":dict(sorted(Counter(x["reviewStatus"] for x in reviews).items()))}

def simulate(raw,maintenance,repair,confirmation,report,urls,*,expected=BASELINE):
    """Return an in-memory unsigned staging document only. Never write it.

    URLs must be rehydrated by a trusted caller; exact hashes are mandatory.
    The original status, aliases, old stream objects and logos are immutable.
    Query-bearing URLs are deliberately held out of materialized previews.
    """
    recomputed=plan(raw,maintenance,repair,confirmation,expected=expected)
    if report!=recomputed:
        raise ValueError("repair plan mismatch")
    if not report["proposals"]:
        if urls:
            raise ValueError("unexpected replacement URLs")
        return None
    keys={(p["goStationId"],p["streamSha256"]) for p in report["proposals"]}
    if set(urls)!=keys:
        raise ValueError("missing or unexpected replacement URLs")
    old=strict_json(raw)
    new=copy.deepcopy(old)
    stations={s["go_station_id"]:s for s in new["stations"]}
    used={u for s in new["stations"] for v in s["streams"] for u in [v["url"],*v.get("previous_urls",[])]}
    for p in report["proposals"]:
        sid=p["goStationId"]
        url=urls[(sid,p["streamSha256"])]
        parsed=validate_endpoint(url)
        if parsed.query or sha(url.encode())!=p["streamSha256"] or url in used:
            raise ValueError("unsafe, changed or occupied replacement")
        s=stations[sid]
        if sha(encode(s))!=p["stationSha256"]:
            raise ValueError("station changed before staging")
        s["streams"].append({"stream_id":p["streamId"],"url":url,"priority":p["priority"],
                             "protocol":urlsplit(url).scheme,"state":"candidate_verified",
                             "codec":None,"bitrate_kbps":None,"last_checked_at":None,"previous_urls":[]})
        used.add(url)
    new["release_sequence"]=old["release_sequence"]+1
    new["generated_at"]=report["scanDate"]+"T00:00:00Z"
    # Reverse the sole permitted change and require byte-equivalent content.
    restored=copy.deepcopy(new)
    for p in report["proposals"]:
        s=next(x for x in restored["stations"] if x["go_station_id"]==p["goStationId"])
        s["streams"].pop()
    restored["release_sequence"]=old["release_sequence"]
    restored["generated_at"]=old["generated_at"]
    if restored!=old:
        raise ValueError("repair preservation violation")
    validate_shape(new)
    check_catalog(new,previous=old)
    return new

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("baseline","maintenance","repair","confirmation","output"):
        p.add_argument("--"+name,required=True,type=Path)
    p.add_argument("--baseline-sha256",default=BASELINE)
    a=p.parse_args()
    def load(path):
        if path.stat().st_size>MAX_BYTES:
            raise ValueError("oversize repair plan input")
        return path.read_bytes()
    report=plan(load(a.baseline),*(strict_json(load(getattr(a,k))) for k in ("maintenance","repair","confirmation")),expected=a.baseline_sha256)
    payload=encode(report)
    if len(payload)>MAX_BYTES:
        raise ValueError("oversize repair plan")
    a.output.write_bytes(payload)
    print("RADIO_REPAIR_PLAN_ONLY",{k:v for k,v in report.items() if k not in ("proposals","deferred","statusReviews")})

if __name__=="__main__":
    main()
