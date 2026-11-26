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
from radio_daily_editorial_preview import Page, station_nodes, homepage_url, fetch_html, related_host, followup_links
from radio_daily_discovery import fetch_page, resolve_api_mirrors
from radio_stream_technical_probe import PinnedHttpTransport, probe_url
from radio_stream_recheck_ledger import parse_day, SHA256_RE
from radio_daily_hls_preview import observe as observe_hls
from radio_daily_continuity_preview import observe_url

MAX_CHECKS=4
ANALYZER_VERSION=2
ROUTES={"direct","hls"}
CONTINUITY={"not_checked","continuous_hint","inconclusive"}
STATUSES={"directory_held","directory_changed","broadcaster_held","broadcaster_unlinked",
          "audio_hint","unavailable_hint","inconclusive"}
POSITIVE={"audio_hint"}
DECLARATIONS={"typed_station","unique_named_player","linked_typed_station","linked_unique_named_player"}

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

def named_root(station,body):
    p=Page()
    p.feed(body.decode("utf-8",errors="replace"))
    name=name_key(station["display_name"])
    return (len(name)>=5 and name not in {"radio","metal","punk","hard rock"}
            and (any(name_key(v)==name for v in p.identity)
                 or any(name_key(n.get("name"))==name for n in station_nodes(p.structured))))

def confirm_page(station,page,url,fetch):
    final,body=fetch(page)
    if (not related_host(final,page) or homepage_url(final)!=final
            or page_key(final)!=page_key(page) or not isinstance(body,bytes) or len(body)>256*1024):
        raise ValueError("unexpected broadcaster response")
    root_hash=hashlib.sha256(body).hexdigest()
    mode=declaration(station,final,body,url)
    if mode:
        return mode,root_hash,None
    # Only follow the generic editorial player/about links on a named
    # station page. The child must independently declare the same station.
    if named_root(station,body):
        for child in followup_links(final,body):
            try:
                child_final,child_body=fetch(child)
                if (not related_host(child_final,final) or homepage_url(child_final)!=child_final
                        or page_key(child_final)!=page_key(child)
                        or not isinstance(child_body,bytes) or len(child_body)>256*1024):
                    continue
                mode=declaration(station,child_final,child_body,url)
                if mode:
                    return "linked_"+mode,hashlib.sha256(child_body).hexdigest(),root_hash
            except (ValueError,OSError,http.client.HTTPException,TypeError,AttributeError):
                continue
    return None,None,None

def build(raw,repair,*,expected=BASELINE,prior=None,limit=0,search=None,fetch=None,probe=None,
          hls_probe=None,continuity_probe=None):
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
                root=o.get("rootPageSha256")
                route=o.get("route","direct" if mode else None)
                continuity=o.get("continuity","not_checked")
                version=o.get("analyzerVersion",1)
                if (type(version) is not int or not 1<=version<=ANALYZER_VERSION
                        or (mode in ("linked_typed_station","linked_unique_named_player") and not SHA256_RE.fullmatch(root or ""))
                        or (mode not in ("linked_typed_station","linked_unique_named_player") and root is not None)
                        or (mode and route not in ROUTES) or (not mode and route is not None)
                        or continuity not in CONTINUITY
                        or (continuity=="continuous_hint" and status!="audio_hint")):
                    raise ValueError("invalid extended confirmation observation")
                dates.append(date)
                if k in history and age(day,date)<30:
                    history[k].append({"date":date,"status":status,"declaration":mode,"pageSha256":page,
                                       "rootPageSha256":root,"route":route,"continuity":continuity,"analyzerVersion":version})
            if dates!=sorted(set(dates)):
                raise ValueError("duplicate confirmation dates")
    queue=sorted((k for k in candidates if k not in conflicts and
                  (not history[k] or history[k][-1]["date"]!=day or
                   (history[k][-1]["status"]=="broadcaster_unlinked" and
                    history[k][-1]["analyzerVersion"]<ANALYZER_VERSION))),
                 key=lambda k:(history[k][-1]["date"] if history[k] else "",k))
    if limit and queue and any(x is None for x in (search,fetch,probe)):
        raise ValueError("explicit confirmation services required")
    attempted=0
    def record(k,status,mode=None,page=None,root=None,route=None,continuity="not_checked"):
        if history[k] and history[k][-1]["date"]==day:
            history[k].pop()
        history[k].append({"date":day,"status":status,"declaration":mode,"pageSha256":page,
                           "rootPageSha256":root,"route":route,"continuity":continuity,
                           "analyzerVersion":ANALYZER_VERSION})
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
            mode,page_hash,root_hash=confirm_page(station,page,url,fetch)
        except (ValueError,OSError,http.client.HTTPException,TypeError,AttributeError):
            record(k,"broadcaster_held")
            continue
        if not mode:
            record(k,"broadcaster_unlinked")
            continue
        route="direct"
        continuity="not_checked"
        try:
            sample=probe(url)
            status=outcome(sample,sha)
            if sample.get("verdict")=="playlist_pending" and hls_probe is not None:
                route="hls"
                h=hls_probe(url)
                if h.get("verdict")=="advancing_hls_audio_frame_indication" and h.get("frameCodec"):
                    status="audio_hint"
                    continuity="continuous_hint"
                else:
                    status="inconclusive"
                    continuity="inconclusive"
            elif status=="audio_hint" and continuity_probe is not None:
                c=continuity_probe(url)
                continuity=("continuous_hint" if c.get("verdict")=="continuous_icy_frame_indication" else "inconclusive")
        except (ValueError,OSError,http.client.HTTPException):
            status="inconclusive"
            continuity="inconclusive"
        record(k,status,mode,page_hash,root_hash,route,continuity)
    records=[]
    for k,obs in sorted(history.items()):
        recent=[x for x in obs if age(day,x["date"])<=7]
        positives=[]
        for o in reversed(recent):
            if o["status"]!="audio_hint":
                break
            positives.append(o["date"])
        strong=[]
        for o in reversed(recent):
            if o["status"]!="audio_hint" or o.get("continuity")!="continuous_hint":
                break
            strong.append(o["date"])
        state=("identity_collision_held" if k in conflicts else
               "repeated_continuity_review" if len(strong)>=2 and day in strong else
               "repeated_audio_review" if len(positives)>=2 and day in positives else
               recent[-1]["status"] if recent else "awaiting_confirmation")
        records.append({"goStationId":k[0],"stationuuid":k[1],"streamSha256":k[2],
                        "observations":obs,"positiveDates":sorted(positives),"continuityDates":sorted(strong),"reviewStatus":state,
                        "approved":False,"publicationAllowed":False})
    return {"schemaVersion":1,"scanDate":day,"catalogBaselineSha256":expected,
            "approvedCount":0,"publicationAllowed":False,"analyzerVersion":ANALYZER_VERSION,"attemptedCount":attempted,
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
                 probe=lambda u:probe_url(u,transport.request),
                 hls_probe=observe_hls,continuity_probe=observe_url)
    payload=json.dumps(report,ensure_ascii=False,indent=2)+"\n"
    if len(payload.encode())>MAX_BYTES:
        raise ValueError("oversize confirmation output")
    a.output.write_text(payload,encoding="utf-8")
    print("RADIO_REPAIR_CONFIRMATION_PREVIEW_ONLY",{k:v for k,v in report.items() if k!="records"})

if __name__=="__main__":
    main()
