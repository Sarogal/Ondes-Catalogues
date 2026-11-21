#!/usr/bin/env python3
"""Independent official-place-address -> IGN/BAN geocoding, private only.

Alternative to OSM-first discovery: a page hosted on a DILA-authenticated
municipal domain may explicitly identify a named venue and postal address.
IGN/BAN must independently locate THAT EXACT address within 65 m of the
untrusted but UID-bound OpenAgenda/ODS source point. Nothing is published.
"""
import json
import math
import re
from html.parser import HTMLParser

from proof import meters, norm
from ptitesondes_dila_municipal_domains import approved_municipal_page_host
from ptitesondes_generic_venue_official_proof import JSONLD, VENUE_TYPES, _nodes, _types
from ptitesondes_generic_venue_visible_address import VisiblePostal
from ptitesondes_generic_venue_ign_corroboration import (
    HOUSE, POSTCODE, MIN_SCORE, MAX_FEATURES, MAX_DISTANCE_M,
)

STREET_ADDRESS = re.compile(
    r"^\s*([0-9]{1,4}(?:[ -]?(?:bis|ter|quater|[a-z]))?)\s+(.{3,120}?)\s*$",
    re.I,
)
VISIBLE_ADDRESS = re.compile(
    r"^\s*([0-9]{1,4}(?:[ -]?(?:bis|ter|quater|[a-z]))?)\s+"
    r"(.{3,120}?)\s*,?\s+(\d{5})\s+(.{2,120}?)\s*$", re.I,
)


def _candidate(group, number, street, postcode, city):
    if (not isinstance(group, dict) or not isinstance(city, str)
            or not isinstance(street, str) or not isinstance(number, str)
            or not isinstance(postcode, str)
            or HOUSE.fullmatch(number) is None
            or POSTCODE.fullmatch(postcode) is None
            or norm(city) != norm(group.get("city"))
            or not norm(group.get("venue"))):
        return None
    value = f"{number} {street} {postcode} {city}"
    if len(value) > 300 or not norm(street):
        return None
    return {"city": group["city"], "venue": group["venue"],
            "housenumber": number, "street": street, "postcode": postcode,
            "address_query": value}


_FRENCH_LINK_WORDS = frozenset(("de", "du", "des", "la", "le", "les",
                               "l", "d", "et", "a", "au", "aux"))


def _official_heading_matches(heading, venue):
    """Exact title or its printed French acronym, never a fuzzy place name."""
    if norm(heading) == norm(venue):
        return True
    match = re.fullmatch(r"(.+?)\s+\(([A-Za-zÀ-ÿ]{2,10})\)\s*", heading)
    if not match or norm(match.group(1)) != norm(venue):
        return False
    words = [w for w in norm(venue).split() if w not in _FRENCH_LINK_WORDS]
    acronym = "".join(w[0] for w in words)
    return len(acronym) >= 2 and norm(match.group(2)) == acronym


class _MunicipalHeadingText(HTMLParser):
    """Visible H1-associated text, excluding unrelated sections and footer."""
    HIDDEN = frozenset(("script", "style", "noscript", "template", "svg",
                        "iframe", "footer", "nav"))

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.nodes = 0
        self.head = None
        self.text = []
        self.in_heading = False
        self.sections = []

    def _finish(self):
        if self.head is not None:
            self.sections.append(
                (" ".join(self.head).strip(), " ".join(self.text).strip()))

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
            self.head, self.text = [], []
            self.in_heading = True

    def handle_data(self, data):
        if self.hidden or self.head is None:
            return
        target = self.head if self.in_heading else self.text
        if sum(map(len, target)) <= 10000:
            target.append(" ".join(data.split()))

    def handle_endtag(self, tag):
        if tag in self.HIDDEN:
            self.hidden = max(0, self.hidden - 1)
        elif not self.hidden and tag in ("h1", "h2", "h3"):
            self.in_heading = False


def _municipal_visible_numbered_address(group, html):
    """Recover an official numbered address even without an <address> tag.

    Municipality pages can display an exact titled building and its street
    address in ordinary page text. This fallback does NOT accept arbitrary
    venues or coordinates: DILA authorization and exact BAN check still apply.
    """
    if (not isinstance(group, dict) or not isinstance(html, str)
            or not 30 <= len(html) <= 350000
            or not norm(group.get("city")) or not norm(group.get("venue"))):
        return None
    parser = _MunicipalHeadingText()
    try:
        parser.feed(html)
        parser.close()
        parser._finish()
        city = group["city"]
        pattern = re.compile(
            r"(?<!\w)([0-9]{1,4}(?:[ -]?(?:bis|ter|quater|[a-z]))?)\s+"
            r"([^\d,]{3,100}?)\s*,?\s+([0-9]{5})\s+"
            + re.escape(city) + r"(?:\b|$)", re.IGNORECASE)
        addresses = []
        for heading, body in parser.sections:
            if not _official_heading_matches(heading, group["venue"]):
                continue
            pairs = pattern.findall(body[:350])
            # One address per named section; conflicting ones fail closed.
            if len(pairs) != 1:
                return None
            number, street, postcode = pairs[0]
            candidate = _candidate(group, number, street.strip(), postcode, city)
            if candidate is None:
                return None
            addresses.append(candidate)
        if addresses and len({
                norm(x["address_query"]) for x in addresses}) == 1:
            return addresses[0]
    except (TypeError, ValueError, KeyError, RecursionError, OverflowError):
        return None
    return None


def extract_official_address(group, html):
    """No URL discovery or language-model inference; explicit place identity."""
    if not isinstance(html, str) or not 30 <= len(html) <= 350000:
        return None
    parser = JSONLD()
    try:
        parser.feed(html)
        parser.close()
    except (TypeError, ValueError, RecursionError):
        return None
    # JSONLD caps the number of stored blocks; reaching that cap makes
    # uniqueness unverifiable, so never certify a potentially truncated page.
    if len(parser.blocks) >= 20:
        return None
    matches = []
    other_place_nodes = 0
    try:
        for block in parser.blocks:
            for node in _nodes(json.loads(block)):
                if _types(node).intersection(VENUE_TYPES):
                    if norm(node.get("name")) == norm(group.get("venue")):
                        matches.append(node)
                        if len(matches) > 1:
                            return None
                    else:
                        other_place_nodes += 1
    except (ValueError, TypeError, RecursionError):
        return None
    if len(matches) == 1:
        adr = matches[0].get("address")
        if not isinstance(adr, dict):
            return None
        country = adr.get("addressCountry")
        if country is not None and norm(
                country.get("name") if isinstance(country, dict) else country
        ) not in ("fr", "france"):
            return None
        m = STREET_ADDRESS.fullmatch(str(adr.get("streetAddress") or ""))
        if m is None:
            return None
        candidate = _candidate(
            group, m.group(1), m.group(2),
            adr.get("postalCode"), adr.get("addressLocality"))
        if candidate is None:
            return None
        geo = matches[0].get("geo")
        if geo is not None:
            if not isinstance(geo, dict):
                return None
            try:
                lat, lon = float(geo["latitude"]), float(geo["longitude"])
            except (ValueError, KeyError, TypeError, OverflowError):
                return None
            if (not math.isfinite(lat) or not math.isfinite(lon)
                    or not -90 <= lat <= 90 or not -180 <= lon <= 180):
                return None
            candidate["official_coordinates_hint"] = (lat, lon)
        return candidate
    if len(matches) > 1 or other_place_nodes:
        return None
    # No contradictory schema.org Place: accept only one visible exact
    # heading and one semantic <address> block. Hidden/footer text excluded.
    p = VisiblePostal()
    try:
        p.feed(html)
        p.close()
    except (TypeError, ValueError, RecursionError):
        return None
    if (len(p.headings) == 1 and len(p.addresses) == 1
            and norm(p.headings[0]) == norm(group.get("venue"))):
        m = VISIBLE_ADDRESS.fullmatch(p.addresses[0])
        if m is not None:
            return _candidate(group, m.group(1), m.group(2), m.group(3), m.group(4))
    return _municipal_visible_numbered_address(group, html)


def confirm_official_address_ban(group, source_center, directory,
                                  page_url, html, ign_fetch):
    """Return a private diagnostic, NEVER an attested publisher venue."""
    base = {"status": "official_address_ban_unverified",
            "independent_geo_correlated": False,
            "official_venue_verified_for_publisher": False,
            "gps_verified_for_publisher": False,
            "event_sessions_verified": False,
            "publication_ready": False, "public_writes": 0}
    if (not isinstance(group, dict)
            or not isinstance(source_center, tuple)
            or len(source_center) != 2
            or not all(type(x) in (int, float) and math.isfinite(x)
                       for x in source_center)
            or not -90 <= source_center[0] <= 90
            or not -180 <= source_center[1] <= 180
            or approved_municipal_page_host(
                page_url, group.get("city"), directory) is None):
        return base
    candidate = extract_official_address(group, html)
    if candidate is None:
        return {**base, "status": "official_name_or_address_missing"}
    try:
        data = ign_fetch(candidate)
    except (OSError, ValueError, TypeError, KeyError, TimeoutError):
        return {**base, "status": "ban_source_unavailable"}
    if not isinstance(data, dict) or data.get("type") != "FeatureCollection":
        return base
    features = data.get("features")
    if not isinstance(features, list) or len(features) > MAX_FEATURES:
        return base
    matches = 0
    for feature in features:
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            continue
        prop = feature.get("properties")
        geo = feature.get("geometry")
        if not isinstance(prop, dict) or not isinstance(geo, dict):
            continue
        score = prop.get("score")
        if (prop.get("type") != "housenumber"
                or prop.get("postcode") != candidate["postcode"]
                or norm(prop.get("housenumber")) != norm(candidate["housenumber"])
                or norm(prop.get("city")) != norm(candidate["city"])
                or norm(prop.get("label")) != norm(candidate["address_query"])
                or type(score) not in (int, float)
                or not math.isfinite(score) or not MIN_SCORE <= score <= 1):
            continue
        coordinates = geo.get("coordinates")
        if (geo.get("type") != "Point" or not isinstance(coordinates, list)
                or len(coordinates) != 2
                or not all(type(x) in (int, float) and math.isfinite(x)
                           for x in coordinates)
                or not -180 <= coordinates[0] <= 180
                or not -90 <= coordinates[1] <= 90):
            continue
        point = (coordinates[1], coordinates[0])
        if meters(point, source_center) > MAX_DISTANCE_M:
            continue
        if ("official_coordinates_hint" in candidate and
                meters(point, candidate["official_coordinates_hint"])
                > MAX_DISTANCE_M):
            continue
        matches += 1
    if matches != 1:
        return base
    return {**base, "status": "official_address_ban_source_private_review",
            "independent_geo_correlated": True,
            "corroboration_method": "municipal_official_address_plus_ban_uid_center"}
