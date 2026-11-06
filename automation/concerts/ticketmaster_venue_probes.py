"""Ticketmaster Discovery API v2: bounded named-venue probes, leads only.

Official API permits venue search and event filtering by venueId. Since
generic keyword/category queries sometimes yield zero French events, this
rotates a *small* approved venue list. Never invents a venueId, never queries
more than two calls per venue, never treats a ticket as venue corroboration.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import unicodedata
import urllib.error
import urllib.parse

ROOT = "https://app.ticketmaster.com/discovery/v2/"
SCHEMA = "grossesondes.concert.ticketmaster-venue-probes.v1"


def norm(text):
    value = unicodedata.normalize("NFKD", str(text or "")).casefold()
    return re.sub(r"[^a-z0-9]+", "", value.encode("ascii", "ignore").decode())


def city_name(venue):
    city=venue.get("city") or {}
    return city.get("name", "") if isinstance(city,dict) else str(city)


def venue_matches(raw, config):
    if not isinstance(raw, dict):
        return False
    name=norm(raw.get("name"))
    aliases={norm(x) for x in config.get("aliases",[])}
    aliases.add(norm(config.get("name")))
    country=(raw.get("country") or {}).get("countryCode")
    postal=str(raw.get("postalCode") or "").strip()
    expected=str(config.get("postalCode") or "").strip()
    return (
        bool(raw.get("id")) and name in aliases and
        norm(city_name(raw))==norm(config.get("city")) and country=="FR" and
        (not expected or not postal or postal==expected)
    )


def selected_venues(config, catalogue, today):
    if config.get("schema")!=SCHEMA or not isinstance(config.get("venues"),list):
        raise ValueError("Registre Ticketmaster ciblé invalide")
    venues={x["id"]:x for x in catalogue.get("venues",[])}
    options=config["venues"]
    if not options or len(options)>12:
        raise ValueError("Trop de sondes Ticketmaster")
    for item in options:
        ref=venues.get(item.get("id"))
        if not ref or norm(ref.get("city"))!=norm(item.get("city")) or norm(ref.get("name"))!=norm(item.get("name")):
            raise ValueError("Sonde hors du catalogue de salles vérifiées")
    n=min(2,max(1,int(config.get("maxVenuesPerRun",2))))
    start=(today.toordinal()*n)%len(options)
    return [options[(start+i)%len(options)] for i in range(min(n,len(options)))]


def build_url(kind, params, key):
    if kind not in ("venues","events"):
        raise ValueError("Endpoint Ticketmaster non autorisé")
    return ROOT+kind+".json?"+urllib.parse.urlencode({
        **params,"apikey":key
    })


def probe(config, catalogue, key, today, request, to_candidate, known):
    """Injected request(url) returns JSON; do not log URLs carrying API key."""
    if not key:
        return [],[{"status":"not_configured","kind":"venue_probe"}]
    candidates, diagnostics=[],[]
    for item in selected_venues(config,catalogue,today):
        line={"kind":"ticketmaster_venue_probe","venueId":item["id"],
              "venueName":item["name"],"matchedVenueCount":0,
              "eventsReturned":0,"candidates":0}
        try:
            url=build_url("venues",{
                "keyword":item["name"],"countryCode":"FR",
                "size":"50","page":"0"},key)
            payload=request(url)
            if not isinstance(payload,dict) or payload.get("fault"):
                raise ValueError("Réponse recherche de salle invalide")
            raw_venues=((payload.get("_embedded") or {}).get("venues") or [])
            if not isinstance(raw_venues,list):
                raise ValueError("Réponse salles invalide")
            exact={str(x["id"]):x for x in raw_venues
                   if venue_matches(x,item)}
            line["matchedVenueCount"]=len(exact)
            # Ambiguous names and multiple platform IDs cannot be safely
            # interpreted as the same physical venue. Hold instead.
            if len(exact)!=1:
                line["status"]="not_indexed_or_ambiguous"
                diagnostics.append(line)
                continue
            official_id=next(iter(exact))
            # Never search by a generic city alone: only the verified API
            # venueId, keeping searches tight and low-cost.
            url=build_url("events",{
                "venueId":official_id,"countryCode":"FR",
                "size":"100","page":"0"},key)
            payload=request(url)
            if not isinstance(payload,dict) or payload.get("fault"):
                raise ValueError("Réponse concerts de salle invalide")
            raw_events=((payload.get("_embedded") or {}).get("events") or [])
            if not isinstance(raw_events,list):
                raise ValueError("Réponse événements invalide")
            line["eventsReturned"]=len(raw_events)
            for raw in raw_events:
                if not isinstance(raw,dict):
                    continue
                embedded=(raw.get("_embedded") or {}).get("venues") or []
                if not any(str(v.get("id"))==official_id and
                           venue_matches(v,item) for v in embedded):
                    continue
                lead=to_candidate(raw,known,today.isoformat())
                if lead is None:
                    continue
                lead["sourceConfidence"]="Billetterie Ticketmaster — salle correspondante, programmation/genre à contrôler auprès de la salle"
                lead["venueCatalogueId"]=item["id"]
                lead["ticketmasterVenueId"]=official_id
                lead["publicationAllowed"]=False
                lead["reviewRequired"]=True
                candidates.append(lead)
                line["candidates"]+=1
            line["status"]="venue_indexed"
        except urllib.error.HTTPError as exc:
            line["status"]="http_error"
            line["httpStatus"]=exc.code
        except Exception as exc:
            # Never leak a key through HTTP error URLs.
            line["status"]="error"
            line["errorType"]=type(exc).__name__
        diagnostics.append(line)
    return candidates,diagnostics
