"""Read-only independent GPS check for any HTML-discovered family session.

This reuses the generic first-party Place JSON-LD and bounded IGN/BAN readers.
Crucially, the pinned *venue* URL and reference coordinates come only from
pre-reviewed, separate public registries; never from the candidate or search.
No OA event is required, and no venue or event may be admitted or published.
"""
import math
import re
from urllib.parse import urlsplit, quote

from ptitesondes_family_national_source_preflight import _Visibility
from ptitesondes_openagenda_v2_geo_fetch import GEO_ENDPOINT
from ptitesondes_openagenda_v2_geo_bridge import _LD, _nodes, _place_candidates

from proof import meters, norm
from ptitesondes_html_registry_history_triage import (
    _valid_venue, CONTEXT_KEYS,
)
from ptitesondes_openagenda_v2_geo_bridge import (
    _place_address, _url, MAX_FEATURES, MAX_DISTANCE_METERS,
)
from ptitesondes_openagenda_v2_geo_fetch import (
    fetch_official_page, fetch_ban_exact, ban_query_for_official_address,
)

SCHEMA = "ptitesondes.html_independent_venue_ban_readonly.v1"
COORDINATE_TOLERANCE_METERS = 3
MIN_BAN_SCORE = 0.90


def _result(reason, *, address=False, ban=False, venue=False,
            address_kind="none"):
    return {
        "schema": SCHEMA,
        "reason": reason,
        "official_venue_address_present": address,
        "venue_address_evidence_kind": address_kind,
        "independent_ban_housenumber_matched": ban,
        "registry_coordinates_concordant": venue,
        "geometry_evidence_consistent": bool(address and ban and venue),
        "registry_is_previously_reviewed_not_refetched": True,
        "event_session_attested": False,
        "organizer_ownership_attested": False,
        "family_age_access_verified": False,
        "rights_reviewed": False,
        "publisher_connected": False,
        "publication_ready": False,
        "approval_granted": False,
        "public_writes": 0,
    }


CONTACT_LABELS = frozenset({
    "contact", "contacts", "adresse", "coordonnees", "informations pratiques",
    "nous contacter", "acces",
})
STREET = re.compile(
    r"^(?P<number>[0-9]{1,4}(?:[a-z]| bis| ter| quater)?)\s+"
    r"(?P<street>(?:rue|route|avenue|boulevard|allee|allée|chemin|"
    r"impasse|place|quai|cours|passage|square|esplanade|montee|montée)"
    r"\s+.+)$", re.IGNORECASE)
POSTAL = re.compile(r"^(?P<postcode>[0-9]{5})\s+(?P<city>[^0-9]{2,80})$")


class _VisibleContacts(_Visibility):
    """Extract visible fragments, plus exact visible H1 identity.

    DOM is not an authority for the address: only one unique street/postcode
    pair in the contact area of a separately pinned venue page is eligible.
    """
    def __init__(self):
        super().__init__()
        self.headings = []
        self.fragments = []
        self._h1_parts = []
        self._in_h1 = False

    def handle_starttag(self, tag, attrs):
        hidden = super().handle_starttag(tag, attrs)
        if not hidden and tag == "h1" and not self._in_h1:
            self._in_h1 = True
            self._h1_parts = []

    def handle_data(self, data):
        if self._hidden():
            return
        for fragment in data.splitlines():
            piece = fragment.strip()
            if 1 <= len(piece) <= 250:
                self.fragments.append(piece)
        if self._in_h1:
            self._h1_parts.append(data)

    def handle_endtag(self, tag):
        if tag == "h1" and self._in_h1:
            self.headings.append(" ".join(self._h1_parts).strip())
            self._in_h1 = False
        super().handle_endtag(tag)


def _matching_structured_place_claim(html, venue):
    """If a matching Place JSON-LD exists but is contradictory, fail closed."""
    parser = _LD()
    parser.feed(html)
    parser.close()
    for block in parser.blocks:
        try:
            import json
            payload = json.loads(block)
        except (ValueError, TypeError):
            continue
        for item in _nodes(payload):
            for place in _place_candidates(item):
                names = [place.get("name")]
                aliases = place.get("alternateName", [])
                names += aliases if isinstance(aliases, list) else [aliases]
                if any(isinstance(name, str) and norm(name) == norm(venue)
                       for name in names):
                    return True
    return False


def _visible_contact_address(html, venue, city):
    """Conservative generic contact fallback, never an address from a lead.

    Reject hidden content, other venue H1, ambiguous contacts, isolated
    postcodes and addresses only from unrelated page sections.
    """
    if not isinstance(html, str) or not 60 <= len(html) <= 450_000:
        return None
    parser = _VisibleContacts()
    parser.feed(html)
    parser.close()
    if len(parser.headings) != 1 or norm(parser.headings[0]) != norm(venue):
        return None
    fragments = parser.fragments
    contacts = [i for i, token in enumerate(fragments)
                if norm(token) in CONTACT_LABELS]
    if not contacts:
        return None
    addresses = set()
    for i, token in enumerate(fragments):
        # The street must be close to an explicit contact label, never a
        # guessed civic address from footer or a list of event locations.
        if not any(0 < i - j <= 18 for j in contacts):
            continue
        street = STREET.fullmatch(token)
        if street is None:
            continue
        for future in fragments[i + 1:i + 5]:
            postcode = POSTAL.fullmatch(future)
            if postcode and norm(postcode["city"]) == norm(city):
                number = street["number"]
                road = street["street"]
                addresses.add((number, road, postcode["postcode"], city))
    if len(addresses) != 1:
        return None
    number, street, postcode, locality = next(iter(addresses))
    return (number, street, postcode, locality, (norm(venue),))


def _trusted_exact_venue(lead, context):
    if not isinstance(lead, dict) or not isinstance(context, dict):
        return None
    if set(context) != CONTEXT_KEYS:
        return None
    legacy, public = context.get("legacy_venues"), context.get("public_places")
    if (not isinstance(legacy, list) or not isinstance(public, list)
            or len(legacy) > 500 or len(public) > 500):
        return None
    city, venue = lead.get("city"), lead.get("venue")
    if (not isinstance(city, str) or not city.strip()
            or not isinstance(venue, str) or not venue.strip()):
        return None
    matches, invalid = [], False
    for row in [*legacy, *public]:
        if not isinstance(row, dict) or not isinstance(row.get("city"), str):
            continue
        aliases = row.get("aliases")
        if not isinstance(aliases, (tuple, list)):
            continue
        if (norm(row["city"]) != norm(city)
                or norm(venue) not in {
                    norm(a) for a in aliases if isinstance(a, str)
                }):
            continue
        if not _valid_venue(row):
            invalid = True
            continue
        matches.append(row)
    # No ambiguous aliases, conflicting records or untrusted venue rows.
    return matches[0] if not invalid and len(matches) == 1 else None


def _coordinates_from_ban(geojson, address):
    if (not isinstance(geojson, dict)
            or geojson.get("type") != "FeatureCollection"
            or not isinstance(geojson.get("features"), list)
            or not 1 <= len(geojson["features"]) <= MAX_FEATURES):
        return None
    house, street, postcode, city, _aliases = address
    coords = []
    for feature in geojson["features"]:
        if not isinstance(feature, dict):
            continue
        prop, geom = feature.get("properties"), feature.get("geometry")
        if not isinstance(prop, dict) or not isinstance(geom, dict):
            continue
        score = prop.get("score")
        if (prop.get("type") != "housenumber"
                or type(score) not in (int, float)
                or not math.isfinite(score) or score < MIN_BAN_SCORE
                or str(prop.get("housenumber", "")).casefold() != house.casefold()
                or norm(prop.get("street")) != norm(street)
                or prop.get("postcode") != postcode
                or norm(prop.get("city")) != norm(city)
                or not isinstance(prop.get("citycode"), str)
                or not re.fullmatch(r"(?:\d{5}|2[AB]\d{3})", prop["citycode"])
                or geom.get("type") != "Point"
                or not isinstance(geom.get("coordinates"), list)
                or len(geom["coordinates"]) != 2):
            continue
        lng, lat = geom["coordinates"]
        if (not all(type(v) in (int, float) and math.isfinite(v)
                    for v in (lat, lng))
                or not -90 <= lat <= 90 or not -180 <= lng <= 180
                or (lat, lng) == (0, 0)):
            continue
        coords.append((lat, lng))
    if not coords or any(meters(coords[0], p) > COORDINATE_TOLERANCE_METERS
                         for p in coords[1:]):
        return None
    return coords[0]


def diagnose_html_independent_venue(
        lead, independent_context, *,
        venue_reader=fetch_official_page, ban_reader=fetch_ban_exact):
    """Bounded live check; return a fixed, anonymous reason, never GPS or URL.

    The caller owns the source registries, and MUST NOT build them from
    candidate fields. Reader mocks are for isolated tests only.
    """
    if not callable(venue_reader) or not callable(ban_reader):
        return _result("independent_readers_unavailable")
    venue = _trusted_exact_venue(lead, independent_context)
    if venue is None:
        return _result("reviewed_venue_absent_ambiguous_or_untrusted")
    official = venue["official"]
    source = {"approved_host": urlsplit(official).hostname,
              "exact_url": official}
    if _url(official, host=source["approved_host"]) is None:
        return _result("reviewed_venue_url_invalid")
    try:
        page = venue_reader(source)
        if (not isinstance(page, dict)
                or set(page) != {"url", "html"}
                or page["url"] != official):
            return _result("official_venue_page_unavailable")
        address = _place_address(page.get("html"), lead["venue"], lead["city"])
        kind = "json_ld"
        if address is None:
            # A conflicting/invalid first-party structured Place must not be
            # bypassed with unstructured page text.
            if _matching_structured_place_claim(page["html"], lead["venue"]):
                return _result("official_venue_address_not_structured")
            address = _visible_contact_address(
                page["html"], lead["venue"], lead["city"])
            kind = "visible_contacts"
        if address is None:
            return _result("official_venue_address_not_structured")
        if kind == "json_ld":
            query = ban_query_for_official_address(lead, source, page)
        else:
            number, street, postcode, locality, _aliases = address
            target = f"{number} {street} {postcode} {locality}"
            query = GEO_ENDPOINT + "?q=" + quote(target, safe="") + "&limit=2"
        if query is None:
            return _result("independent_query_not_derived_from_official_address",
                           address=True, address_kind=kind)
        geojson = ban_reader(query)
        point = _coordinates_from_ban(geojson, address)
        if point is None:
            return _result("ban_housenumber_missing_or_ambiguous",
                           address=True, address_kind=kind)
        # Coordinates were independently reviewed previously AND just
        # cross-checked against the official geocoder response.
        reference = (venue["lat"], venue["lng"])
        if meters(reference, point) > MAX_DISTANCE_METERS:
            return _result("ban_conflicts_with_reviewed_venue",
                           address=True, ban=True, address_kind=kind)
        return _result("independent_official_address_ban_registry_concordant",
                       address=True, ban=True, venue=True,
                       address_kind=kind)
    except (ValueError, TypeError, OSError, KeyError, OverflowError):
        return _result("independent_source_or_ban_unavailable")
