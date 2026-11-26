#!/usr/bin/env python3
"""Digest-only artwork plan and explicit in-memory immutable object staging.

No upload, remote fetch or mutation of the signed catalogue is allowed.
A repeated change at an old URL is not by itself proof of logo identity.
"""
from urllib.parse import urlsplit
from radio_daily_v9_generator import BASELINE, digest, encode
from radio_daily_baseline_verify import strict_json
from radio_daily_maintenance_preview import age, digest as url_digest
from radio_daily_logo_maintenance import build as maintenance_build, MAX_SOURCES, valid_metadata, source_policy, source_reference
from radio_daily_missing_logo import build as missing_build, MAX_STATIONS, MAX_IMAGES, candidates, LOGO_KINDS
from radio_daily_editorial_preview import homepage_url, related_host
from radio_daily_repair_preview import page_key
from radio_catalog_logo_pilot_probe import decode_image, MAX_LOGO_BYTES

EXTENSIONS={"image/png":"png","image/jpeg":"jpg","image/webp":"webp"}
# Reserved example domain: the simulated descriptor cannot be a live endpoint.
PREVIEW_BASE="https://radio-preview.example.org/objects/sha256/"


def plan(raw, day, maintenance, missing, *, expected=BASELINE):
    for report in (maintenance,missing):
        if (report.get("scanDate")!=day or report.get("catalogChanged") is not False
                or report.get("publicationAllowed") is not False):
            raise ValueError("invalid artwork report")
    for report,key,cap in ((maintenance,"attemptedCount",MAX_SOURCES),
                           (missing,"attemptedStationCount",MAX_STATIONS),
                           (missing,"attemptedImageCount",MAX_IMAGES)):
        if type(report.get(key)) is not int or not 0<=report[key]<=cap:
            raise ValueError("invalid artwork budget")
    m=maintenance_build(raw,day,expected=expected,prior=maintenance)
    n=missing_build(raw,day,expected=expected,prior=missing)
    m["attemptedCount"]=maintenance["attemptedCount"]
    for key in ("attemptedStationCount","attemptedImageCount"):
        n[key]=missing[key]
    if m!=maintenance or n!=missing:
        raise ValueError("artwork report mismatch")
    old=strict_json(raw)
    stations={x["go_station_id"]:x for x in old["stations"]}
    sources={x["sourceSha256"]:x["observations"] for x in m["sources"]}
    proposals=[]
    deferred=[]
    for row in n["records"]:
        if row["confirmationStatus"]!="stable_typed_logo_review":
            continue
        sid=row["goStationId"]
        if age(day,row["observedDate"])>7:
            deferred.append({"goStationId":sid,"reason":"stale_logo_evidence"})
            continue
        proposals.append({"goStationId":sid,"operation":"attach_logo","sourceSha256":row["sourceSha256"],
            "image":row["image"],"dates":row["logoEvidenceDates"],"pageSha256":row["pageSha256"],
            "stationSha256":digest(encode(stations[sid]))})
    for row in m["records"]:
        if row["reviewStatus"]!="repeated_changed_image_review":
            continue
        sid=row["goStationId"]
        if stations[sid]["status"].get("reason_code")=="synthetic_diagnostic_not_for_playback":
            continue
        proposals.append({"goStationId":sid,"operation":"update_logo","sourceSha256":row["sourceSha256"],
            "image":sources[row["sourceSha256"]][-1]["image"],"dates":row["changedDates"],
            "pageSha256":None,"stationSha256":digest(encode(stations[sid]))})
    return sorted(proposals,key=lambda p:p["goStationId"]),deferred


def stage(station, proposal, material, *, decode=decode_image):
    """Require exact official declaration and actual decoded bytes for each delta."""
    if digest(encode(station))!=proposal["stationSha256"]:
        raise ValueError("artwork station mismatch")
    page=homepage_url(station.get("homepage"))
    final=material["pageUrl"]
    body=material["pageBytes"]
    source=material["sourceUrl"]
    data=material["imageBytes"]
    if (not page or homepage_url(final)!=final or not related_host(final,page)
            or page_key(final)!=page_key(page) or not isinstance(body,bytes)
            or not 0<len(body)<=256*1024 or source_policy(source)!="eligible"
            or url_digest(source)!=proposal["sourceSha256"]
            or len(found:=candidates(station,final,body))!=1
            or found.get(source) not in LOGO_KINDS):
        raise ValueError("artwork source not station bound")
    if proposal["pageSha256"] and digest(body)!=proposal["pageSha256"]:
        raise ValueError("artwork page changed")
    if not isinstance(data,bytes) or not 0<len(data)<=MAX_LOGO_BYTES:
        raise ValueError("invalid artwork object size")
    mime,width,height=decode(data)
    image={"imageSha256":digest(data),"mime":mime,"width":width,"height":height,"byteLength":len(data)}
    if not valid_metadata(image) or image!=proposal["image"]:
        raise ValueError("artwork object mismatch")
    previous=station["logo"]
    if (previous is None)!=(proposal["operation"]=="attach_logo"):
        raise ValueError("artwork operation mismatch")
    sha=image["imageSha256"]
    path=sha+"."+EXTENSIONS[mime]
    descriptor={"asset_id":"sha256:"+sha,"sha256":sha,"revision":previous["revision"]+1 if previous else 1,
        "url":PREVIEW_BASE+path,"byte_size":len(data),"width":width,"height":height,"mime_type":mime}
    # Refuse material that cannot retain its safe official provenance.
    source_reference(descriptor,source)
    return descriptor,path,data
