"""Reusable named-venue GPS from a DILA municipality's event location block.

Some municipal schedules give "Le Liberté // L'Étage", then a separate
"Adresse — 1 esplanade Charles-de-Gaulle" rather than a JSON-LD Place or
postal code. An exact named venue + unnumbered-postcode municipal street
address can be independently crosschecked against BAN. No city, domain,
venue, or street-type allowlist. Not proof of event dates or publication.
"""
from datetime import date
from html.parser import HTMLParser
import math
import re
from urllib.parse import urlsplit

from proof import meters, norm
from ptitesondes_dila_municipal_domains import approved_municipal_page_host
from ptitesondes_generic_venue_ign_corroboration import (
    MIN_SCORE, MAX_FEATURES, MAX_DISTANCE_M, HOUSE,
)
from ptitesondes_shared_venue_location_evidence import (
    VenueLocationProof, _SEAL, _coordinates,
)

MAX_HTML = 350_000
MAX_NODES = 3500
HIDDEN = frozenset(("script", "style", "noscript", "template", "svg",
                    "iframe", "footer", "nav"))


class _MunicipalEventLocation(HTMLParser):
    """Only visible main/article body; explicitly labelled Adresse section."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.node_count = 0
        self.content_depth = 0
        self.in_address_heading = False
        self.address_heading = []
        self.in_address = False
        self.address_parts = []
        self.address_sections = []
        self.visible_parts = []

    def _hidden(self):
        return bool(self.stack and self.stack[-1][1])

    def handle_starttag(self, tag, attrs):
        self.node_count += 1
        if self.node_count > MAX_NODES:
            raise ValueError("municipal_event_page_too_many_nodes")
        data = dict(attrs)
        hidden = (self._hidden() or tag in HIDDEN or "hidden" in data
                  or str(data.get("aria-hidden") or "").lower() == "true"
                  or re.search(r"display\s*:\s*none|visibility\s*:\s*hidden",
                               str(data.get("style") or "").lower()) is not None)
        # HTML void tags never have closing tags; don't hide later sections.
        if tag not in ("area", "base", "br", "col", "embed", "hr", "img",
                       "input", "link", "meta", "param", "source",
                       "track", "wbr"):
            self.stack.append((tag, hidden))
        if not hidden and tag in ("main", "article"):
            self.content_depth += 1
        if not hidden and self.content_depth:
            if tag in ("h1", "h2", "h3"):
                if self.in_address:
                    self.address_sections.append(" ".join(self.address_parts))
                self.address_parts = []
                self.in_address = False
                self.address_heading = []
                self.in_address_heading = True
            if tag in ("a", "button") and self.in_address:
                # A navigation link (such as "Itinéraire") is never part
                # of the address and must not expand the BAN query.
                if self.address_parts:
                    self.address_sections.append(" ".join(self.address_parts))
                    self.address_parts = []
                self.in_address = False

    def handle_data(self, data):
        if self._hidden() or not self.content_depth:
            return
        part = " ".join(data.split())
        if not part:
            return
        if len(self.visible_parts) < 5000:
            self.visible_parts.append(part)
        if self.in_address_heading:
            self.address_heading.append(part)
        elif self.in_address and len(self.address_parts) < 70:
            self.address_parts.append(part)

    def handle_endtag(self, tag):
        if self.content_depth and tag in ("h1", "h2", "h3"):
            self.in_address_heading = False
            self.in_address = norm(" ".join(self.address_heading)) == "adresse"
        if tag in ("main", "article") and self.content_depth:
            self.content_depth -= 1
            if self.content_depth == 0 and self.in_address:
                self.address_sections.append(" ".join(self.address_parts))
                self.in_address = False
        for n in range(len(self.stack) - 1, -1, -1):
            if self.stack[n][0] == tag:
                del self.stack[n:]
                break


def _visible_venue_street(group, html):
    if (not isinstance(group, dict) or not norm(group.get("venue"))
            or not norm(group.get("city")) or not isinstance(html, str)
            or not 30 <= len(html) <= MAX_HTML):
        return None
    parser = _MunicipalEventLocation()
    try:
        parser.feed(html)
        parser.close()
        body = norm(" ".join(parser.visible_parts))
        name = norm(group["venue"])
        if not re.search(r"(?<![a-z0-9])" + re.escape(name)
                         + r"(?![a-z0-9])", body):
            return None
        if len(parser.address_sections) != 1:
            return None
        # Only explicit house number + one named street. The postcode may be
        # omitted by city webpages; the independently checked BAN response
        # must return its canonical postcode and precise street point.
        raw = parser.address_sections[0].strip()
        match = re.fullmatch(
            r"([0-9]{1,4}(?:[ -]?(?:bis|ter|quater|[a-z]))?)"
            r"\s+([\wÀ-ÿ .,'’\-]{3,120})", raw, re.I)
        if not match or HOUSE.fullmatch(match.group(1)) is None:
            return None
        street = match.group(2).strip()
        if len(norm(street)) < 4:
            return None
        return {"housenumber": match.group(1), "street": street,
                "city": group["city"],
                "address_query": (match.group(1) + " " + street + " "
                                  + group["city"])}
    except (TypeError, ValueError, RecursionError, OverflowError):
        return None


def mint_municipal_event_location_proof(
        group, directory, municipal_url, official_html, ign_fetch,
        checked_on, source_center):
    """Factory-only private venue proof, no publication or date validation."""
    if (not isinstance(group, dict) or type(checked_on) is not date
            or not callable(ign_fetch)
            or approved_municipal_page_host(
                municipal_url, group.get("city"), directory) is None
            or (source_center is not None
                and _coordinates(source_center) is None)):
        return None
    # A city homepage is not an independent, dedicated venue/event record.
    try:
        url = urlsplit(municipal_url)
        if url.path in ("", "/") or url.query or url.fragment:
            return None
    except (TypeError, ValueError):
        return None
    # Without an OA centre, refuse a BAN coordinate unless its INSEE city
    # code also matches the independently authenticated DILA municipality.
    # This prevents a same-name town or neighboring commune being mistaken
    # for the address, even when the source itself has no GPS hint.
    citycode = None
    if source_center is None:
        rows = directory.get("results") if isinstance(directory, dict) else None
        if not isinstance(rows, list):
            return None
        codes = set(
            row.get("code_insee_commune") for row in rows
            if isinstance(row, dict)
            and norm(row.get("nom")) == norm("Mairie - " + group["city"])
            and isinstance(row.get("code_insee_commune"), str)
            and re.fullmatch(r"[0-9]{5}", row["code_insee_commune"]))
        if len(codes) != 1:
            return None
        citycode = next(iter(codes))
    address = _visible_venue_street(group, official_html)
    if address is None:
        return None
    try:
        geo = ign_fetch(address)
    except (OSError, TimeoutError, KeyError, TypeError, ValueError):
        return None
    if not isinstance(geo, dict) or geo.get("type") != "FeatureCollection":
        return None
    features = geo.get("features")
    if not isinstance(features, list) or len(features) > MAX_FEATURES:
        return None
    matches = []
    for row in features:
        if not isinstance(row, dict) or row.get("type") != "Feature":
            continue
        props, geometry = row.get("properties"), row.get("geometry")
        if not isinstance(props, dict) or not isinstance(geometry, dict):
            continue
        score = props.get("score")
        if (props.get("type") != "housenumber"
                or norm(props.get("city")) != norm(group["city"])
                or (citycode is not None and props.get("citycode") != citycode)
                or norm(props.get("street")) != norm(address["street"])
                or norm(props.get("housenumber"))
                != norm(address["housenumber"])
                or type(props.get("postcode")) is not str
                or not re.fullmatch(r"[0-9]{5}", props["postcode"])
                or type(score) not in (int, float)
                or not math.isfinite(score)
                or not MIN_SCORE <= score <= 1):
            continue
        raw = geometry.get("coordinates")
        point = (raw[1], raw[0]) if (
            geometry.get("type") == "Point"
            and isinstance(raw, list) and len(raw) == 2) else None
        if point is None or _coordinates(point) is None:
            continue
        if (source_center is not None
                and meters(point, source_center) > MAX_DISTANCE_M):
            continue
        matches.append(point)
    if len(matches) != 1:
        return None
    return VenueLocationProof(
        group["city"], group["venue"], *matches[0], checked_on,
        municipal_url, _SEAL, method="dila_municipal_event_address_plus_ban",
    )


__all__ = ["mint_municipal_event_location_proof"]
