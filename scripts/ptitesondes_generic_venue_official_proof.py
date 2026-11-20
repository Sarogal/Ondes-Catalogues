#!/usr/bin/env python3
"""Fail-closed official-place identity crosscheck on independently trusted pages.

Input is a venue page downloaded by an independently authenticated caller,
not a lead/OSM-suggested "website" and not the OpenAgenda event page.
Never approves a specific session or writes to any public registry.
"""
from html.parser import HTMLParser
import json
import math
import re
from urllib.parse import urlsplit

from proof import norm, meters

SCHEMA = "ptitesondes.generic_official_venue_identity.v1"
MAX_HTML = 350_000
MAX_SCRIPTS = 20
MAX_NODES = 120
MAX_DISTANCE_M = 65
NON_OFFICIAL_HOSTS = frozenset((
    "openagenda.com", "public.opendatasoft.com",
    "data.geopf.fr", "www.openstreetmap.org",
))
VENUE_TYPES = frozenset((
    "place", "localbusiness", "civicstructure", "library",
    "museum", "park", "performingartstheater", "touristattraction",
    "communitycentre", "educationalorganization", "artsorganization",
    "musicvenue", "childcare",
))


class JSONLD(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_script = False
        self.parts = []
        self.blocks = []

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            attrs = dict(attrs)
            self.in_script = ((attrs.get("type") or "").lower().strip()
                              == "application/ld+json")
            self.parts = []

    def handle_data(self, data):
        if self.in_script:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.in_script:
            if len(self.blocks) < MAX_SCRIPTS:
                self.blocks.append("".join(self.parts))
            self.parts = []
            self.in_script = False


def _host(url):
    if not isinstance(url, str):
        return None
    try:
        p = urlsplit(url)
        if (p.scheme != "https" or not p.hostname or p.username or p.password
                or p.port not in (None, 443) or p.fragment
                or len(p.path) > 300 or p.hostname in NON_OFFICIAL_HOSTS):
            return None
        return p.hostname
    except ValueError:
        return None


def _types(node):
    labels = node.get("@type", [])
    if isinstance(labels, str):
        labels = [labels]
    if not isinstance(labels, list):
        return set()
    return {str(v).rstrip("/").split("/")[-1].lower()
            for v in labels if isinstance(v, str)}


def _nodes(data):
    """Bound depth and node count; only @graph nesting is considered."""
    pending = [data]
    yielded = 0
    while pending:
        value = pending.pop()
        if isinstance(value, list):
            pending.extend(value[:MAX_NODES])
        elif isinstance(value, dict):
            yielded += 1
            if yielded > MAX_NODES:
                raise ValueError("unbounded_schema")
            yield value
            if "@graph" in value:
                pending.append(value["@graph"])


def _address_ok(candidate, value):
    if not isinstance(value, dict):
        return False
    if not {"streetAddress", "postalCode", "addressLocality"} <= value.keys():
        return False
    street = candidate["housenumber"] + " " + candidate["street"]
    if (norm(value.get("streetAddress")) != norm(street)
            or value.get("postalCode") != candidate["postcode"]
            or norm(value.get("addressLocality")) != norm(candidate["city"])):
        return False
    country = value.get("addressCountry")
    if country is not None:
        if isinstance(country, dict):
            country = country.get("name")
        if norm(country) not in ("fr", "france"):
            return False
    return True


def _geo_ok(candidate, node):
    geo = node.get("geo")
    if geo is None:
        return True
    if not isinstance(geo, dict):
        return False
    try:
        lat, lng = float(geo["latitude"]), float(geo["longitude"])
        point = (float(candidate["lat_osm_hint"]),
                 float(candidate["lng_osm_hint"]))
    except (ValueError, KeyError, TypeError, OverflowError):
        return False
    return (all(math.isfinite(x) for x in (lat, lng) + point)
            and -90 <= lat <= 90 and -180 <= lng <= 180
            and meters((lat, lng), point) <= MAX_DISTANCE_M)


def official_venue_page_proof(group, candidate, ign_evidence, page_url,
                              html, approved_official_hosts):
    """Requires independent BAN corroboration AND previously trusted host.

    The host must be approved OUTSIDE candidate discovery, never taken from
    OSM's website=* tag or the organizer's OpenAgenda event alone.
    """
    result = {
        "schema": SCHEMA, "official_identity_verified": False,
        "location_evidence_complete_for_private_review": False,
        "event_sessions_verified": False, "publication_ready": False,
        "public_writes": 0, "status": "insufficient_independent_place_evidence",
    }
    if (not isinstance(group, dict) or not isinstance(candidate, dict)
            or not isinstance(ign_evidence, dict)
            or ign_evidence.get("address_correlated") is not True
            or ign_evidence.get("publication_ready") is not False
            or ign_evidence.get("gps_verified") is not False
            or not isinstance(approved_official_hosts, (tuple, frozenset))
            or not approved_official_hosts
            or any(not isinstance(x, str) or not x or x != x.lower()
                   or "/" in x or "." not in x
                   for x in approved_official_hosts)):
        return result
    host = _host(page_url)
    if host is None or host not in approved_official_hosts:
        return {**result, "status": "official_host_not_independently_approved"}
    if (not isinstance(html, str) or not 30 <= len(html) <= MAX_HTML):
        return {**result, "status": "official_page_missing_or_too_large"}
    try:
        if (norm(group["city"]) != norm(candidate["city"])
                or norm(group["venue"]) != norm(candidate["venue"])
                or not norm(candidate["venue"])):
            return result
    except (KeyError, ValueError, TypeError):
        return result
    parser = JSONLD()
    try:
        parser.feed(html)
        parser.close()
    except (ValueError, TypeError):
        return result
    if len(parser.blocks) >= MAX_SCRIPTS:
        return {**result, "status": "too_many_structured_blocks"}
    same_name_nodes = []
    other_structured_places = 0
    try:
        for block in parser.blocks:
            value = json.loads(block)
            for node in _nodes(value):
                if _types(node).intersection(VENUE_TYPES):
                    if norm(node.get("name")) == norm(group["venue"]):
                        same_name_nodes.append(node)
                        if len(same_name_nodes) > 2:
                            return {**result, "status": "ambiguous_named_place"}
                    else:
                        other_structured_places += 1
    except (ValueError, TypeError, RecursionError):
        return result
    if len(same_name_nodes) == 0:
        if other_structured_places:
            return {**result, "status": "different_structured_place_identity"}
        # Some genuine institutional venue pages contain only semantic
        # visible H1 + postal <address>, not schema.org Place. This narrow
        # fallback never overrides contradictory structured Place evidence.
        from ptitesondes_generic_venue_visible_address import (
            visible_venue_identity_matches,
        )
        if visible_venue_identity_matches(group, candidate, html):
            return {**result, "status": "official_visible_name_address_private_review",
                    "official_identity_verified": True,
                    "location_evidence_complete_for_private_review": True}
        return {**result, "status": "named_place_missing_or_ambiguous"}
    if len(same_name_nodes) != 1:
        return {**result, "status": "named_place_missing_or_ambiguous"}
    node = same_name_nodes[0]
    addresses = node.get("address")
    if not _address_ok(candidate, addresses) or not _geo_ok(candidate, node):
        return {**result, "status": "official_address_or_geo_conflict"}
    # Checks one named place at one exact post address on a previously
    # authenticated official venue host, not event dates or family audience.
    return {**result, "status": "independent_location_evidence_private_review",
            "official_identity_verified": True,
            "location_evidence_complete_for_private_review": True}
