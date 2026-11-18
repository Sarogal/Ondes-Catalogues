#!/usr/bin/env python3
"""Temporary read-only proof: three current first-party Black Lab pages.

NO private ledger, no approval or publication. This event-URL-specific
rehearsal file will be removed before recommending a merge. The generic
verifier has no event-specific exceptions or URL allowlists.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/"automation"/"concerts"),str(ROOT/"scripts")]
import blacklab_adapter as adapter
import blacklab_official_recheck as verifier
import official_recheck
from concerts_cloud_sync import validate_approval

SOURCE={"name":"The Black Lab","city":"Wasquehal","department":"59",
        "url":"https://theblacklab.fr/agenda/"}
TARGETS=(
  ("https://theblacklab.fr/agenda/houle-can-bardd-galibot/",3,True),
  ("https://theblacklab.fr/agenda/revnoir-ice-sealed-eyes/",2,True),
  ("https://theblacklab.fr/agenda/me-gusta-tu/",1,False),
)

def main():
    today=dt.date.today()
    catalog=json.loads((ROOT/"docs"/"grossesondes"/"concerts.json").read_text(encoding="utf-8"))
    if catalog.get("schemaVersion")!=1:
        raise RuntimeError("Unexpected catalog")
    # Existing published event IDs are deliberately NOT re-approved.
    # A read-only empty events overlay tests only named-lineup logic
    # without changing the public file on disk.
    working=copy.deepcopy(catalog)
    working["events"]=[]
    robots={}
    results=[]
    for url,count,should_accept in TARGETS:
        try:
            page=official_recheck.download_official(url,robots)
            candidate=adapter.detail_candidate(page,url,SOURCE,today.isoformat())
            candidate.update({"reviewBucket":"genre_tag_review",
                              "possibleExistingConcert":False})
            approval=verifier.verify(candidate,page,working,today)
            event,new=validate_approval(approval,
                  {x["id"]:x for x in catalog["venues"]},
                  {x["id"]:x for x in catalog["artists"]},today)
            accepted=True
            if len(event["artistIds"])!=count or event["time"] is not None:
                raise RuntimeError("Incomplete bill or unproved concert start")
            outcome={"status":"accepted","namedArtists":len(event["artistIds"]),
                     "newArtists":len(new),"time":event["time"]}
        except Exception as exc:
            accepted=False
            outcome={"status":"held","reason":type(exc).__name__+": "+str(exc)[:170]}
        outcome["url"]=url
        results.append(outcome)
        if accepted!=should_accept:
            print(json.dumps({"results":results},ensure_ascii=False,sort_keys=True),flush=True)
            raise AssertionError("Unexpected approval/hold from first-party source")
    print(json.dumps({"mode":"public-live-readonly-no-private-ledger","results":results},
                     ensure_ascii=False,sort_keys=True),flush=True)

if __name__=="__main__":
    main()
