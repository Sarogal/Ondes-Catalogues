#!/usr/bin/env python3
"""Generic independent IGN/BAN address corroboration of OSM venue hints.

The event collector provides only the search center. OSM named objects may
supply independent *hints*, then IGN/BAN rechecks the exact street address.
This cannot certify an OFFICIAL venue or an event. No publisher access.
"""
import json
import math
import re
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler

from proof import meters, norm

SCHEMA = "ptitesondes.generic_venue_ign_corroboration.v1"
ENDPOINT = "https://data.geopf.fr/geocodage/search"
MAX_BYTES = 100_000
MIN_SCORE = 0.95
MAX_DISTANCE_M = 65
HOUSE = re.compile(r"[0-9]{1,4}(?:[ -]?(?:bis|ter|quater|[a-z]))?", re.I)
POSTCODE = re.compile(r"[0-9]{5}")
MAX_FEATURES = 2


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _address_text(value, size):
    return (isinstance(value, str) and 1 <= len(value.strip()) <= size
            and not any(ord(char) < 32 or ord(char) == 127 for char in value)
            and norm(value) != "")


def address_candidate(group, osm_record):
    """Parse explicit address tags. Never reverse-geocode an approximate dot."""
    if not isinstance(group, dict) or not isinstance(osm_record, dict):
        return None
    city, venue = group.get("city"), group.get("venue")
    if not _address_text(city, 120) or not _address_text(venue, 180):
        return None
    tags = osm_record.get("tags")
    if (not isinstance(tags, dict)
            or norm(tags.get("name")) != norm(venue)
            or (tags.get("addr:city") and
                norm(tags["addr:city"]) != norm(city))):
        return None
    number = tags.get("addr:housenumber")
    street = tags.get("addr:street")
    postcode = tags.get("addr:postcode")
    if (not isinstance(number, str) or not HOUSE.fullmatch(number.strip())
            or not _address_text(street, 120)
            or not isinstance(postcode, str)
            or not POSTCODE.fullmatch(postcode)):
        return None
    if not isinstance(osm_record.get("id"), int) or osm_record["id"] <= 0:
        return None
    typ = osm_record.get("type")
    if typ not in ("node", "way", "relation"):
        return None
    center = osm_record if typ == "node" else osm_record.get("center")
    if not isinstance(center, dict):
        return None
    try:
        lat, lon = float(center["lat"]), float(center["lon"])
    except (KeyError, ValueError, TypeError, OverflowError):
        return None
    if (not math.isfinite(lat) or not math.isfinite(lon)
            or not -90 <= lat <= 90 or not -180 <= lon <= 180):
        return None
    address = f"{number.strip()} {street.strip()} {postcode} {city.strip()}"
    return {
        "city": city, "venue": venue, "postcode": postcode,
        "housenumber": number.strip(), "street": street.strip(),
        "address_query": address,
        "lat_osm_hint": lat, "lng_osm_hint": lon,
        "osm_object_hint": f"{typ}/{osm_record['id']}",
    }


def ign_url(candidate):
    if not isinstance(candidate, dict):
        raise ValueError("invalid_candidate")
    q = candidate.get("address_query")
    if not _address_text(q, 300):
        raise ValueError("invalid_address_query")
    return ENDPOINT + "?" + urlencode({"q": q, "limit": 2})


def fetch_ign(candidate, opener=None):
    """Fixed host, strict no-redirect fetch and limited bytes."""
    url = ign_url(candidate)
    getter = opener or build_opener(NoRedirect()).open
    with getter(Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "PtitesOndesPrivateIGNCorroboration/1.0 (read-only)",
    }), timeout=18) as response:
        if response.status != 200 or response.geturl() != url:
            raise ValueError("noncanonical_ign_response")
        content = response.read(MAX_BYTES + 1)
    if not content or len(content) > MAX_BYTES:
        raise ValueError("oversized_ign_response")
    return json.loads(content)


def verify_ign(candidate, data, source_center=None):
    """Return a private independent-address diagnostic, never an approval."""
    bad = {"status": "ign_address_unverified", "address_correlated": False,
           "gps_verified": False, "official_venue_verified": False,
           "publication_ready": False}
    if not isinstance(candidate, dict) or not isinstance(data, dict):
        return bad
    features = data.get("features")
    if (data.get("type") != "FeatureCollection"
            or not isinstance(features, list)
            or len(features) > MAX_FEATURES):
        return bad
    try:
        osm = (float(candidate["lat_osm_hint"]),
               float(candidate["lng_osm_hint"]))
        if (not all(math.isfinite(v) for v in osm)
                or not -90 <= osm[0] <= 90 or not -180 <= osm[1] <= 180):
            return bad
        if source_center is not None:
            if (not isinstance(source_center, tuple) or len(source_center) != 2
                    or not all(type(x) in (float, int) and math.isfinite(x)
                               for x in source_center)):
                return bad
        hits = 0
        for f in features:
            if not isinstance(f, dict) or f.get("type") != "Feature":
                continue
            p, geo = f.get("properties"), f.get("geometry")
            if not isinstance(p, dict) or not isinstance(geo, dict):
                continue
            score = p.get("score")
            if (p.get("type") != "housenumber"
                    or p.get("postcode") != candidate["postcode"]
                    or norm(p.get("housenumber")) != norm(candidate["housenumber"])
                    or norm(p.get("city")) != norm(candidate["city"])
                    or norm(p.get("label")) != norm(candidate["address_query"])
                    or type(score) not in (float, int) or not math.isfinite(score)
                    or not MIN_SCORE <= score <= 1):
                continue
            coords = geo.get("coordinates")
            if (geo.get("type") != "Point" or not isinstance(coords, list)
                    or len(coords) != 2
                    or not all(type(x) in (float, int) and math.isfinite(x)
                               for x in coords)
                    or not -180 <= coords[0] <= 180
                    or not -90 <= coords[1] <= 90):
                continue
            ban = (float(coords[1]), float(coords[0]))
            if meters(ban, osm) > MAX_DISTANCE_M:
                continue
            if (source_center is not None
                    and meters(ban, source_center) > MAX_DISTANCE_M):
                continue
            hits += 1
        if hits == 1:
            return {**bad, "status": "ign_exact_address_correlated_official_site_unchecked",
                    "address_correlated": True}
    except (KeyError, ValueError, TypeError, OverflowError):
        pass
    return bad


def corroborate_osm_records(group, response, source_center, ign_fetch=fetch_ign):
    """One unambiguous named OSM feature; require explicit postal address."""
    from ptitesondes_generic_venue_osm_preflight import osm_hints
    hints = osm_hints(group, source_center, response)
    result = {"status": "no_unambiguous_osm_address",
              "address_correlated": False, "gps_verified": False,
              "official_venue_verified": False, "publication_ready": False,
              "ign_requests": 0}
    if len(hints) != 1:
        return result
    target = hints[0]["osm_object_hint"]
    typ, oid = target.split("/")
    records = [r for r in response["elements"]
               if isinstance(r, dict) and r.get("type") == typ
               and r.get("id") == int(oid)]
    if len(records) != 1:
        return result
    candidate = address_candidate(group, records[0])
    if candidate is None:
        return {**result, "status": "osm_street_address_incomplete"}
    try:
        verified = verify_ign(candidate, ign_fetch(candidate), source_center)
    except (OSError, ValueError, TypeError, KeyError, UnicodeError):
        return {**result, "status": "ign_source_unavailable", "ign_requests": 1}
    return {**result, **verified, "ign_requests": 1,
            **({"address_candidate_private": candidate}
               if verified["address_correlated"] is True else {})}
