#!/usr/bin/env python3
"""Read-only research hint for named outdoor/unaddressed venues.

Some public squares, parks and temporary outdoor sites have no numbered
postal address. A DILA-confirmed official municipal page naming the exact
venue plus ONE named OSM object near a separately UID-bound OA/ODS source
may give a private REVIEW HINT. It is NEVER geographic proof for admission.
No whitelist of OSM amenity types, cities or venue names is maintained.
"""
import json
import math
from urllib.parse import urlsplit

from proof import meters, norm
from ptitesondes_dila_municipal_domains import approved_municipal_page_host
from ptitesondes_generic_venue_official_proof import (
    JSONLD, VENUE_TYPES, _nodes, _types,
)
from ptitesondes_generic_venue_visible_address import VisiblePostal

MAX_HTML = 350_000
MAX_SCRIPTS = 20
MAX_METERS = 65


def named_venue_html(group, html, object_center):
    """Exact, unique visible H1 or named structured Place on official page.

    Reject a conflicting structured Place, contradictory structured city,
    foreign address or official geo far from the OSM hint. No postal
    housenumber is needed because this NEVER mints a location proof.
    """
    if (not isinstance(group, dict) or not norm(group.get("venue"))
            or not norm(group.get("city")) or not isinstance(html, str)
            or not 30 <= len(html) <= MAX_HTML):
        return False
    parser = JSONLD()
    try:
        parser.feed(html)
        parser.close()
        if len(parser.blocks) >= MAX_SCRIPTS:
            return False
        same = []
        other_places = 0
        for block in parser.blocks:
            for node in _nodes(json.loads(block)):
                if not _types(node).intersection(VENUE_TYPES):
                    continue
                if norm(node.get("name")) == norm(group["venue"]):
                    same.append(node)
                    if len(same) > 1:
                        return False
                else:
                    other_places += 1
        if len(same) == 1:
            if other_places:
                return False
            node = same[0]
            adr = node.get("address")
            if adr is not None:
                if not isinstance(adr, dict):
                    return False
                city = adr.get("addressLocality")
                if city is not None and norm(city) != norm(group["city"]):
                    return False
                country = adr.get("addressCountry")
                if isinstance(country, dict):
                    country = country.get("name")
                if country is not None and norm(country) not in ("fr", "france"):
                    return False
            geo = node.get("geo")
            if geo is not None:
                if not isinstance(geo, dict):
                    return False
                try:
                    lat, lng = geo["latitude"], geo["longitude"]
                except KeyError:
                    return False
                if (type(lat) not in (float, int)
                        or type(lng) not in (float, int)
                        or not math.isfinite(lat) or not math.isfinite(lng)
                        or not -90 <= lat <= 90 or not -180 <= lng <= 180
                        or meters((lat, lng), object_center) > MAX_METERS):
                    return False
            return True
        if other_places:
            return False
        visible = VisiblePostal()
        visible.feed(html)
        visible.close()
        return (len(visible.headings) == 1
                and norm(visible.headings[0]) == norm(group["venue"]))
    except (ValueError, TypeError, KeyError, RecursionError, OverflowError):
        return False


def unnumbered_named_venue_hint(group, source_center, osm_response,
                                directory, official_url, official_html):
    """Correlate three source families for PRIVATE RESEARCH only.

    OA/ODS source point is untrusted; named OSM geometry is independent,
    and the municipal site must be independently authenticated with DILA.
    This DOES NOT attest a venue address, GPS, event or publication right.
    """
    base = {
        "status": "unnumbered_venue_hint_unverified",
        "official_name_correlated": False,
        "osm_geometry_correlated": False,
        "city_osm_tag_confirmed": False,
        "gps_verified": False,
        "official_venue_verified": False,
        "event_sessions_verified": False,
        "publication_ready": False,
        "public_writes": 0,
    }
    if (not isinstance(group, dict)
            or not isinstance(source_center, tuple)
            or len(source_center) != 2
            or any(type(x) not in (float, int) or not math.isfinite(x)
                   for x in source_center)
            or not -90 <= source_center[0] <= 90
            or not -180 <= source_center[1] <= 180
            or not isinstance(official_url, str)
            or approved_municipal_page_host(
                official_url, group.get("city"), directory) is None):
        return base
    try:
        # A municipality homepage is not a dedicated venue page.
        page = urlsplit(official_url)
        if page.path in ("", "/") or page.query or page.fragment:
            return base
        from ptitesondes_generic_venue_osm_preflight import osm_hints
        hints = osm_hints(group, source_center, osm_response)
        if len(hints) != 1:
            return base
        point = (hints[0]["lat_unverified"], hints[0]["lng_unverified"])
        if not named_venue_html(group, official_html, point):
            return base
        return {
            **base,
            "status": "named_municipal_venue_and_osm_hint_private_review",
            "official_name_correlated": True,
            "osm_geometry_correlated": True,
            "city_osm_tag_confirmed": hints[0]["city_tag_confirmed"],
        }
    except (ValueError, TypeError, KeyError, RecursionError, OverflowError):
        return base


__all__ = ["unnumbered_named_venue_hint", "named_venue_html"]
