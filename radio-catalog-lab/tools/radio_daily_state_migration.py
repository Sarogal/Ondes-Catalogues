"""Offline migration of resource-bound evidence between verified successors.

The caller supplies trusted anchors for BOTH signed snapshots. Nothing is
published, signed, or persisted by this module. Derived approvals are never
copied; all reports are regenerated using the new catalogue.
"""
import copy
from radio_daily_baseline_verify import verify_baseline
from radio_daily_v9_generator import digest,check_catalog
from radio_daily_maintenance_preview import build as maintenance_build, catalogue_rows
from radio_daily_logo_maintenance import build as logo_build
from radio_daily_missing_logo import build as missing_build
from radio_daily_status_preview import build as status_build
from radio_daily_repair_preview import build as repair_build, validate_hint
from radio_catalog_daily_candidate_reconcile import index_catalog
from radio_daily_maintenance_preview import age
from radio_daily_repair_confirmation import build as confirmation_build
from radio_daily_repair_plan import plan as repair_plan
from radio_stream_recheck_ledger import parse_day


def identity(s):
    return (s["display_name"],s["country_code"],s.get("homepage"),
            s["radio_browser_uuids"],s["legacy_aliases"],
            s["status"].get("reason_code")=="synthetic_diagnostic_not_for_playback")


def migrate(old_pointer,old_raw,new_pointer,new_raw,*,old_anchor,new_anchor,day,
            maintenance,logo,missing,status,repair,confirmation):
    day=parse_day(day)
    old=verify_baseline(old_pointer,old_raw,**old_anchor)
    new=verify_baseline(new_pointer,new_raw,**new_anchor)
    old_sha,new_sha=digest(old_raw),digest(new_raw)
    if new["release_sequence"]!=old["release_sequence"]+1:
        raise ValueError("migration requires immediate signed successor")
    check_catalog(new,previous=old)
    new_tombs={t["go_station_id"]:t for t in new["tombstones"]}
    if any(new_tombs.get(t["go_station_id"])!=t for t in old["tombstones"]):
        raise ValueError("historical redirect changed")
    a={s["go_station_id"]:s for s in old["stations"]}
    b={s["go_station_id"]:s for s in new["stations"]}
    same={sid for sid in a.keys()&b.keys() if identity(a[sid])==identity(b[sid])}
    _,old_streams=catalogue_rows(old_raw,old_sha)
    _,new_streams=catalogue_rows(new_raw,new_sha)
    common={k for k in old_streams.keys()&new_streams.keys()
            if k[0] in same and old_streams[k]==new_streams[k]}
    reports=(maintenance,logo,missing,status,repair,confirmation)
    old_day=parse_day(maintenance["scanDate"])
    if old_day>day or any(x.get("scanDate")!=old_day or
        x.get("catalogBaselineSha256")!=old_sha or x.get("publicationAllowed") is not False for x in reports):
        raise ValueError("incompatible migration evidence")
    # Validate source histories against the old signed inventory first.
    m=maintenance_build(old_raw,old_day,expected=old_sha,prior=maintenance)
    l=logo_build(old_raw,old_day,expected=old_sha,prior=logo)
    n=missing_build(old_raw,old_day,expected=old_sha,prior=missing)
    rp=repair_plan(old_raw,maintenance,repair,confirmation,expected=old_sha)
    st=status_build(old_raw,maintenance,rp,expected=old_sha,prior=status)
    for derived,stored,keys in ((m,maintenance,("streams","records")),(l,logo,("sources","records")),
            (n,missing,("records",)),(st,status,("streams","records","proposals"))):
        if any(derived[k]!=stored.get(k) for k in keys):
            raise ValueError("source migration history mismatch")
    def rebind(report,field,rows):
        prior=copy.deepcopy(report)
        prior["catalogBaselineSha256"]=new_sha
        prior[field]=copy.deepcopy(rows)
        return prior
    streams=[x for x in m["streams"] if (x["goStationId"],x["streamId"]) in common]
    new_m=maintenance_build(new_raw,day,expected=new_sha,prior=rebind(m,"streams",streams))
    # URL histories are shared by all stations using a source. Preserve only
    # sources whose complete set of owners and descriptors remains identical.
    def sources(stations):
        result={}
        for sid,s in stations.items():
            if s["logo"]:
                result.setdefault(digest(s["logo"]["url"].encode()),{})[sid]=s["logo"]
        return result
    old_sources,new_sources=sources(a),sources(b)
    stable_sources={k for k in old_sources.keys()&new_sources.keys()
        if old_sources[k]==new_sources[k] and set(old_sources[k])<=same}
    logos=[x for x in l["sources"] if x["sourceSha256"] in stable_sources]
    new_l=logo_build(new_raw,day,expected=new_sha,prior=rebind(l,"sources",logos))
    missing_rows=[x for x in n["records"] if x["goStationId"] in same
        and b[x["goStationId"]]["logo"] is None and a[x["goStationId"]]["status"]==b[x["goStationId"]]["status"]]
    new_n=missing_build(new_raw,day,expected=new_sha,prior=rebind(n,"records",missing_rows))
    # Recompute eligibility from migrated observations; keep repair history
    # only when the full station/variant contract and candidate ownership agree.
    old_owners,_,_=index_catalog(old)
    new_owners,_,_=index_catalog(new)
    occupied={digest(u.encode()) for station in new["stations"] for v in station["streams"]
              for u in [v["url"],*v.get("previous_urls",[])]}
    stable_repair={sid for sid in same if a[sid]["streams"]==b[sid]["streams"]
                   and a[sid]["status"]==b[sid]["status"] and a[sid]["genres"]==b[sid]["genres"]}
    repair_rows=[]
    kept_keys=set()
    for row in repair["records"]:
        sid=row["goStationId"]
        if sid not in stable_repair:
            continue
        hints=row["hints"]
        # An incomplete set must never become a falsely unique candidate.
        if any(old_owners.get(h["stationuuid"])!=new_owners.get(h["stationuuid"])
               or new_owners.get(h["stationuuid"]) not in (None,sid)
               or h["streamSha256"] in occupied for h in hints):
            continue
        for h in hints:
            validate_hint(h)
        if hints and (not row.get("hintsObservedDate") or age(day,row["hintsObservedDate"])>=7):
            continue
        repair_rows.append(row)
        kept_keys.update((sid,h["stationuuid"],h["streamSha256"]) for h in hints)
    discovery={"schemaVersion":1,"scanDate":day,"publicationAllowed":False,"candidates":[]}
    # Validate original search register before filtering/rebinding.
    repair_build(old_raw,m,dict(discovery,scanDate=old_day),expected=old_sha,prior=repair)
    new_r=repair_build(new_raw,new_m,discovery,expected=new_sha,
                       prior=rebind(repair,"records",repair_rows))
    confirmation_rows=[x for x in confirmation["records"]
                       if (x["goStationId"],x["stationuuid"],x["streamSha256"]) in kept_keys]
    new_c=confirmation_build(new_raw,new_r,expected=new_sha,
                              prior=rebind(confirmation,"records",confirmation_rows))
    new_rp=repair_plan(new_raw,new_m,new_r,new_c,expected=new_sha)
    recovery=[x for x in st["streams"] if (x["goStationId"],x["streamId"]) in common
        and a[x["goStationId"]]["status"]==b[x["goStationId"]]["status"]]
    new_st=status_build(new_raw,new_m,new_rp,expected=new_sha,prior=rebind(st,"streams",recovery))
    return {"maintenance":new_m,"logoMaintenance":new_l,"missingLogo":new_n,
            "status":new_st,"repair":new_r,"confirmation":new_c,"repairPlan":new_rp,
            "migration":{"schemaVersion":1,"publicationAllowed":False,"oldBaselineSha256":old_sha,
                "newBaselineSha256":new_sha,"oldSequence":old["release_sequence"],"newSequence":new["release_sequence"],
                "streamHistoriesRetained":sum(bool(x["observations"]) for x in streams),
                "logoSourceHistoriesRetained":sum(bool(x["observations"]) for x in logos),
                "missingLogoRowsRetained":sum(bool(x["observedDate"]) for x in missing_rows),
                "recoveryHistoriesRetained":sum(bool(x["observations"]) for x in recovery),
                "repairHistoriesRetained":sum(bool(x["observations"]) for x in new_c["records"]),
                "repairHistoryDeferredForReconciliation":len(confirmation["records"])-len(new_c["records"])}}
