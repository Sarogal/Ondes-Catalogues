"""Independently locate a named physical event site without an OSM URL in JSON-LD.

The first-party EVENT already proves a named site, French postal address,
date, lineup and genre. Only if its direct OSM link is absent, corroborate the
*exact postal street* via France's BAN (IGN Géoplateforme), then look for a
single, identically named OSM node or way near that verified street address.
No BAN point, neighbourhood centroid, generic map pin or similarly named
feature is by itself a site approval. This is intentionally bounded to a tiny
map extent and only runs on already qualified individual official events.
"""
from __future__ import annotations

import json
import math
import re
from urllib.parse import urlencode
from xml.etree import ElementTree

import triage
import osm_read_only_fallback as readonly

BAN = "https://data.geopf.fr/geocodage/search/"
OSM_MAP = "https://api.openstreetmap.org/api/0.6/map"
OSM_PUBLIC = "https://www.openstreetmap.org"
# Bounded < 200m box; no city-wide map queries or city centroid fallback.
LAT_HALF = 0.00065
LON_HALF = 0.00110
MAX_DISTANCE_METERS = 95


def require(ok, reason):
    if not ok:
        raise ValueError("Independent BAN/OSM site: " + reason)


def clean(value):
    return triage.words(value)


def _street_parts(value):
    text = str(value or "").strip()
    match = re.match(r"^([0-9]{1,4}(?:\s*(?:bis|ter|quater|[a-z]))?)\s+(.+)$",
                     text, flags=re.I)
    if not match:
        return None, clean(text)
    return clean(match[1]), clean(match[2])


def _distance_meters(lat1, lon1, lat2, lon2):
    radius = 6371008.8
    a1, a2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((a2-a1)/2)**2
         + math.cos(a1)*math.cos(a2)
         *math.sin(math.radians(lon2-lon1)/2)**2)
    return 2*radius*math.asin(min(1, math.sqrt(a)))


def _geo(valid):
    return (isinstance(valid, (list, tuple)) and len(valid) == 2
            and all(type(x) in (int, float) and math.isfinite(x)
                    for x in valid)
            and -180 <= valid[0] <= 180 and -56 <= valid[1] <= 52)


def _ban_result(site, fetch, *, include_region=False, min_score=0.89):
    # A lower bound is permissible only to RESEARCH a government-matched
    # exact address; the publisher continues to call the 0.89 default.
    require(type(min_score) in (int, float) and math.isfinite(min_score)
            and 0.75 <= min_score <= 0.99,
            "invalid French address confidence policy")
    postcode = site["postalCode"]
    city = site["city"]
    house, street = _street_parts(site["address"])
    require(street and len(street) >= 4 and re.fullmatch(r"\d{5}", postcode),
            "incomplete official postal address")
    params = urlencode({
        "q": f"{site['address']} {postcode} {city}, France",
        "limit": 5, "autocomplete": 0,
    })
    url = BAN + "?" + params
    body, final = fetch(url, 130_000)
    require(final == url and isinstance(body, str) and len(body) <= 130_000,
            "French government address lookup unavailable")
    report = json.loads(body)
    require(isinstance(report, dict)
            and isinstance(report.get("features"), list)
            and len(report["features"]) <= 5,
            "ambiguous or invalid government response")
    eligible = []
    for item in report["features"]:
        if not isinstance(item, dict):
            continue
        props, geom = item.get("properties"), item.get("geometry")
        if not isinstance(props, dict) or not isinstance(geom, dict):
            continue
        coords = geom.get("coordinates")
        if not _geo(coords) or geom.get("type") != "Point":
            continue
        if (props.get("postcode") != postcode
                or clean(props.get("city")) != clean(city)
                or clean(props.get("street")) != street
                or props.get("type") not in ("housenumber", "street")
                or type(props.get("score")) not in (int, float)
                or not math.isfinite(props["score"])
                or props["score"] < min_score):
            continue
        if house:
            if props["type"] != "housenumber" or clean(
                    props.get("housenumber")) != house:
                continue
        else:
            if props["type"] != "street":
                continue
        eligible.append(((coords[1], coords[0]), props.get("context")))
    require(len(eligible) == 1, "one exact government street address required")
    center, context = eligible[0]
    if not include_region:
        return center
    # Government BAN context: "<department>, <department name>, <region>"
    # (in some overseas departments the region is also the department).
    # Unlike the untrusted event page this is an independent, exact-address
    # and high-score government response. Never guess the region from city.
    require(isinstance(context, str) and len(context) <= 180,
            "independent government region unavailable")
    parts = [x.strip() for x in context.split(",")]
    dept = str(site.get("department") or "").upper()
    require(len(parts) in (2, 3) and parts[0].upper() == dept
            and (len(parts) == 3 or dept.startswith(("97", "98"))),
            "independent government department mismatch")
    region = parts[-1]
    require(3 <= len(region) <= 90
            and all(ch.isalpha() or ch in " -'" for ch in region),
            "independent government region invalid")
    return center, region


def independently_attested_region(site, fetch):
    """A missing OPTIONAL first-party region can be sourced from exact BAN.

    Return the validated region and exact-address point for optional
    cross-checking of the separately named OSM feature; no city centroid,
    approximate match or postcode-only inference is accepted.
    """
    return _ban_result(site, fetch, include_region=True)


def _node_tags(obj):
    return {t.get("k"): t.get("v") for t in obj.findall("tag")
            if t.get("k") and t.get("v")}


def _osm_map(site, center, fetch):
    lat, lon = center
    require(-56 <= lat <= 52 and -180 <= lon <= 180,
            "address geocode outside territorial bounds")
    bbox = ",".join(f"{v:.6f}" for v in (
        lon-LON_HALF, lat-LAT_HALF, lon+LON_HALF, lat+LAT_HALF))
    url = OSM_MAP + "?bbox=" + bbox
    try:
        body, final = fetch(url, 650_000)
    except (ValueError, OSError, TimeoutError):
        # OpenStreetMap's editing API can be unavailable/robots-protected
        # for unattended public runners. The read-only Overpass request
        # covers the SAME tiny bbox, including referenced nodes for ways.
        fallback = readonly.nearby(
            lat-LAT_HALF, lon-LON_HALF, lat+LAT_HALF, lon+LON_HALF)
        body, final = fetch(fallback, 650_000)
        url = fallback
    require(final == url and isinstance(body, str)
            and len(body) <= 650_000
            and "<!DOCTYPE" not in body.upper()
            and "<!ENTITY" not in body.upper(),
            "OSM map unavailable or unsafe")
    root = ElementTree.fromstring(body)
    require(root.tag == "osm" and root.get("version") == "0.6",
            "OSM feature collection invalid")
    nodes = {}
    for n in root.findall("node"):
        ident = n.get("id")
        if not ident or not ident.isdigit():
            continue
        try:
            nla, nlo = float(n.get("lat")), float(n.get("lon"))
        except (ValueError, TypeError):
            continue
        if _geo((nlo, nla)):
            nodes[ident] = (nla, nlo)
    house, official_street = _street_parts(site["address"])
    matches = []
    for kind in ("node", "way"):
        for feature in root.findall(kind):
            ident = feature.get("id")
            if not ident or not ident.isdigit() or int(ident) < 1:
                continue
            tags = _node_tags(feature)
            if (clean(tags.get("name")) != clean(site["name"])
                    or clean(tags.get("addr:city")) != clean(site["city"])
                    or tags.get("addr:postcode") != site["postalCode"]
                    or tags.get("addr:country", "FR").upper() != "FR"):
                continue
            if (tags.get("addr:street")
                    and clean(tags["addr:street"]) != official_street):
                continue
            if house and tags.get("addr:housenumber") and clean(
                    tags["addr:housenumber"]) != house:
                continue
            if kind == "node":
                position = nodes.get(ident)
            else:
                references = [nd.get("ref") for nd in feature.findall("nd")]
                unique = list(dict.fromkeys(references))
                refs = [nodes.get(x) for x in unique]
                position = (sum(x[0] for x in refs) / len(refs),
                            sum(x[1] for x in refs) / len(refs)) if (
                                len(refs) >= 3 and all(refs)) else None
            if position and _distance_meters(
                    lat, lon, position[0], position[1]) <= MAX_DISTANCE_METERS:
                matches.append((
                    f"{OSM_PUBLIC}/{kind}/{ident}",
                    position[0], position[1],
                    "named-site-point" if kind == "node" else "named-site-area",
                ))
    require(len(matches) == 1,
            "one independent named OSM feature at exact address required")
    return matches[0]


def verify(site, fetch, *, min_score=0.89):
    """The caller must have verified a single dated first-party Event beforehand.

    fetch(url, byte_cap) -> (body, final_url); the production fetch honours
    HTTPS, robots restrictions, and exact destination URLs. This module does
    not grant concert approvals and has no arbitrary host/URL input.
    """
    require(isinstance(site, dict) and all(
        isinstance(site.get(field), str) and site[field].strip()
        for field in ("name", "city", "address", "postalCode", "region")),
        "official event site identity absent")
    center = _ban_result(site, fetch, min_score=min_score)
    return _osm_map(site, center, fetch)
