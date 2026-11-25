#!/usr/bin/env python3
"""Corroborate an ICY artist/title pair against MusicBrainz recording credits.

Raw titles are transient runner input, never stored in the output. Exact credit
matches are hypotheses about metadata, not proof of what actually played.
"""
import argparse
import datetime as dt
import json
import re
import time
import unicodedata
from pathlib import Path
from urllib.error import HTTPError

from radio_daily_artist_research import Client, key, safe_name, valid_id
from radio_daily_metadata_preview import valid_hint
from radio_daily_qualification_dossiers import index, safe_digest
from radio_stream_recheck_ledger import parse_day, SHA256_RE

MAX_TASKS = 4
MAX_BYTES = 12 * 1024 * 1024
SEARCH_LIMIT = 50

def safe_title(value):
    return (isinstance(value,str) and 1 <= len(value) <= 140
            and any(c.isalnum() for c in value)
            and not any(unicodedata.category(c).startswith("C") for c in value)
            and not re.search(r"https?://|www\.|@|[?=]",value,re.I))

def phrase(value):
    return '"' + value.replace("\\","\\\\").replace('"','\\"') + '"'

def resolve(artist,title,request):
    data=request({"query":"artist:"+phrase(artist)+" AND recording:"+phrase(title),
                  "limit":SEARCH_LIMIT})
    rows,count=data.get("recordings"),data.get("count")
    if not isinstance(rows,list) or type(count) is not int or count<len(rows):
        raise ValueError("invalid recording search")
    if count>len(rows):
        return {"status":"incomplete_search"}
    found={}
    for row in rows:
        if not isinstance(row,dict) or not isinstance(row.get("title"),str) or key(row["title"])!=key(title):
            continue
        credits=row.get("artist-credit")
        if not isinstance(credits,list) or not credits or len(credits)>20:
            continue
        if any(not isinstance(c,dict) or not isinstance(c.get("artist"),dict)
               or not isinstance(c.get("name",c["artist"].get("name")),str)
               or not isinstance(c.get("joinphrase",""),str)
               or not valid_id(c["artist"].get("id")) for c in credits):
            continue
        credit="".join(c.get("name",c["artist"].get("name"))+c.get("joinphrase","") for c in credits).strip()
        if key(credit)!=key(artist):
            continue
        ids=tuple(c["artist"]["id"] for c in credits)
        rid=row.get("id")
        if not valid_id(rid):
            raise ValueError("invalid recording id")
        found.setdefault(ids,set()).add(rid)
    if len(found)!=1:
        return {"status":"ambiguous_credit" if found else "no_exact_credit"}
    ids,recordings=next(iter(found.items()))
    return {"status":"recording_credit_hypothesis","artistMbids":list(ids),
            "recordingMbids":sorted(recordings)}

def build(metadata,research,titles,*,prior=None,limit=0,request=None):
    day=parse_day(metadata["scanDate"])
    for r in (metadata,research):
        if r.get("schemaVersion")!=1 or r.get("scanDate")!=day or r.get("publicationAllowed") is not False or r.get("approvedCount")!=0:
            raise ValueError("untrusted input")
    if type(limit) is not int or not 0<=limit<=MAX_TASKS or not isinstance(titles,list) or len(titles)>18:
        raise ValueError("invalid task budget")
    rows=index(metadata,"records")
    entries={}
    if prior is not None:
        if (prior.get("schemaVersion")!=1 or prior.get("publicationAllowed") is not False or prior.get("approvedCount")!=0
                or parse_day(prior["scanDate"])>day or not isinstance(prior.get("entries"),dict)):
            raise ValueError("untrusted recording cache")
        for k,e in prior["entries"].items():
            if (not isinstance(e,dict) or not safe_name(e.get("artistHint"))
                    or not SHA256_RE.fullmatch(e.get("titleSha256") or "")
                    or k!=safe_digest(e["artistHint"]+"\n"+e["titleSha256"])
                    or e.get("identityVerified") is not False or e.get("publicationAllowed") is not False
                    or parse_day(e["checkedAt"])>day or e.get("source")!="musicbrainz-recording-search"):
                raise ValueError("invalid recording cache entry")
            entries[k]=e
    tasks={}
    for t in titles:
        if (not valid_hint(t) or not safe_name(t["artistHint"]) or not safe_title(t.get("titleHint"))
                or safe_digest(t["titleHint"])!=t["titleSha256"]):
            continue
        row=rows.get(t.get("stationuuid"),{})
        if (row.get("streamSha256")!=t.get("streamSha256") or row.get("approved") is not False
                or row.get("publicationAllowed") is not False or row.get("observedDate")!=day
                or not any(h.get("date")==day and h.get("artistHint")==t["artistHint"]
                           and h.get("titleSha256")==t["titleSha256"] for h in row.get("observations",[]))):
            continue
        k=safe_digest(t["artistHint"]+"\n"+t["titleSha256"])
        old=entries.get(k)
        if old:
            age=(dt.date.fromisoformat(day)-dt.date.fromisoformat(old["checkedAt"])).days
            if age < (30 if old["status"]=="recording_credit_hypothesis" else 7):
                continue
        tasks[k]=t
    attempted=0
    failure=None
    # Avoid hammering the same API after a failed artist research call.
    held=bool(research.get("serviceFailure"))
    if limit and tasks and not held and request is None:
        time.sleep(1.2)
        request=Client().recordings
    for k,t in sorted(tasks.items())[:0 if held else limit]:
        attempted+=1
        try:
            result=resolve(t["artistHint"],t["titleHint"],request)
        except (ValueError,OSError,TypeError,KeyError) as exc:
            failure="http_"+str(exc.code) if isinstance(exc,HTTPError) else "service_or_response_held"
            break
        entries[k]=dict(result,artistHint=t["artistHint"],titleSha256=t["titleSha256"],
                        source="musicbrainz-recording-search",checkedAt=day,identityVerified=False,publicationAllowed=False)
    return {"schemaVersion":1,"scanDate":day,"publicationAllowed":False,"approvedCount":0,
            "duePairCount":len(tasks),"attemptedCount":attempted,"heldByArtistService":held,
            "serviceFailure":failure,"entries":dict(sorted(entries.items()))}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("metadata","research","titles","output"):
        p.add_argument("--"+name,required=True,type=Path)
    p.add_argument("--previous",type=Path)
    p.add_argument("--limit",type=int,default=0)
    p.add_argument("--allow-network",action="store_true")
    a=p.parse_args()
    if a.limit and not a.allow_network:
        p.error("network must be explicit")
    def load(path):
        if path.stat().st_size>MAX_BYTES:
            raise ValueError("oversize input")
        return json.loads(path.read_text("utf-8"))
    result=build(load(a.metadata),load(a.research),load(a.titles),prior=load(a.previous) if a.previous else None,limit=a.limit)
    payload=json.dumps(result,ensure_ascii=False,indent=2)+"\n"
    if len(payload.encode())>MAX_BYTES:
        raise ValueError("oversize output")
    a.output.write_text(payload,encoding="utf-8")
    print("RADIO_RECORDING_CREDIT_PREVIEW_ONLY",{k:v for k,v in result.items() if k!="entries"})

if __name__=="__main__":
    main()
