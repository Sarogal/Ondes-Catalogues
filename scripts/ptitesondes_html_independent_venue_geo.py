"""Read-only independent GPS check for any HTML-discovered family session.

This reuses the generic first-party Place JSON-LD and bounded IGN/BAN readers.
Crucially, the pinned *venue* URL and reference coordinates come only from
pre-reviewed, separate public registries; never from the candidate or search.
No OA event is required, and no venue or event may be admitted or published.
"""
import math
import re
from urllib.parse import urlsplit

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


def _result(reason, *, address=False, ban=False, venue=False):
    return {
        "schema": SCHEMA,
        "reason": reason,
        "official_venue_address_present": address,
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
        if address is None:
            return _result("official_venue_address_not_structured")
        query = ban_query_for_official_address(lead, source, page)
        if query is None:
            return _result("independent_query_not_derived_from_official_address",
                           address=True)
        geojson = ban_reader(query)
        point = _coordinates_from_ban(geojson, address)
        if point is None:
            return _result("ban_housenumber_missing_or_ambiguous", address=True)
        # Coordinates were independently reviewed previously AND just
        # cross-checked against the official geocoder response.
        reference = (venue["lat"], venue["lng"])
        if meters(reference, point) > MAX_DISTANCE_METERS:
            return _result("ban_conflicts_with_reviewed_venue",
                           address=True, ban=True)
        return _result("independent_official_address_ban_registry_concordant",
                       address=True, ban=True, venue=True)
    except (ValueError, TypeError, OSError, KeyError, OverflowError):
        return _result("independent_source_or_ban_unavailable")
