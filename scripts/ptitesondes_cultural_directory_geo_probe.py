"""Private-free read-only audit of place vs municipality coordinates.

A directory point is not an independently verified building location.
Never approve a candidate, expose raw locations or replace an absent GPS.
"""
from collections import Counter
import json
import math
from urllib.parse import urlencode
from ptitesondes_cultural_directory_discovery import PAGE_SIZE, parse_page, identity, is_family_lead
from ptitesondes_national_cultural_directory_probe import URL, _fetch
from ptitesondes_cultural_directory_identity import directory_identity


def number(value):
    if type(value) not in (str, int, float):
        return None
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (ValueError, TypeError, OverflowError):
        return None


def point(lat, lng):
    a, b = number(lat), number(lng)
    if a is None or b is None or not -90 <= a <= 90 or not -180 <= b <= 180 or (a, b) == (0, 0):
        return None
    return a, b


def pair(value):
    # Only explicit known shapes: named latitude/longitude or lat,lng text.
    # Arrays/unknown shapes are counted, not interpreted.
    if isinstance(value, dict):
        return point(value.get("lat", value.get("latitude")),
                     value.get("lon", value.get("longitude")))
    if isinstance(value, str) and len(value) <= 100 and value.count(",") == 1:
        return point(*value.split(","))
    return None


def shape(value):
    return "missing" if value is None or value == "" else (
        "text" if isinstance(value, str) else "object" if isinstance(value, dict)
        else "list" if isinstance(value, list) else "number" if type(value) in (int, float)
        else "other")


def distance(a, b):
    x, y = map(math.radians, a)
    u, v = map(math.radians, b)
    h = math.sin((u-x)/2)**2 + math.cos(x)*math.cos(u)*math.sin((v-y)/2)**2
    return 6371000 * 2 * math.asin(math.sqrt(min(1, max(0, h))))


def classify(row):
    loc = point(row.get("latitude"), row.get("longitude"))
    supplied = pair(row.get("coordonnees_geographiques_lieu"))
    town = pair(row.get("coordonnees_geographiques_commune_lieu"))
    if loc is None:
        return "no_numeric_place_point"
    if supplied is None:
        return "place_pair_unparsed"
    if distance(loc, supplied) > 10:
        return "place_fields_disagree"
    if town is None:
        return "municipality_pair_unparsed"
    if distance(loc, town) <= 50:
        return "near_municipality_reference"
    return "distinct_directory_point_unverified"


def nearby_exact_node(row, doc):
    """Require a unique named cultural node, exact city/postcode and proximity.
    A matching map node remains an unverified hypothesis, not approval.
    """
    from ptitesondes_generic_venue_osm_preflight import MAX_ELEMENTS
    from ptitesondes_open_world_permanent_place_evidence import mapped_place_kind
    from ptitesondes_family_national_source_preflight import norm_text
    if (classify(row) != "distinct_directory_point_unverified"
            or not isinstance(doc, dict) or doc.get("remark")
            or not isinstance(doc.get("elements"), list)
            or len(doc["elements"]) >= MAX_ELEMENTS):
        return None
    names = {norm_text(row.get(k)) for k in ("nom_du_lieu", "nom_usuel_du_lieu")}
    names.discard("")
    city = norm_text(row.get("commune"))
    postcode = row.get("code_postal")
    if not names or not city or not isinstance(postcode, str) or len(postcode) != 5 or not postcode.isdigit():
        return None
    matches = [obj for obj in doc["elements"] if isinstance(obj, dict)
               and isinstance(obj.get("tags"), dict)
               and norm_text(obj["tags"].get("name")) in names
               and norm_text(obj["tags"].get("addr:city")) in ("", city)]
    if len(matches) != 1:
        return None
    obj = matches[0]
    tags = obj["tags"]
    loc = point(obj.get("lat"), obj.get("lon"))
    if (obj.get("type") != "node" or type(obj.get("id")) is not int or obj["id"] <= 0
            or norm_text(tags.get("addr:city")) != city or tags.get("addr:postcode") != postcode
            or mapped_place_kind(tags) is None or tags.get("access") in ("private", "no", "customers")
            or tags.get("disused") == "yes" or tags.get("abandoned") == "yes"
            or loc is None or distance(loc, point(row["latitude"], row["longitude"])) > 65):
        return None
    return loc


REVERSE_LIMIT = 20


def reverse_poi_url(row):
    import re
    if classify(row) != "distinct_directory_point_unverified":
        raise ValueError("invalid_directory_point")
    code = row.get("code_commune")
    if not isinstance(code, str) or not re.fullmatch(r"(?:[0-9]{5}|2[AB][0-9]{3})", code):
        raise ValueError("invalid_directory_code")
    lat, lng = point(row["latitude"], row["longitude"])
    return "https://data.geopf.fr/geocodage/reverse?" + urlencode({
        "index": "poi", "lat": lat, "lon": lng, "citycode": code,
        "limit": REVERSE_LIMIT, "searchgeom": json.dumps({"type": "Circle",
            "coordinates": [lng, lat], "radius": 100}, separators=(",", ":"))})


def fetch_reverse_poi(row, opener=None):
    from urllib.request import Request, build_opener
    from ptitesondes_national_cultural_directory_probe import NoRedirect
    url = reverse_poi_url(row)
    reader = opener or build_opener(NoRedirect()).open
    with reader(Request(url, headers={"Accept": "application/json",
            "User-Agent": "PtitesOndesPOIProbe/1.0"}), timeout=20) as response:
        if response.status != 200 or response.geturl() != url:
            raise ValueError("invalid_reverse_poi_response")
        raw = response.read(200001)
    if not raw or len(raw) > 200000:
        raise ValueError("invalid_reverse_poi_size")
    return json.loads(raw)


def reverse_exact_point(row, doc, diagnostics):
    from ptitesondes_ign_poi_probe import exact_poi_point
    if classify(row) != "distinct_directory_point_unverified":
        diagnostics["invalid_directory_point"] += 1
        return None
    loc = exact_poi_point(row, doc, diagnostics, limit=REVERSE_LIMIT)
    if loc is not None and distance(loc, point(row["latitude"], row["longitude"])) > 65:
        diagnostics["poi_distance"] += 1
        return None
    return loc


def probe(*, fetch=_fetch, nearby=None, reverse=None, pages=(1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12)):
    counts, family, numberless, shapes = Counter(), Counter(), Counter(), Counter()
    candidates = []
    for page in pages[:12]:
        doc = fetch(URL.split("?")[0] + "?" + urlencode({"page": page, "page_size": PAGE_SIZE}))
        parse_page(doc, page)
        for row in doc["data"]:
            reason = classify(row)
            counts[reason] += 1
            for field in ("latitude", "longitude", "coordonnees_geographiques_lieu",
                          "coordonnees_geographiques_commune_lieu"):
                shapes[field + ":" + shape(row.get(field))] += 1
            lead = identity(row)
            if lead and is_family_lead(row):
                family[reason] += 1
                diagnostics = Counter()
                directory_identity(*lead, row, diagnostics)
                if diagnostics.get("numbered_street_missing"):
                    numberless[reason] += 1
                if reason == "distinct_directory_point_unverified":
                    candidates.append((not bool(diagnostics.get("numbered_street_missing")), row))
    map_counts = Counter()
    if nearby is not None:
        for _, row in sorted(candidates, key=lambda x: x[0])[:5]:
            map_counts["attempted"] += 1
            try:
                doc = nearby(point(row["latitude"], row["longitude"]))
                result = nearby_exact_node(row, doc)
                map_counts["exact_node_hint" if result is not None else "no_exact_node"] += 1
            except (OSError, ValueError, TypeError, KeyError, OverflowError, UnicodeError):
                map_counts["map_unavailable"] += 1
    reverse_counts, reverse_rejections = Counter(), Counter()
    if reverse is not None:
        for _, row in sorted(candidates, key=lambda x: x[0])[:5]:
            reverse_counts["attempted"] += 1
            try:
                doc = reverse(row)
                loc = reverse_exact_point(row, doc, reverse_rejections)
                reverse_counts["exact_point_hint" if loc is not None else "no_exact_point"] += 1
            except (OSError, ValueError, TypeError, KeyError, OverflowError, UnicodeError):
                reverse_counts["provider_unavailable"] += 1
    return {"rows_examined": sum(counts.values()), "point_counts": dict(counts),
            "family_counts": dict(family), "numberless_family_counts": dict(numberless),
            "field_shapes": dict(shapes), "nearby_map_counts": dict(map_counts),
            "reverse_poi_counts": dict(reverse_counts), "reverse_poi_rejections": dict(reverse_rejections), "publication_ready": False, "public_writes": 0}


if __name__ == "__main__":
    try:
        from ptitesondes_generic_venue_osm_preflight import fetch_overpass, osm_transport_diagnostics
        result = probe(nearby=fetch_overpass, reverse=fetch_reverse_poi)
        result["map_transport"] = osm_transport_diagnostics()
        print(json.dumps(result, sort_keys=True))
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, OverflowError):
        print("::error::Cultural directory point audit unavailable")
        raise SystemExit(1) from None
