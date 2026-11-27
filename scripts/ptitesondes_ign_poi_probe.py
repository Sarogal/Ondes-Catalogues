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

def probe(*, discover=scan, lookup=exact_directory_record, query=fetch_poi):
    # Select only automatically discovered leads. No fixed venue list, no
    # saved GPS, no private data, no public or private catalogue writes.
    leads = discover()["records"]
    attempted = 0
    summaries = []
    for lead in leads[:5]:
        record = lookup(lead["city"], lead["venue"])
        pair = identity(record)
        if pair is None:
            continue
        attempted += 1
        summaries.append(summarize(query(pair[1], record["code_commune"])))
    return {"discovered": len(leads), "attempted": attempted, "responses": summaries,
            "publication_ready": False, "public_writes": 0}

if __name__ == "__main__":
    try:
        print(json.dumps(probe(), sort_keys=True))
    except (OSError, ValueError, KeyError, TypeError, UnicodeError, OverflowError):
        print("::error::IGN POI probe unavailable or invalid")
        raise SystemExit(1) from None
