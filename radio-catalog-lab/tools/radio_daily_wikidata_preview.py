#!/usr/bin/env python3
"""Independent Wikidata artist/genre hypotheses; never approve a radio."""
import argparse
import datetime as dt
import json
import re
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import build_opener, ProxyHandler, Request

from radio_daily_artist_research import NoRedirect, key, safe_name, valid_id
from radio_daily_metadata_preview import valid_hint
from radio_daily_qualification_dossiers import index
from radio_stream_recheck_ledger import parse_day, SHA256_RE

BASE="https://www.wikidata.org/w/api.php"
MAX_BYTES=12*1024*1024
MAX_RESPONSE=1_000_000
MAX_NAMES=6
SEARCH_LIMIT=20

def qid(v):
    return isinstance(v,str) and bool(re.fullmatch(r"Q[1-9][0-9]{0,15}",v))

class Client:
    def __init__(self):
        self.opener=build_opener(ProxyHandler({}),NoRedirect())
        self.last=None
    def __call__(self,params):
        if self.last is not None:
            time.sleep(max(0,1.2-(time.monotonic()-self.last)))
        self.last=time.monotonic()
        req=Request(BASE+"?"+urlencode(dict(params,format="json",maxlag=5)),
                    headers={"User-Agent":"GrossesOndes-RadioPreview/1.0 (https://grosses-ondes.fr/)",
                             "Accept":"application/json","Accept-Encoding":"identity"})
        with self.opener.open(req,timeout=8) as response:
            raw=response.read(MAX_RESPONSE+1)
        if len(raw)>MAX_RESPONSE:
            raise ValueError("oversize directory response")
        data=json.loads(raw)
        if not isinstance(data,dict) or "error" in data:
            raise ValueError("directory unavailable")
        return data

def claims(entity,prop):
    rows=entity.get("claims",{}).get(prop,[])
    if not isinstance(rows,list) or len(rows)>100:
        raise ValueError("invalid claims")
    result=[]
    for row in rows:
        if not isinstance(row,dict) or row.get("rank")=="deprecated":
            continue
        snak=row.get("mainsnak",{})
        if snak.get("snaktype")=="value":
            result.append((snak.get("datavalue") or {}).get("value"))
    return result

def ids(entity,prop):
    return {v["id"] for v in claims(entity,prop) if isinstance(v,dict) and qid(v.get("id"))}

def labels(entity):
    out=[]
    for v in entity.get("labels",{}).values():
        if isinstance(v,dict) and isinstance(v.get("value"),str):
            out.append(v["value"])
    return out

def research(name,request):
    matches=set()
    for lang in ("en","fr"):
        data=request({"action":"wbsearchentities","search":name,"language":lang,
                      "type":"item","limit":SEARCH_LIMIT})
        rows=data.get("search")
        if "search-continue" in data or "continue" in data or not isinstance(rows,list) or len(rows)>=SEARCH_LIMIT:
            return {"status":"ambiguous_or_incomplete"}
        for row in rows:
            if not isinstance(row,dict):
                continue
            match=row.get("match") or {}
            candidates=[row.get("label"),match.get("text") if isinstance(match,dict) else None]
            if any(isinstance(v,str) and key(v)==key(name) for v in candidates):
                if not qid(row.get("id")):
                    raise ValueError("invalid directory id")
                matches.add(row["id"])
    if len(matches)!=1:
        return {"status":"ambiguous_or_incomplete" if matches else "not_found"}
    ident=next(iter(matches))
    data=request({"action":"wbgetentities","ids":ident,"props":"labels|aliases|claims","languages":"en|fr"})
    entity=data.get("entities",{}).get(ident)
    if not isinstance(entity,dict) or entity.get("id")!=ident:
        return {"status":"identity_held"}
    names=labels(entity)
    for rows in entity.get("aliases",{}).values():
        if isinstance(rows,list):
            names.extend(v["value"] for v in rows if isinstance(v,dict) and isinstance(v.get("value"),str))
    if key(name) not in {key(n) for n in names}:
        return {"status":"identity_held"}
    kinds=ids(entity,"P31")
    genre_ids=ids(entity,"P136")
    if not ("Q215380" in kinds or ("Q5" in kinds and (ids(entity,"P106") & {"Q639669","Q177220","Q488205","Q753110"} or genre_ids))):
        return {"status":"identity_held"}
    genres={}
    if genre_ids:
        if len(genre_ids)>30:
            return {"status":"genre_set_held"}
        data=request({"action":"wbgetentities","ids":"|".join(sorted(genre_ids)),
                      "props":"labels","languages":"en"})
        for g in sorted(genre_ids):
            v=data.get("entities",{}).get(g,{})
            label=v.get("labels",{}).get("en",{}).get("value")
            if v.get("id")==g and safe_name(label):
                genres[g]=label
    return {"status":"name_hypothesis","qid":ident,"genresById":genres,
            "musicbrainzIds":sorted({v for v in claims(entity,"P434") if valid_id(v)}),
            "sourceUrl":"https://www.wikidata.org/wiki/"+ident,
            "genreSource":"wikidata-P136"}

def validate_entry(k,e,day):
    if (not isinstance(e,dict) or not safe_name(e.get("artistName")) or key(e["artistName"])!=k
            or e.get("source")!="wikidata" or e.get("identityVerified") is not False
            or e.get("publicationAllowed") is not False or parse_day(e["checkedAt"])>day):
        raise ValueError("untrusted directory cache")
    if e.get("status")=="name_hypothesis":
        ident=e.get("qid")
        genres=e.get("genresById")
        links=e.get("musicbrainzIds")
        if (not qid(ident) or e.get("sourceUrl")!="https://www.wikidata.org/wiki/"+ident
                or e.get("genreSource")!="wikidata-P136" or not isinstance(genres,dict)
                or len(genres)>30 or any(not qid(g) or not safe_name(v) for g,v in genres.items())
                or not isinstance(links,list) or len(links)>100 or any(not valid_id(v) for v in links)):
            raise ValueError("untrusted directory provenance")

def build(metadata,*,prior=None,limit=0,request=None):
    day=parse_day(metadata["scanDate"])
    if (metadata.get("schemaVersion")!=1 or metadata.get("publicationAllowed") is not False
            or metadata.get("approvedCount")!=0 or type(limit) is not int or not 0<=limit<=MAX_NAMES):
        raise ValueError("invalid metadata")
    names={}
    for row in index(metadata,"records").values():
        if (row.get("approved") is not False or row.get("publicationAllowed") is not False
                or not SHA256_RE.fullmatch(row.get("streamSha256") or "")
                or parse_day(row["observedDate"])>day or not isinstance(row.get("observations"),list)
                or len(row["observations"])>90):
            raise ValueError("invalid metadata row")
        for h in row["observations"]:
            if not valid_hint(h) or parse_day(h["date"])>day:
                raise ValueError("invalid observation")
            n=h["artistHint"].strip()
            if safe_name(n):
                names.setdefault(key(n),set()).add(n)
    entries={}
    if prior is not None:
        if (prior.get("schemaVersion")!=1 or prior.get("publicationAllowed") is not False
                or prior.get("approvedCount")!=0 or parse_day(prior["scanDate"])>day
                or not isinstance(prior.get("entries"),dict)):
            raise ValueError("invalid directory cache")
        entries=dict(prior["entries"])
        for k,e in entries.items():
            validate_entry(k,e,day)
    today=dt.date.fromisoformat(day)
    tasks=[]
    for k,n in names.items():
        if len(n)!=1:
            continue
        e=entries.get(k)
        age=(today-dt.date.fromisoformat(e["checkedAt"])).days if e else 999999
        if age >= (30 if e and e.get("genresById") else 7):
            tasks.append((-age,k,next(iter(n))))
    tasks.sort()
    cursor=prior.get("retryAfterKey") if prior else None
    for i,t in enumerate(tasks):
        if t[1]==cursor:
            tasks=tasks[i+1:]+tasks[:i+1]
            break
    if limit and tasks and request is None:
        request=Client()
    failure=retry=None
    attempted=0
    for _,k,n in tasks[:limit]:
        attempted+=1
        try:
            result=research(n,request)
        except (ValueError,TypeError,KeyError,AttributeError,OSError) as exc:
            failure="http_"+str(exc.code) if isinstance(exc,HTTPError) else "service_or_response_held"
            retry=k
            break
        entries[k]=dict(result,artistName=n,checkedAt=day,source="wikidata",
                        identityVerified=False,publicationAllowed=False)
    return {"schemaVersion":1,"scanDate":day,"publicationAllowed":False,"approvedCount":0,
            "observedNameCount":len(names),"dueNameCount":len(tasks),"attemptedCount":attempted,
            "serviceFailure":failure,"retryAfterKey":retry,"entries":dict(sorted(entries.items()))}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("metadata","output"):
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
    result=build(load(a.metadata),prior=load(a.previous) if a.previous else None,limit=a.limit)
    payload=json.dumps(result,ensure_ascii=False,indent=2)+"\n"
    if len(payload.encode())>MAX_BYTES:
        raise ValueError("oversize output")
    a.output.write_text(payload,encoding="utf-8")
    print("RADIO_WIKIDATA_PREVIEW_ONLY",{k:v for k,v in result.items() if k not in {"entries","retryAfterKey"}})

if __name__=="__main__":
    main()
