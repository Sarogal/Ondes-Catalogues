"""Rehydrate confirmed repair URLs only in the current unsigned preview process."""
import http.client
from radio_daily_v9_generator import BASELINE
from radio_daily_baseline_verify import strict_json
from radio_daily_repair_plan import plan
from radio_daily_repair_preview import match, PAGE_SIZE
from radio_daily_repair_confirmation import confirm_page, MAX_CHECKS
from radio_daily_editorial_preview import homepage_url, fetch_html
from radio_catalog_daily_candidate_reconcile import index_catalog
from radio_daily_discovery import fetch_page, resolve_api_mirrors
from radio_stream_technical_probe import validate_endpoint


def recover(raw,maintenance,repair,confirmation,report,*,expected=BASELINE,search=None,fetch=None):
    if plan(raw,maintenance,repair,confirmation,expected=expected)!=report:
        raise ValueError("repair material plan mismatch")
    proposals=report["proposals"]
    if not proposals:
        return {},[]
    if len(proposals)>MAX_CHECKS:
        return {},[{"reason":"repair_material_budget_held"}]
    if search is None or fetch is None:
        raise ValueError("explicit repair material services required")
    doc=strict_json(raw)
    stations={s["go_station_id"]:s for s in doc["stations"]}
    owners,_,_=index_catalog(doc)
    occupied={u for s in doc["stations"] for v in s["streams"] for u in [v["url"],*v.get("previous_urls",[])]}
    result={}
    deferred=[]
    for p in proposals:
        sid,sha,uid=p["goStationId"],p["streamSha256"],p["stationuuid"]
        station=stations[sid]
        reason="directory_material_held"
        try:
            if station["status"].get("reason_code")=="synthetic_diagnostic_not_for_playback":
                raise ValueError("synthetic station")
            rows=search(station["display_name"])
            if not isinstance(rows,list) or len(rows)>=PAGE_SIZE or any(not isinstance(x,dict) for x in rows):
                raise ValueError("incomplete directory response")
            urls=set()
            for row in rows:
                h=match(station,row,owners,occupied)
                if h and h["stationuuid"]==uid and h["streamSha256"]==sha:
                    urls.add(row.get("url_resolved") or row.get("url") or row.get("streamUrl"))
            reason="replacement_fingerprint_not_found"
            if len(urls)!=1:
                raise ValueError("replacement mismatch")
            url=next(iter(urls))
            reason="unsafe_replacement_material"
            parsed=validate_endpoint(url)
            if parsed.query or parsed.fragment:
                raise ValueError("query or fragment")
            reason="broadcaster_material_unconfirmed"
            mode,_,_=confirm_page(station,homepage_url(station.get("homepage")),url,fetch)
            if not mode:
                raise ValueError("broadcaster no longer confirms")
            result[(sid,sha)]=url
            occupied.add(url)
        except (ValueError,OSError,RuntimeError,TypeError,AttributeError,http.client.HTTPException):
            deferred.append({"goStationId":sid,"streamSha256":sha,"reason":reason})
    return result,deferred


def live_recover(raw,maintenance,repair,confirmation,report):
    hosts=None
    def search(name):
        nonlocal hosts
        if hosts is None:
            hosts=resolve_api_mirrors()[:2]
        return fetch_page(hosts,"name",name,0,PAGE_SIZE)
    return recover(raw,maintenance,repair,confirmation,report,search=search,fetch=fetch_html)
