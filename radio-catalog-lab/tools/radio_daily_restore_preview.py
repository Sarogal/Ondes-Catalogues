"""Conservative monotone restoration planning, offline and unsigned.

Restore selected records from an authenticated historical release, without
reviving merged identities or discarding newly discovered stations. Historical
verification is not proof of present-day stream availability.
"""
import copy
from radio_daily_baseline_verify import verify_baseline
from radio_daily_lab_signing import validate_candidate
from radio_daily_v9_generator import encode, digest
from radio_stream_recheck_ledger import parse_day


def restore(current_pointer,current_body,historical_pointer,historical_body,*,
            current_anchor,historical_anchor,day,station_ids):
    day=parse_day(day)
    if (current_anchor["public_key"],current_anchor["key_id"]) != (
            historical_anchor["public_key"],historical_anchor["key_id"]):
        raise ValueError("different trusted signing lineage")
    current=verify_baseline(current_pointer,current_body,**current_anchor)
    historical=verify_baseline(historical_pointer,historical_body,**historical_anchor)
    if historical["release_sequence"]>=current["release_sequence"]:
        raise ValueError("restoration source must be older")
    if not isinstance(station_ids,(list,tuple)) or len(set(station_ids))!=len(station_ids):
        raise ValueError("explicit unique restoration IDs required")
    old={s["go_station_id"]:s for s in historical["stations"]}
    active={s["go_station_id"]:s for s in current["stations"]}
    tombs={t["go_station_id"]:t for t in current["tombstones"]}
    # A signed historical catalogue is not sufficient if it belongs to a
    # conflicting history. Every previous identity and alias must survive.
    for s in historical["stations"]+historical["tombstones"]:
        now=active.get(s["go_station_id"],tombs.get(s["go_station_id"]))
        if now is None or not set(s["legacy_aliases"])<=set(now["legacy_aliases"]):
            raise ValueError("historical identity continuity mismatch")
    if any(tombs.get(t["go_station_id"])!=t for t in historical["tombstones"]):
        raise ValueError("historical redirect continuity mismatch")
    if set(station_ids)-set(old).intersection(active):
        raise ValueError("restoration target missing or merged")
    restored=copy.deepcopy(current)
    changes=[]
    for i,now in enumerate(current["stations"]):
        sid=now["go_station_id"]
        if sid not in station_ids:
            continue
        previous=old[sid]
        if previous==now:
            continue
        # The lab holds status changes (including reactivation) and synthetic
        # stations; they need fresh evidence and a separate transition.
        if (previous["status"]["state"]!=now["status"]["state"] or
                any(s["status"].get("reason_code")=="synthetic_diagnostic_not_for_playback"
                    for s in (previous,now))):
            raise ValueError("status restoration requires independent requalification")
        row=copy.deepcopy(previous)
        row["status"]=copy.deepcopy(now["status"])
        row["legacy_aliases"]=list(now["legacy_aliases"])
        uuids={x["uuid"]:x for x in now["radio_browser_uuids"]}
        if len(uuids)!=len(now["radio_browser_uuids"]):
            raise ValueError("ambiguous current UUID identity")
        for entry in previous["radio_browser_uuids"]:
            uid=entry["uuid"]
            if uid not in uuids:
                uuids[uid]=dict(entry,state="historical")
        row["radio_browser_uuids"]=copy.deepcopy(list(uuids.values()))
        # Preserve subsequent stream IDs and all known URL history. Newer
        # variants remain present but disabled in the restored candidate.
        present={v["stream_id"]:v for v in now["streams"]}
        historic_ids={v["stream_id"] for v in row["streams"]}
        for v in row["streams"]:
            later=present.get(v["stream_id"])
            if later:
                history=[*v.get("previous_urls",[]),*later.get("previous_urls",[]),later["url"]]
                if history:
                    v["previous_urls"]=list(dict.fromkeys(u for u in history if u!=v["url"]))
        next_priority=max((v["priority"] for v in row["streams"]),default=-1)+1
        for v in now["streams"]:
            if v["stream_id"] not in historic_ids:
                row["streams"].append(dict(copy.deepcopy(v),state="disabled",priority=next_priority))
                next_priority+=1
        if row["logo"]!=now["logo"] and row["logo"] is not None:
            row["logo"]["revision"]=max(row["logo"]["revision"],(now["logo"] or {}).get("revision",0))+1
        if row==now:
            continue
        restored["stations"][i]=row
        changes.append(sid)
    report=dict(schemaVersion=1,publicationAllowed=False,signed=False,
        historicalSequence=historical["release_sequence"],currentSequence=current["release_sequence"],
        restoredStationIds=changes,candidateSequence=None,candidateSha256=None,
        requiresFreshStreamAndArtworkReview=bool(changes))
    if not changes:
        return None,report
    restored.update(release_sequence=current["release_sequence"]+1,generated_at=day+"T00:00:00Z")
    raw=encode(restored)
    validate_candidate(current_pointer,current_body,raw,expected_candidate_sha=digest(raw),
                       day=day,**current_anchor)
    report.update(candidateSequence=restored["release_sequence"],candidateSha256=digest(raw))
    return raw,report
