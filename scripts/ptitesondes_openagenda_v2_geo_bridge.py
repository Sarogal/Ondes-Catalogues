"""Generic independent venue geocoding preflight for P'tites Ondes.

Never geocode from an OpenAgenda candidate alone. Inputs must come from:
1) a separately PINNED institutional HTTPS venue page fetched by a trusted
   caller without redirects (the lead and OpenAgenda cannot supply the pin);
2) a separately fetched IGN/BAN GeoJSON result for that page's exact address;
3) an OpenAgenda location checked only against those independent sources.

This PURE adapter performs zero I/O, approval, event patching or publication.
The caller must still authenticate the institution and rights independently.
"""
import ipaddress
import json
import math
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit, parse_qs

from proof import meters, norm
from ptitesondes_openagenda_v2_direct_evidence import _french_location

SCHEMA = "ptitesondes.oa2.independent_venue_geocode.v1"
MAX_HTML = 450_000
MAX_FEATURES = 20
MAX_JSONLD = 30
MAX_DISTANCE_METERS = 65
ALLOWED_PLACE_TYPES = frozenset({
    "Place", "CivicStructure", "Library", "Museum", "LocalBusiness",
    "PerformingArtsTheater", "CommunityCenter", "EventVenue",
    "TouristAttraction", "SportsActivityLocation",
})


def _url(raw, host=None, path=None):
    if not isinstance(raw, str) or len(raw) > 1800:
        return None
    try:
        u = urlsplit(raw)
        h = (u.hostname or "").lower()
        if (u.scheme != "https" or not h or u.username or u.password
                or u.port not in (None, 443) or u.fragment
                or not re.fullmatch(r"[a-z0-9.-]+", h)
                or h in ("localhost", "openagenda.com", "api.openagenda.com",
                         "public.opendatasoft.com")
                or h.endswith((".local", ".internal", ".openagenda.com",
                               ".opendatasoft.com"))):
            return None
        try:
            ipaddress.ip_address(h)
            return None
        except ValueError:
            pass
        if host is not None and h != host:
            return None
        if path is not None and u.path != path:
            return None
        return u
    except ValueError:
        return None


class _LD(HTMLParser):
    """Parse bounded, explicitly typed JSON-LD from the pinned page only."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.active = False
        self.parts = []
        self.blocks = []

    def handle_starttag(self, tag, attrs):
        if tag != "script":
            return
        attrs = dict(attrs)
        if str(attrs.get("type") or "").lower().strip() == "application/ld+json":
            self.active = True
            self.parts = []

    def handle_data(self, data):
        if self.active:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.active:
            if len(self.blocks) < MAX_JSONLD:
                self.blocks.append("".join(self.parts))
            self.parts = []
            self.active = False


def _nodes(raw):
    """Bounded nonrecursive traversal of document and @graph collections."""
    pending = [raw]
    emitted = 0
    while pending and emitted < MAX_JSONLD:
        node = pending.pop()
        if isinstance(node, list):
            pending.extend(reversed(node[:MAX_JSONLD]))
        elif isinstance(node, dict):
            yield node
            emitted += 1
            graph = node.get("@graph")
            if isinstance(graph, list):
                pending.extend(reversed(graph[:MAX_JSONLD]))


def _types(node):
    values = node.get("@type", []) if isinstance(node, dict) else []
    if isinstance(values, str):
        values = [values]
    return {item.rsplit("/", 1)[-1] for item in values
            if isinstance(item, str)} if isinstance(values, list) else set()


def _place_candidates(node):
    """Only explicit Place nodes, including Event.location typed as Place."""
    if _types(node) & ALLOWED_PLACE_TYPES:
        yield node
    if any(t == "Event" or t.endswith("Event") for t in _types(node)):
        nested = node.get("location")
        locations = nested if isinstance(nested, list) else [nested]
        for place in locations[:MAX_JSONLD]:
            if isinstance(place, dict) and _types(place) & ALLOWED_PLACE_TYPES:
                yield place


def _place_address(html, venue, city):
    if not isinstance(html, str) or not 60 <= len(html) <= MAX_HTML:
        return None
    parser = _LD()
    try:
        parser.feed(html)
        parser.close()
    except (TypeError, ValueError):
        return None
    # A municipality can repeat the SAME address for several sessions while
    # listing distinct alternate names. Only divergent physical addresses
    # are contradictory: aliases at one address are combined.
    matching = {}
    for block in parser.blocks:
        try:
            data = json.loads(block)
        except (ValueError, TypeError):
            continue
        for item in _nodes(data):
            for node in _place_candidates(item):
                names = [node.get("name")]
                aliases = node.get("alternateName", [])
                names += aliases if isinstance(aliases, list) else [aliases]
                names = {norm(x) for x in names
                         if isinstance(x, str) and norm(x)}
                if not names or norm(venue) not in names:
                    continue
                address = node.get("address")
                if not isinstance(address, dict):
                    continue
                locality = address.get("addressLocality")
                street = address.get("streetAddress")
                postcode = address.get("postalCode")
                country = address.get("addressCountry")
                if (not isinstance(locality, str) or norm(locality) != norm(city)
                        or not isinstance(street, str)
                        or not re.fullmatch(r"[0-9]{1,4}[a-zA-Z]?\s+.+", street)
                        or not isinstance(postcode, str)
                        or not re.fullmatch(r"(?:[0-9]{5}|97[0-9]{3})", postcode)
                        or country not in ("FR", "France")):
                    continue
                number = re.fullmatch(
                    r"([0-9]{1,4}[a-zA-Z]?)\s+(.+)", street.strip())
                if number:
                    address_key = (number.group(1), number.group(2),
                                   postcode, locality)
                    matching.setdefault(address_key, set()).update(names)
    if len(matching) != 1:
        return None
    address, known_names = next(iter(matching.items()))
    return (*address, tuple(sorted(known_names)))


def review_independent_geo(lead, api_event, reviewed_source,
                           official_page, geocoder_request_url, geojson):
    """Check independently sourced NAME+ADDRESS+BAN+OA point; no admission."""
    base = {
        "schema": SCHEMA, "geo_evidence_consistent": False,
        "registered_venue": None,
        "publisher_connected": False, "approval_granted": False,
        "public_writes": 0, "reason": "not_verified",
    }
    def hold(reason):
        return dict(base, reason=reason)

    if not isinstance(lead, dict) or not isinstance(api_event, dict):
        return hold("invalid_event_inputs")
    if (not isinstance(reviewed_source, dict)
            or set(reviewed_source) != {"approved_host", "exact_url"}
            or not isinstance(official_page, dict)
            or set(official_page) != {"url", "html"}):
        return hold("missing_reviewed_institution")
    host = reviewed_source.get("approved_host")
    pinned = _url(reviewed_source.get("exact_url"), host=host)
    if (pinned is None or not isinstance(host, str)
            or official_page.get("url") != reviewed_source["exact_url"]):
        return hold("source_not_independently_pinned")
    source_address = _place_address(
        official_page.get("html"), lead.get("venue"), lead.get("city"))
    if source_address is None:
        return hold("official_address_not_exact_or_ambiguous")
    house, street, postcode, city, aliases = source_address
    req = _url(geocoder_request_url, host="data.geopf.fr",
               path="/geocodage/search")
    if req is None:
        return hold("invalid_geocoder_provenance")
    args = parse_qs(req.query, keep_blank_values=True)
    target = f"{house} {street} {postcode} {city}"
    if (set(args) - {"q", "limit"} or len(args.get("q", [])) != 1
            or norm(args["q"][0]) != norm(target)
            or (args.get("limit") and args["limit"] != ["2"])):
        return hold("geocoder_query_not_official_address")
    if (not isinstance(geojson, dict) or geojson.get("type") != "FeatureCollection"
            or not isinstance(geojson.get("features"), list)
            or len(geojson["features"]) > MAX_FEATURES):
        return hold("invalid_geocoder_response")
    loc = api_event.get("location")
    if (not isinstance(loc, dict) or not _french_location(loc)
            or norm(loc.get("name")) not in aliases
            or norm(lead.get("venue")) not in aliases
            or norm(lead.get("city")) != norm(loc.get("adminLevel4"))):
        return hold("event_venue_city_or_country_conflict")
    coords = []
    for feature in geojson["features"]:
        if not isinstance(feature, dict):
            continue
        p = feature.get("properties")
        geom = feature.get("geometry")
        if (not isinstance(p, dict) or not isinstance(geom, dict)
                or p.get("type") != "housenumber"
                or type(p.get("score")) not in (int, float)
                or not math.isfinite(p["score"]) or p["score"] < 0.90
                or str(p.get("housenumber", "")).casefold() != house.casefold()
                or norm(p.get("street")) != norm(street)
                or p.get("postcode") != postcode
                or norm(p.get("city")) != norm(city)
                or not isinstance(p.get("citycode"), str)
                or not re.fullmatch(r"(?:\d{5}|2[AB]\d{3})", p["citycode"])
                or geom.get("type") != "Point"
                or not isinstance(geom.get("coordinates"), list)
                or len(geom["coordinates"]) != 2):
            continue
        lon, lat = geom["coordinates"]
        if (not all(type(v) in (int, float) and math.isfinite(v)
                    for v in (lon, lat))
                or not -180 <= lon <= 180 or not -90 <= lat <= 90
                or (lon == 0 and lat == 0)):
            continue
        coords.append((lat, lon))
    if not coords:
        return hold("no_exact_housenumber_geocode")
    if any(meters(coords[0], other) > 3 for other in coords[1:]):
        return hold("ambiguous_geocoded_housenumber")
    reference = coords[0]
    point = (loc.get("latitude"), loc.get("longitude"))
    if (not all(type(x) in (int, float) and math.isfinite(x) for x in point)
            or meters(reference, point) > MAX_DISTANCE_METERS):
        return hold("openagenda_point_not_matched_to_ban")
    registered = {
        "city": city,
        "aliases": list(aliases),
        "lat": reference[0], "lng": reference[1],
    }
    return dict(base, geo_evidence_consistent=True,
                registered_venue=registered,
                reason="independent_address_and_ban_match_other_gates_pending")


def review_direct_with_independent_geo(
        lead, api_event, reviewed_agenda, reviewed_source,
        official_page, geocoder_request_url, geojson, today):
    """Compose independent GPS with API v2 structural checks, read-only.

    This is a DIAGNOSTIC bridge, not a production replacement for the venue
    registry or a source-rights/access/age approval. In particular, an
    official institution and BAN never prove an event's organizer or license.
    """
    geo = review_independent_geo(
        lead, api_event, reviewed_source, official_page,
        geocoder_request_url, geojson,
    )
    result = {
        "schema": "ptitesondes.oa2.direct_geo_diagnostic.v1",
        "geography_verified": geo["geo_evidence_consistent"] is True,
        "direct_source_structurally_valid": False,
        "publisher_connected": False,
        "approval_granted": False, "public_writes": 0,
    }
    if not geo["geo_evidence_consistent"]:
        return dict(result, reason=geo["reason"])
    from ptitesondes_openagenda_v2_direct_evidence import review_direct_v2
    direct = review_direct_v2(
        lead, api_event, reviewed_agenda, geo["registered_venue"], today,
    )
    # The returned message contains ONLY a fixed producer-owned reason;
    # never include source URLs, UID, title, API payload, key, coordinates.
    return dict(
        result,
        direct_source_structurally_valid=(
            direct.get("source_evidence_structurally_valid") is True
        ),
        reason=direct.get("reason", "direct_structure_unverified"),
    )
