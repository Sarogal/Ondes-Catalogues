"""Conservative duplicate staging from the pinned catalogue and probe history."""
import copy
from itertools import combinations
from urllib.parse import urlsplit
from radio_daily_v9_generator import digest, encode
from radio_daily_maintenance_preview import age
from radio_daily_repair_preview import name_key

MAX_MERGES=2

def plan(old, maintenance, day, blocked=()):
    stations=old["stations"]
    redirects={t.get("redirect_to") for t in old["tombstones"]}
    history={(r["goStationId"],r["streamId"]):r["observations"] for r in maintenance["streams"]}
    groups={}
    for s in stations:
        key=(name_key(s["display_name"]),s["country_code"])
        groups.setdefault(key,[]).append(s)
    proposals=[]
    deferred=[]
    for (name,country),group in sorted(groups.items(),key=lambda item:str(item[0])):
        if len(group)<2:
            continue
        ids=sorted(s["go_station_id"] for s in group)
        def hold(reason):
            deferred.append({"goStationIds":ids,"reason":reason})
        if len(group)!=2:
            hold("ambiguous_duplicate_group")
            continue
        if not country or len(name)<4 or "radio bob" in name:
            hold("protected_or_ambiguous_identity")
            continue
        a,b=sorted(group,key=lambda s:(s["go_station_id"] not in redirects,s["go_station_id"]))
        target,source=a,b
        if source["go_station_id"] in redirects or set(ids)&set(blocked):
            hold("redirect_or_concurrent_change_conflict")
            continue
        if any(s["status"]["state"]!="active" or s["status"].get("reason_code")=="synthetic_diagnostic_not_for_playback" for s in group):
            hold("station_status_conflict")
            continue
        if (not target.get("homepage") or target["homepage"]!=source.get("homepage")
                or urlsplit(target["homepage"]).query
                or target["genres"]!=source["genres"]
                or target["editorial"]!=source["editorial"]
                or (source["logo"] is not None and source["logo"]!=target["logo"])):
            hold("identity_or_artwork_conflict")
            continue
        # Every field of every retired variant must already exist in the
        # survivor, including historical URLs and stream identifiers.
        if not source["streams"] or any(v not in target["streams"] for v in source["streams"]):
            hold("variant_transfer_requires_review")
            continue
        if any(urlsplit(v["url"]).query or urlsplit(v["url"]).fragment for s in group for v in s["streams"]):
            hold("query_or_fragment_stream_held")
            continue
        def positive(s,v):
            obs=history.get((s["go_station_id"],v["stream_id"]),[])
            good=[]
            for o in reversed(obs):
                if o["outcome"]!="audio_hint" or age(day,o["date"])>7:
                    break
                good.append(o["date"])
            return set(good)
        shared=[]
        for v in source["streams"]:
            dates=positive(target,v)&positive(source,v)
            if len(dates)>=2 and day in dates:
                shared.append({"streamSha256":digest(v["url"].encode()),"dates":sorted(dates)})
        if not shared:
            hold("await_repeated_shared_stream")
            continue
        proposals.append({"sourceGoStationId":source["go_station_id"],"targetGoStationId":target["go_station_id"],
            "sourceSha256":digest(encode(source)),"targetSha256":digest(encode(target)),
            "sharedEvidence":shared,"approved":False,"publicationAllowed":False})
    if len(proposals)>MAX_MERGES:
        deferred.append({"reason":"mass_merge_held","proposalCount":len(proposals)})
        proposals=[]
    return proposals,deferred

def apply(output, old, proposals, day):
    originals={s["go_station_id"]:s for s in old["stations"]}
    for p in proposals:
        current={s["go_station_id"]:s for s in output["stations"]}
        sid,tid=p["sourceGoStationId"],p["targetGoStationId"]
        source,target=current[sid],current[tid]
        if source!=originals[sid] or target!=originals[tid]:
            raise ValueError("merge conflicts with concurrent change")
        if digest(encode(source))!=p["sourceSha256"] or digest(encode(target))!=p["targetSha256"]:
            raise ValueError("merge station fingerprint mismatch")
        output["stations"].remove(source)
        output["tombstones"].append({"go_station_id":sid,"legacy_aliases":copy.deepcopy(source["legacy_aliases"]),
           "retired_at":day+"T00:00:00Z","reason_code":"merged_into_station","redirect_to":tid})

def undo(output, old, proposals):
    originals={s["go_station_id"]:s for s in old["stations"]}
    for p in reversed(proposals):
        sid=p["sourceGoStationId"]
        tombstone=output["tombstones"].pop()
        if tombstone["go_station_id"]!=sid or tombstone["redirect_to"]!=p["targetGoStationId"]:
            raise ValueError("unexpected merge redirect delta")
        output["stations"].append(copy.deepcopy(originals[sid]))
    # Restore baseline ordering without replacing any surviving records.
    order={s["go_station_id"]:i for i,s in enumerate(old["stations"])}
    output["stations"].sort(key=lambda s:order.get(s["go_station_id"],len(order)))
