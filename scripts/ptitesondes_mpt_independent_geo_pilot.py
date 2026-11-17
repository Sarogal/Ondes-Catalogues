"""Read-only independently reviewed building points for a MPT family pilot.

Only identities and building coordinates are curated. No event, session, age,
cost, canonical organizer proof, private approval, or publication is granted.
Separate source pages are municipal; geocoding is independently rechecked
against the French public IGN geocoder, not copied from event candidates.
"""
from copy import deepcopy
import math
import re
import unicodedata
from urllib.parse import parse_qs, urlsplit

from proof import meters

SCHEMA = "ptitesondes.mpt_independent_geographic_review.v1"
MIN_EXACT_HOUSENUMBER_SCORE = 0.95
MAX_RECHECK_DISTANCE_METRES = 15
REGISTRY_KEYS = frozenset({
    "venue_key", "city", "venue", "region", "department", "lat", "lng",
    "institutional_url", "geo_source_url",
})
EVIDENCE_KEYS = REGISTRY_KEYS | frozenset({"address_label", "postcode"})

# Exact, independently corroborated primary event venue and housenumber.
# These records do not identify or authorize any specific family outing.
PILOT_VENUES = (
    {
        "venue_key": "mpt-melina-mercouri-montpellier",
        "city": "Montpellier", "venue": "Maison pour tous Mélina Mercouri",
        "region": "Occitanie", "department": "Hérault",
        "postcode": "34000",
        "address_label": "842 Rue de la Vieille Poste 34000 Montpellier",
        "lat": 43.614655, "lng": 3.907746,
        "institutional_url": (
            "https://mpt.montpellier.fr/evenement/"
            "melipitchouns-atelier-deveil-et-de-lecture"
        ),
        "geo_source_url": (
            "https://data.geopf.fr/geocodage/search?"
            "q=842%20Rue%20de%20la%20Vieille%20Poste%2034000%20Montpellier&limit=2"
        ),
    },
    {
        "venue_key": "mpt-frida-kahlo-montpellier",
        "city": "Montpellier", "venue": "Maison pour tous Frida Kahlo",
        "region": "Occitanie", "department": "Hérault",
        "postcode": "34000",
        "address_label": "240 Rue Claude Levi-Strauss 34000 Montpellier",
        "lat": 43.595814, "lng": 3.903417,
        "institutional_url": (
            "https://mpt.montpellier.fr/evenement/bebes-lecteurs"
        ),
        "geo_source_url": (
            "https://data.geopf.fr/geocodage/search?"
            "q=240%20Rue%20Claude%20Levi-Strauss%2034000%20Montpellier&limit=2"
        ),
    },
    {
        "venue_key": "mpt-albert-dubout-montpellier",
        "city": "Montpellier", "venue": "Maison pour tous Albert Dubout",
        "region": "Occitanie", "department": "Hérault",
        "postcode": "34090",
        "address_label": "2 Rue des Tourterelles 34090 Montpellier",
        "lat": 43.626242, "lng": 3.879302,
        "institutional_url": (
            "https://mpt.montpellier.fr/evenement/dans-la-foret"
        ),
        "geo_source_url": (
            "https://data.geopf.fr/geocodage/search?"
            "q=2%20Rue%20des%20Tourterelles%2034090%20Montpellier&limit=2"
        ),
    },
)


def norm(s):
    if not isinstance(s, str):
        return ""
    s = unicodedata.normalize("NFKD", s.casefold())
    return " ".join(re.sub(r"[^a-z0-9]+", " ",
                           "".join(c for c in s
                                   if not unicodedata.combining(c))).split())


def reviewed_pilot_records():
    """Return a defensive copy: callers cannot mutate curated source facts."""
    return deepcopy(PILOT_VENUES)


def validate_curated_registry(records=None):
    """Structural review, NOT verification that the live IGN API still agrees."""
    records = PILOT_VENUES if records is None else records
    if not isinstance(records, (tuple, list)) or len(records) != 3:
        return False
    seen_keys, seen_names = set(), set()
    for r in records:
        if not isinstance(r, dict) or set(r) != EVIDENCE_KEYS:
            return False
        if (not isinstance(r["venue_key"], str)
                or not re.fullmatch(r"mpt-[a-z-]+-montpellier", r["venue_key"])
                or r["city"] != "Montpellier" or r["region"] != "Occitanie"
                or r["department"] != "Hérault"
                or r["postcode"] not in ("34000", "34090")
                or not isinstance(r["venue"], str)
                or not r["venue"].startswith("Maison pour tous ")
                or not isinstance(r["address_label"], str)
                or r["venue_key"] in seen_keys
                or norm(r["venue"]) in seen_names):
            return False
        seen_keys.add(r["venue_key"])
        seen_names.add(norm(r["venue"]))
        if (not all(type(r[k]) is float and math.isfinite(r[k])
                    for k in ("lat", "lng"))
                or not 43.4 <= r["lat"] <= 43.8
                or not 3.6 <= r["lng"] <= 4.2):
            return False
        try:
            official, geo = (urlsplit(r["institutional_url"]),
                             urlsplit(r["geo_source_url"]))
            query = parse_qs(geo.query, strict_parsing=True)
            if not (official.scheme == "https"
                    and official.hostname == "mpt.montpellier.fr"
                    and official.path.startswith("/evenement/")
                    and official.username is None and official.password is None
                    and official.port in (None, 443)
                    and not official.query and not official.fragment
                    and geo.scheme == "https"
                    and geo.hostname == "data.geopf.fr"
                    and geo.path == "/geocodage/search"
                    and geo.username is None and geo.password is None
                    and geo.port in (None, 443) and not geo.fragment
                    and set(query) == {"q", "limit"}
                    and query["limit"] == ["2"]
                    and len(query["q"]) == 1
                    and norm(query["q"][0]) == norm(r["address_label"])):
                return False
        except (ValueError, TypeError):
            return False
    return True


def review_exact_venue_name(city, venue, records=None):
    """A building lookup only; does not manufacture session-level GPS claims."""
    if not isinstance(city, str) or not isinstance(venue, str):
        return None
    rows = reviewed_pilot_records() if records is None else records
    if not validate_curated_registry(rows):
        return None
    found = [r for r in rows
             if norm(city) == norm(r["city"])
             and norm(venue) == norm(r["venue"])]
    return deepcopy(found[0]) if len(found) == 1 else None


def independent_geo_recheck(record, response):
    """Verify a live IGN/BAN exact housenumber independently of the event.

    Refuse a geocoder's street centroid, fuzzy address, duplicate exact hits,
    low confidence, moved building, wrong postcode, or ambiguous result.
    """
    if not isinstance(record, dict) or set(record) != EVIDENCE_KEYS:
        return False
    if not isinstance(response, dict):
        return False
    features = response.get("features")
    if not isinstance(features, list) or len(features) > 10:
        return False
    matched = []
    for f in features:
        if not isinstance(f, dict):
            continue
        props, geometry = f.get("properties"), f.get("geometry")
        if not isinstance(props, dict) or not isinstance(geometry, dict):
            continue
        if (props.get("type") != "housenumber"
                or norm(props.get("label")) != norm(record["address_label"])
                or props.get("postcode") != record["postcode"]
                or norm(props.get("city")) != norm(record["city"])):
            continue
        score = props.get("score")
        if (type(score) not in (int, float)
                or not math.isfinite(score)
                or not MIN_EXACT_HOUSENUMBER_SCORE <= score <= 1):
            continue
        point = geometry.get("coordinates")
        if (geometry.get("type") != "Point"
                or not isinstance(point, list) or len(point) != 2
                or not all(type(v) in (int, float) and math.isfinite(v)
                           for v in point)
                or not -180 <= point[0] <= 180
                or not -90 <= point[1] <= 90):
            continue
        if meters((record["lat"], record["lng"]),
                  (float(point[1]), float(point[0]))) > MAX_RECHECK_DISTANCE_METRES:
            continue
        matched.append(f)
    return len(matched) == 1


def geo_review_report(records, responses_by_key):
    """Anonymous rollup; accepts no candidate, patch or publisher writes."""
    if not validate_curated_registry(records):
        raise ValueError("invalid_curated_mpt_venue_registry")
    if not isinstance(responses_by_key, dict):
        raise ValueError("invalid_independent_geo_responses")
    keys = {r["venue_key"] for r in records}
    if set(responses_by_key) != keys:
        raise ValueError("incomplete_exact_geo_recheck")
    accepted = sum(independent_geo_recheck(
        r, responses_by_key[r["venue_key"]]) for r in records)
    return {
        "schema": SCHEMA,
        "mode": "independent_venue_geography_only_no_admission",
        "curated_venues_checked": len(records),
        "exact_external_housenumber_matches": accepted,
        "held_for_external_geo_review": len(records) - accepted,
        "per_event_organizer_evidence_verified": 0,
        "per_event_age_access_and_date_verified": 0,
        "human_approvals": 0,
        "event_location_claims_not_inferred": True,
        "publisher_connected": False,
        "publication_ready": False,
        "approval_granted_to_publisher": False,
        "public_writes": 0,
        "candidate_titles_addresses_and_urls_excluded": True,
    }


def national_preflight_venue_registry(records=None):
    """Only the location-reference shape for #346. NOT proof of an event."""
    rows = reviewed_pilot_records() if records is None else records
    if not validate_curated_registry(rows):
        raise ValueError("invalid_curated_mpt_venue_registry")
    return [{k: r[k] for k in REGISTRY_KEYS} for r in rows]
