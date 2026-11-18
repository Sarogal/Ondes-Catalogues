"""Generic, strictly independent IGN/BAN recheck of curated venue coordinates.

A qualifying building point is NOT evidence that any particular event exists.
The output has no publication or approval authority. No network I/O here;
callers supply a bounded JSON response fetched only from pinned HTTPS sources.
"""
import math
import re
from urllib.parse import parse_qs, urlsplit

from proof import meters, norm

MIN_SCORE = 0.95
MAX_METRES = 15.0
SCHEMA = "ptitesondes.independent_ign_venue_recheck.v1"
POSTCODE = re.compile(r"\b[0-9]{5}\b")
HOUSENUMBER = re.compile(r"^\s*([0-9]{1,4})(?:\s*(?:bis|ter|quater))?\b", re.I)
REQUIRED = frozenset({"city", "aliases", "lat", "lng", "official", "geo_source"})


def reviewed_search(venue):
    """Validate a pre-reviewed, full-house-number IGN URL, never build one."""
    if not isinstance(venue, dict) or not REQUIRED.issubset(venue):
        return None
    city, aliases = venue.get("city"), venue.get("aliases")
    if not isinstance(city, str) or not norm(city) or not isinstance(aliases, list):
        return None
    if not aliases or any(not isinstance(a, str) or not norm(a) for a in aliases):
        return None
    if not all(type(venue.get(k)) in (int, float)
               and math.isfinite(venue[k]) for k in ("lat", "lng")):
        return None
    if not -90 <= venue["lat"] <= 90 or not -180 <= venue["lng"] <= 180:
        return None
    try:
        official, external = (urlsplit(venue["official"]),
                              urlsplit(venue["geo_source"]))
        query = parse_qs(external.query, strict_parsing=True)
        if not (official.scheme == "https" and official.hostname
                and official.hostname != "data.geopf.fr"
                and official.port in (None, 443)
                and official.username is None and official.password is None
                and not official.fragment
                and external.scheme == "https"
                and external.hostname == "data.geopf.fr"
                and external.path == "/geocodage/search"
                and external.port in (None, 443)
                and external.username is None and external.password is None
                and not external.fragment
                and set(query) == {"q", "limit"}
                and query["limit"] == ["2"] and len(query["q"]) == 1):
            return None
        address = query["q"][0].strip()
        postcodes = POSTCODE.findall(address)
        number = HOUSENUMBER.match(address)
        if len(postcodes) != 1 or number is None or not norm(city) in norm(address):
            return None
        return address, postcodes[0], number.group(1)
    except (ValueError, TypeError, KeyError, AttributeError):
        return None


def recheck_ign(venue, response):
    """Return (match, reason): no fuzzy identity or city-centroid rescue."""
    parsed = reviewed_search(venue)
    if parsed is None:
        return False, "untrusted_or_insufficient_reviewed_search"
    if not isinstance(response, dict):
        return False, "invalid_external_response"
    features = response.get("features")
    if (response.get("type") != "FeatureCollection"
            or not isinstance(features, list) or len(features) > 2):
        return False, "invalid_external_features"
    query, postcode, house = parsed
    hits = 0
    for feature in features:
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            continue
        prop, geom = feature.get("properties"), feature.get("geometry")
        if not isinstance(prop, dict) or not isinstance(geom, dict):
            continue
        if (prop.get("type") != "housenumber"
                or prop.get("postcode") != postcode
                or str(prop.get("housenumber", "")) != house
                or norm(prop.get("city")) != norm(venue["city"])
                or norm(prop.get("label")) != norm(query)):
            continue
        score = prop.get("score")
        if (type(score) not in (float, int) or not math.isfinite(score)
                or not MIN_SCORE <= score <= 1):
            continue
        coords = geom.get("coordinates")
        if (geom.get("type") != "Point" or not isinstance(coords, list)
                or len(coords) != 2
                or not all(type(c) in (float, int) and math.isfinite(c)
                           for c in coords)
                or not -180 <= coords[0] <= 180
                or not -90 <= coords[1] <= 90):
            continue
        if meters((venue["lat"], venue["lng"]),
                  (float(coords[1]), float(coords[0]))) > MAX_METRES:
            continue
        hits += 1
    if hits != 1:
        return False, "exact_house_number_unconfirmed_or_ambiguous"
    return True, "external_housenumber_reconfirmed"


def redacted_report(venues, responses):
    """Count-only cross-check. Does not certify events or update any register."""
    if not isinstance(venues, list) or not 1 <= len(venues) <= 100:
        raise ValueError("invalid_venue_batch")
    if not isinstance(responses, list) or len(responses) != len(venues):
        raise ValueError("missing_external_responses")
    identities = []
    for venue in venues:
        if reviewed_search(venue) is None:
            raise ValueError("invalid_curated_venue")
        identities.append((norm(venue["city"]), tuple(sorted(
            norm(a) for a in venue["aliases"]))))
    if len(set(identities)) != len(identities):
        raise ValueError("duplicate_venue_identity")
    ok = sum(recheck_ign(venue, response)[0]
             for venue, response in zip(venues, responses))
    return {
        "schema": SCHEMA,
        "mode": "external_building_geography_only_readonly",
        "curated_buildings_checked": len(venues),
        "external_exact_housenumber_matches": ok,
        "needs_geography_review": len(venues) - ok,
        "private_candidate_names_urls_exposed": False,
        "official_event_organizer_and_date_proof_checked": False,
        "ages_and_access_checked": False,
        "approval_granted": False,
        "publisher_connected": False,
        "public_writes": 0,
    }
