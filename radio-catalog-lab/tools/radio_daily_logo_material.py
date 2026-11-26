"""Bounded rehydration of confirmed artwork, in the unsigned preview only."""
import http.client
from urllib.parse import urlsplit
from radio_daily_v9_generator import BASELINE, digest
from radio_daily_baseline_verify import strict_json
from radio_daily_logo_plan import plan, stage
from radio_daily_missing_logo import candidates
from radio_daily_logo_maintenance import source_policy
from radio_daily_editorial_preview import homepage_url, related_host, fetch_html
from radio_daily_repair_preview import page_key
from radio_daily_maintenance_preview import digest as url_digest
from radio_catalog_logo_pilot_probe import fetch_strict_https, MAX_LOGO_BYTES

MAX_MATERIAL=4

def recover(raw,day,maintenance,missing,*,expected=BASELINE,fetch_page=fetch_html,fetch_image=fetch_strict_https):
    proposals,_=plan(raw,day,maintenance,missing,expected=expected)
    stations={s["go_station_id"]:s for s in strict_json(raw)["stations"]}
    result={}
    deferred=[]
    cache={}
    for i,p in enumerate(proposals):
        sid=p["goStationId"]
        reason="artwork_material_budget_held"
        if i>=MAX_MATERIAL:
            deferred.append({"goStationId":sid,"reason":reason})
            continue
        s=stations[sid]
        try:
            reason="artwork_page_unconfirmed"
            home=homepage_url(s.get("homepage"))
            if not home:
                raise ValueError("no homepage")
            final,body=fetch_page(home)
            if (homepage_url(final)!=final or not related_host(final,home) or page_key(final)!=page_key(home)
                    or not isinstance(body,bytes) or not 0<len(body)<=256*1024):
                raise ValueError("page not bound")
            if p["pageSha256"] and digest(body)!=p["pageSha256"]:
                raise ValueError("page changed")
            found=candidates(s,final,body)
            if len(found)!=1:
                raise ValueError("ambiguous image")
            source,kind=next(iter(found.items()))
            if kind!="typed_station_logo" or source_policy(source)!="eligible" or url_digest(source)!=p["sourceSha256"]:
                raise ValueError("source not confirmed")
            reason="artwork_object_unconfirmed"
            if source not in cache:
                data,mime=fetch_image(source,urlsplit(source).hostname)
                if not isinstance(data,bytes) or not 0<len(data)<=MAX_LOGO_BYTES:
                    raise ValueError("invalid object")
                cache[source]=(data,mime)
            data,mime=cache[source]
            if mime!=p["image"]["mime"]:
                raise ValueError("MIME changed")
            material={"pageUrl":final,"pageBytes":body,"sourceUrl":source,"imageBytes":data}
            stage(s,p,material)
            result[sid]=material
        except (ValueError,OSError,RuntimeError,TypeError,AttributeError,http.client.HTTPException):
            deferred.append({"goStationId":sid,"reason":reason})
    return result,deferred
