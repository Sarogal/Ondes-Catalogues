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


def probe(*, fetch=_fetch, pages=(1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12)):
    counts, family, numberless, shapes = Counter(), Counter(), Counter(), Counter()
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
    return {"rows_examined": sum(counts.values()), "point_counts": dict(counts),
            "family_counts": dict(family), "numberless_family_counts": dict(numberless),
            "field_shapes": dict(shapes), "publication_ready": False, "public_writes": 0}


if __name__ == "__main__":
    try:
        print(json.dumps(probe(), sort_keys=True))
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, OverflowError):
        print("::error::Cultural directory point audit unavailable")
        raise SystemExit(1) from None
