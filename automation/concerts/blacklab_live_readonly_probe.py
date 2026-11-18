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
            if len(approval["event"]["artistIds"])!=count or (
                    approval["event"]["time"] is not None):
                raise RuntimeError("Incomplete bill or unproved concert start")
            preexisting=next((e for e in catalog["events"]
                              if e.get("officialUrl")==url and
                                 e.get("date")==approval["event"]["date"] and
                                 e.get("venueId")==approval["event"]["venueId"]),
                             None)
            try:
                event,new=validate_approval(approval,
                      {x["id"]:x for x in catalog["venues"]},
                      {x["id"]:x for x in catalog["artists"]},today)
            except ValueError as exc:
                if preexisting is None:
                    raise
                # Existing signed approvals are reserved permanently.
                # The verifier may read them; the publisher MUST refuse
                # re-approving them through a newly invented signature.
                if preexisting["id"] != approval["event"]["id"]:
                    raise RuntimeError("Historical ID collision") from exc
                accepted=True
                outcome={"status":"first_party_bill_verified_existing_signed",
                         "publisherReapprovalRejected":True,
                         "namedArtists":len(approval["event"]["artistIds"]),
                         "time":approval["event"]["time"]}
            else:
                if preexisting is not None:
                    raise RuntimeError("Historical signed approval was bypassed")
                accepted=True
                outcome={"status":"new_first_party_approval_accepted",
                         "namedArtists":len(event["artistIds"]),
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
