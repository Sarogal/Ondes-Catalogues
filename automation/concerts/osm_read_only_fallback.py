"""Bounded, robots-aware OpenStreetMap read-only endpoint construction.

The OSM editing API is not consistently usable from public runners and is
not intended as an unattended discovery API. A dedicated read-only Overpass
service serves public OSM data; all calls still go through the existing
secure DNS-pinned, HTTPS, robots-aware fetcher with no redirect or SSRF.

Only immutable numeric OSM feature identifiers or caller-computed bounded
bounding boxes may build queries. No performer, candidate, domain, URL, or
arbitrary user-supplied Overpass script may appear as an executable query.
"""
from __future__ import annotations

import math
import re
from urllib.parse import urlencode

ENDPOINT = "https://overpass.private.coffee/api/interpreter"
ALTERNATE_ENDPOINT = "https://overpass-api.de/api/interpreter"
ENDPOINTS = (ENDPOINT, ALTERNATE_ENDPOINT)


def _endpoint(provider):
    # Source code selects either read-only transport, never an input lead.
    if type(provider) is not int or provider not in (0, 1):
        raise ValueError("Unsafe OSM read-only provider")
    return ENDPOINTS[provider]
MAX_TIMEOUT = 12
OSM_ID = re.compile(r"[1-9][0-9]{0,18}\Z")


def element(kind, identifier, *, fmt="xml", provider=0):
    """GET one named OSM node or way, safely and without an editing API."""
    if (kind not in ("node", "way") or fmt not in ("xml", "json")
            or not isinstance(identifier, str)
            or OSM_ID.fullmatch(identifier) is None):
        raise ValueError("Unsafe OSM read-only element query")
    data = (f"[out:{fmt}][timeout:{MAX_TIMEOUT}];" +
            f"{kind}({identifier});out body;")
    return _endpoint(provider) + "?" + urlencode({"data": data})


def nearby(south, west, north, east, *, provider=0):
    """Return a tiny readonly bbox query for independently named OSM geometry.

    Unlike a name lookup, this also returns ways and their referenced nodes.
    The downstream geography verifier requires EXACT name, city, postcode,
    address, distance, single feature, and first-party source attribution.
    """
    coords = (south, west, north, east)
    if (any(type(v) not in (int, float) or not math.isfinite(v)
            for v in coords)
            or not -56 <= south < north <= 52
            or not -180 <= west < east <= 180
            or north - south > 0.01
            or east - west > 0.015):
        raise ValueError("Unsafe OSM read-only bbox")
    fmt = lambda v: f"{v:.6f}"
    bbox = ",".join(fmt(v) for v in coords)
    data = (f"[out:xml][timeout:{MAX_TIMEOUT}];"
            f"(node({bbox});way({bbox}););(._;>;);out body;")
    return _endpoint(provider) + "?" + urlencode({"data": data})
