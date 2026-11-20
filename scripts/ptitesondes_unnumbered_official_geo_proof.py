#!/usr/bin/env python3
"""Private, no-housenumber geographic proof for named outdoor venues.

Requires *independent* municipality provenance (DILA), a unique structured
named venue with explicit official coordinates, and a unique exact-name OSM
geometry in the same location as a UID-bound OpenAgenda/ODS event hint.
No numbered postal address, street-type allowlist or publisher is required.
One source can never certify itself; all doubts remain review candidates.
"""
import json

from datetime import date
from urllib.parse import urlsplit

from proof import meters, norm
from ptitesondes_generic_venue_official_proof import (
    JSONLD, VENUE_TYPES, _nodes, _types,
)
from ptitesondes_dila_municipal_domains import approved_municipal_page_host
from ptitesondes_shared_venue_location_evidence import (
    VenueLocationProof, _SEAL, _coordinates,
)
from ptitesondes_unnumbered_venue_osm_official_hint import (
    named_venue_html, unnumbered_named_venue_hint,
)

MAX_GEO_DELTA_M = 65
MAX_HTML = 350_000


def _exact_official_point(group, html):
    """Only a single exact-name JSON-LD Place with explicit valid geo."""
    if not isinstance(html, str) or not 30 <= len(html) <= MAX_HTML:
        return None
    parser = JSONLD()
    try:
        parser.feed(html)
        parser.close()
        if len(parser.blocks) >= 20:
            return None
        same, others = [], 0
        for block in parser.blocks:
            for node in _nodes(json.loads(block)):
                if not _types(node).intersection(VENUE_TYPES):
                    continue
                if norm(node.get("name")) == norm(group.get("venue")):
                    same.append(node)
                else:
                    others += 1
        if len(same) != 1 or others:
            return None
        node = same[0]
        addr = node.get("address")
        if addr is not None:
            if not isinstance(addr, dict):
                return None
            city = addr.get("addressLocality")
            country = addr.get("addressCountry")
            if isinstance(country, dict):
                country = country.get("name")
            if (city is not None and norm(city) != norm(group.get("city"))) or (
                    country is not None and norm(country) not in ("fr", "france")):
                return None
        geo = node.get("geo")
        if not isinstance(geo, dict):
            return None
        return _coordinates((geo.get("latitude"), geo.get("longitude")))
    except (ValueError, TypeError, RecursionError, OverflowError, KeyError):
        return None


def mint_private_unnumbered_location_proof(
        group, directory, official_url, official_html,
        osm_response, source_center, checked_on):
    """Proof of the named place only; NEVER approval of a dated event.

    A named venue without a building number is never rejected for that fact.
    But a generic municipal home page, a missing official point, ambiguous
    OSM objects, mismatched city, or a reused source location is insufficient.
    """
    if (type(checked_on) is not date or not isinstance(group, dict)
            or not norm(group.get("city")) or not norm(group.get("venue"))
            or _coordinates(source_center) is None
            or not isinstance(official_url, str)
            or approved_municipal_page_host(
                official_url, group.get("city"), directory) is None):
        return None
    try:
        url = urlsplit(official_url)
    except ValueError:
        return None
    if url.path in ("", "/") or url.query or url.fragment:
        return None
    official_point = _exact_official_point(group, official_html)
    if official_point is None:
        return None
    # Detailed identity check also rejects conflicting Place nodes, and
    # official coordinates that disagree with the OSM candidate.
    if not named_venue_html(group, official_html, official_point):
        return None
    signal = unnumbered_named_venue_hint(
        group, source_center, osm_response, directory, official_url,
        official_html)
    if (signal.get("official_name_correlated") is not True
            or signal.get("osm_geometry_correlated") is not True):
        return None
    try:
        from ptitesondes_generic_venue_osm_preflight import osm_hints
        hits = osm_hints(group, source_center, osm_response)
    except (ValueError, TypeError, KeyError):
        return None
    if len(hits) != 1:
        return None
    independent_point = (hits[0]["lat_unverified"],
                         hits[0]["lng_unverified"])
    if (meters(official_point, independent_point) > MAX_GEO_DELTA_M
            or meters(official_point, source_center) > MAX_GEO_DELTA_M):
        return None
    return VenueLocationProof(
        group["city"], group["venue"], *official_point,
        checked_on, official_url, _SEAL,
        method="dila_official_geo_plus_named_osm",
    )
