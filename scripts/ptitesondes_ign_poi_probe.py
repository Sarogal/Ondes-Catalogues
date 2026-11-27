"""Read-only probe of IGN BD TOPO named points; never publication authority."""
from collections import Counter
import json
import math
import re
from urllib.parse import urlencode
from urllib.request import Request, build_opener
from ptitesondes_national_cultural_directory_probe import NoRedirect
from ptitesondes_cultural_directory_discovery import scan, identity
from ptitesondes_national_cultural_directory_probe import exact_directory_record
from ptitesondes_family_national_source_preflight import norm_text

ENDPOINT = "https://data.geopf.fr/geocodage/search"
LIMIT = 5

def poi_url(name, code):
    if (not isinstance(name, str) or not 2 <= len(name) <= 180
            or not norm_text(name) or any(ord(c) < 32 or ord(c) == 127 for c in name)
            or not isinstance(code, str) or not re.fullmatch(r"(?:[0-9]{5}|2[AB][0-9]{3})", code)):
        raise ValueError("invalid_poi_query")
    return ENDPOINT + "?" + urlencode({"q": name, "index": "poi", "citycode": code,
                                      "limit": LIMIT})

def fetch_poi(name, code, opener=None):
    url = poi_url(name, code)
    reader = opener or build_opener(NoRedirect()).open
    req = Request(url, headers={"Accept": "application/json",
                                "User-Agent": "PtitesOndesPOIProbe/1.0"})
    with reader(req, timeout=20) as response:
        if response.status != 200 or response.geturl() != url:
            raise ValueError("invalid_poi_response")
        raw = response.read(200001)
    if not raw or len(raw) > 200000:
        raise ValueError("oversized_poi_response")
    return json.loads(raw)

def summarize(doc):
    if (not isinstance(doc, dict) or doc.get("type") != "FeatureCollection"
            or not isinstance(doc.get("features"), list) or len(doc["features"]) > LIMIT):
        raise ValueError("invalid_poi_collection")
    fields = Counter()
    types = Counter()
    points = 0
    allowed_types = {"poi", "housenumber", "street", "locality", "municipality"}
    for f in doc["features"]:
        if not isinstance(f, dict) or f.get("type") != "Feature":
            raise ValueError("invalid_poi_feature")
        p, g = f.get("properties"), f.get("geometry")
        if not isinstance(p, dict) or not isinstance(g, dict):
            raise ValueError("invalid_poi_feature")
        for k in ("name", "label", "city", "citycode", "postcode", "score",
                  "type", "id", "category", "nature", "source", "street"):
            if k in p:
                fields[k] += 1
        kind = p.get("type")
        types[kind if isinstance(kind, str) and kind in allowed_types else "other"] += 1
        xy = g.get("coordinates")
        if (g.get("type") == "Point" and isinstance(xy, list) and len(xy) == 2
                and all(type(x) in (int, float) and math.isfinite(x) for x in xy)
                and -180 <= xy[0] <= 180 and -90 <= xy[1] <= 90):
            points += 1
    return {"features": len(doc["features"]), "valid_points": points,
            "field_presence": dict(fields), "feature_types": dict(types),
            "publication_ready": False, "public_writes": 0}

def official_names(record):
    """Only names explicitly attached to this fresh directory record."""
    names = {}
    for field in ("nom_du_lieu", "nom_usuel_du_lieu"):
        value = record.get(field)
        if (isinstance(value, str) and 2 <= len(value.strip()) <= 180
                and norm_text(value) and not any(ord(c) < 32 or ord(c) == 127 for c in value)):
            names.setdefault(norm_text(value), value.strip())
    return list(names.values())


def exact_poi_point(record, doc, diagnostics=None):
    """A unique exact named point, not a street or commune centroid.

    This is a private location hypothesis only. The independent official
    page, cultural relevance and public access still need validation.
    """
    def reject(reason):
        if diagnostics is not None:
            diagnostics[reason] += 1
        return None
    try:
        pair = identity(record)
        if pair is None:
            return reject('directory_identity')
        city, name = pair
        aliases = {norm_text(value) for value in official_names(record)}
        code, postcode = record["code_commune"], record.get("code_postal")
        if not isinstance(postcode, str) or not re.fullmatch(r"[0-9]{5}", postcode):
            return reject("directory_postcode_format")
        summarize(doc)
        features = doc["features"]
        # A full truncated result set cannot establish uniqueness.
        if len(features) >= LIMIT:
            return reject('truncated_results')
        matches = []
        for feature in features:
            p, g = feature["properties"], feature["geometry"]
            if norm_text(p.get("name")) not in aliases:
                continue
            # A second exact-name result or malformed matching feature
            # must not be silently discarded to manufacture uniqueness.
            if p.get("citycode") != code:
                return reject("poi_insee_mismatch")
            if p.get("postcode") != postcode:
                return reject("poi_postcode_mismatch")
            if norm_text(p.get("city")) != norm_text(city):
                return reject("poi_city_mismatch")
            category = p.get("category")
            if isinstance(category, str):
                category = [category]
            if (not isinstance(category, list) or not category or len(category) > 20
                    or any(not isinstance(x, str) or not norm_text(x) for x in category)
                    or any(norm_text(x) in ("street", "rue", "commune", "municipality",
                                           "locality", "lieu dit") for x in category)
                    or p.get("type") in ("street", "municipality", "locality", "housenumber")):
                return reject("poi_category_or_type")
            score = p.get("score")
            if type(score) not in (int, float) or not math.isfinite(score) or not 0.8 <= score <= 1:
                return reject("poi_score")
            xy = g.get("coordinates")
            if (g.get("type") != "Point" or not isinstance(xy, list) or len(xy) != 2
                    or not all(type(x) in (int, float) and math.isfinite(x) for x in xy)
                    or not -180 <= xy[0] <= 180 or not -90 <= xy[1] <= 90
                    or xy == [0, 0]):
                return reject("poi_geometry")
            matches.append((xy[1], xy[0]))
        if len(matches) != 1:
            return reject("poi_exact_name_missing" if not matches else "poi_exact_name_ambiguous")
        return matches[0]
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        return reject("invalid_response")


def query_official_names(record, query, diagnostics):
    """Check both official names; do not hide conflicting or truncated hits."""
    points = set()
    responses = []
    reasons = Counter()
    for name in official_names(record):
        response = query(name, record["code_commune"])
        responses.append(summarize(response))
        local = Counter()
        point = exact_poi_point(record, response, local)
        if point is not None:
            points.add(point)
        else:
            reasons.update(local)
    conflicts = {key for key in reasons if key != "poi_exact_name_missing"}
    if conflicts:
        diagnostics.update(reasons)
        return None, responses
    if len(points) > 1:
        diagnostics["poi_official_alias_conflict"] += 1
        return None, responses
    if not points:
        diagnostics["poi_exact_name_missing"] += 1
        return None, responses
    return next(iter(points)), responses


def verify_admin_point(record, point, admin_fetch):
    if point is None:
        return False
    from ptitesondes_open_world_permanent_place_draft import administrative_identity
    try:
        response = admin_fetch(*point)
        return (administrative_identity(response, record["commune"], record["code_postal"]) is not None
                and response[0]["code"] == record["code_commune"])
    except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError):
        return False


def probe(*, discover=scan, lookup=exact_directory_record, query=fetch_poi, admin_fetch=None):
    # Select only automatically discovered leads. No fixed venue list, no
    # saved GPS, no private data, no public or private catalogue writes.
    leads = discover()["records"]
    attempted = exact = admin_verified = 0
    summaries = []
    diagnostics = Counter()
    if admin_fetch is None:
        from ptitesondes_open_world_permanent_place_draft import fetch_admin
        admin_fetch = fetch_admin
    for lead in leads[:5]:
        record = lookup(lead["city"], lead["venue"])
        pair = identity(record)
        if pair is None:
            continue
        attempted += 1
        point, responses = query_official_names(record, query, diagnostics)
        summaries.extend(responses)
        exact += int(point is not None)
        admin_verified += int(verify_admin_point(record, point, admin_fetch))
    return {"discovered": len(leads), "attempted": attempted, "responses": summaries,
            "exact_named_points": exact, "admin_verified_points": admin_verified,
            "rejection_counts": dict(diagnostics),
            "publication_ready": False, "public_writes": 0}

def discover_probe_sample():
    # At most 240 rows, with a deterministic bounded page advance; no
    # mutation of production cursors, and at most ten POI lookups across five records.
    records = {}
    page = 1
    for _ in range(3):
        result = scan(page)
        for row in result["records"]:
            records[(norm_text(row["city"]), norm_text(row["venue"]))] = row
        page = result["next_page"]
        if page == 1 or len(records) >= 5:
            break
    return {"records": list(records.values())}


if __name__ == "__main__":
    try:
        print(json.dumps(probe(discover=discover_probe_sample), sort_keys=True))
    except (OSError, ValueError, KeyError, TypeError, UnicodeError, OverflowError):
        print("::error::IGN POI probe unavailable or invalid")
        raise SystemExit(1) from None
