#!/usr/bin/env python3
"""Private, no-housenumber geographic proof for named outdoor venues.

Requires *independent* municipality provenance (DILA), a unique structured
named venue with explicit official coordinates, and a unique exact-name OSM
geometry in the same location as a UID-bound OpenAgenda/ODS event hint.
No numbered postal address, street-type allowlist or publisher is required.
One source can never certify itself; all doubts remain review candidates.
"""
import json
import re
from html.parser import HTMLParser

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


class _VisibleVenueAddressSections(HTMLParser):
    """Read named sections; never use footer, script or unrelated addresses."""

    HIDDEN = frozenset(("script", "style", "noscript", "template",
                        "svg", "iframe", "nav", "footer"))

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.nodes = 0
        self.heading = None
        self.body = []
        self.in_heading = False
        self.sections = []

    def _finish(self):
        if self.heading is not None:
            self.sections.append((
                " ".join(self.heading).strip(),
                " ".join(self.body).strip(),
            ))

    def handle_starttag(self, tag, attrs):
        if tag in self.HIDDEN:
            self.hidden += 1
            return
        if self.hidden:
            return
        self.nodes += 1
        if self.nodes > 3500:
            raise ValueError("too_many_visible_nodes")
        if tag in ("h1", "h2", "h3"):
            self._finish()
            self.heading, self.body = [], []
            self.in_heading = True

    def handle_data(self, data):
        if self.hidden or self.heading is None:
            return
        target = self.heading if self.in_heading else self.body
        if sum(map(len, target)) <= 10000:
            target.append(" ".join(data.split()))

    def handle_endtag(self, tag):
        if tag in self.HIDDEN:
            self.hidden = max(0, self.hidden - 1)
        elif not self.hidden and tag in ("h1", "h2", "h3"):
            self.in_heading = False


def _visible_unnumbered_official_address(group, html):
    """One exact venue heading + street and postcode; not a map coordinate.

    Municipality websites frequently use an H2 for a facility and state
    "Place de la Gare 62220 Carvin" rather than a numbered <address> or
    JSON-LD GeoCoordinates. Exact identity and a separate named OSM feature
    are still mandatory before a geographic proof can be minted.
    """
    if (not isinstance(group, dict) or not isinstance(html, str)
            or not 30 <= len(html) <= MAX_HTML
            or not norm(group.get("city")) or not norm(group.get("venue"))):
        return None
    try:
        # A conflicting structured Place must never be bypassed through text.
        structured = JSONLD()
        structured.feed(html)
        structured.close()
        if len(structured.blocks) >= 20:
            return None
        for block in structured.blocks:
            for node in _nodes(json.loads(block)):
                if _types(node).intersection(VENUE_TYPES):
                    return None
        parser = _VisibleVenueAddressSections()
        parser.feed(html)
        parser.close()
        parser._finish()
        city = group["city"]
        pattern = re.compile(
            r"^([^\W\d_][\wÀ-ÿ .'\-’]{2,100}?)\s*,?\s+"
            r"([0-9]{5})\s+" + re.escape(city) + r"(?:\b|$)",
            re.IGNORECASE,
        )
        addresses = set()
        matched = False
        for heading, body in parser.sections:
            if norm(heading) != norm(group["venue"]):
                continue
            matched = True
            found = pattern.search(body[:250])
            if found is None:
                return None
            street, postcode = found.group(1).strip(), found.group(2)
            # A house-numbered address belongs to the original BAN verifier.
            if re.match(r"^\d", street):
                return None
            addresses.add((norm(street), postcode))
        if matched and len(addresses) == 1:
            street_norm, postcode = next(iter(addresses))
            return {"street_normalized": street_norm, "postcode": postcode}
    except (ValueError, TypeError, KeyError, RecursionError, OverflowError):
        return None
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
        # Non-numbered municipal address: independent named OSM building
        # point + exact municipal street/postcode + UID-bound OA/ODS centre.
        # NEVER use a street's approximate BAN centroid as a venue point.
        official_address = _visible_unnumbered_official_address(
            group, official_html)
        if official_address is None:
            return None
        try:
            from ptitesondes_generic_venue_osm_preflight import osm_hints
            hits = osm_hints(group, source_center, osm_response)
            if len(hits) != 1:
                return None
            obj_id = hits[0]["osm_object_hint"]
            objects = [
                entry for entry in osm_response["elements"]
                if isinstance(entry, dict)
                and "%s/%s" % (entry.get("type"), entry.get("id")) == obj_id
            ]
            if len(objects) != 1:
                return None
            tags = objects[0].get("tags")
            if (not isinstance(tags, dict)
                    or norm(tags.get("name")) != norm(group["venue"])
                    or norm(tags.get("addr:street"))
                    != official_address["street_normalized"]
                    or str(tags.get("addr:postcode")) != official_address["postcode"]
                    or (tags.get("addr:city")
                        and norm(tags["addr:city"]) != norm(group["city"]))):
                return None
            point = (hits[0]["lat_unverified"], hits[0]["lng_unverified"])
            if meters(point, source_center) > MAX_GEO_DELTA_M:
                return None
            return VenueLocationProof(
                group["city"], group["venue"], *point, checked_on,
                official_url, _SEAL,
                method="dila_official_street_plus_named_osm",
            )
        except (ValueError, TypeError, KeyError, OverflowError):
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
