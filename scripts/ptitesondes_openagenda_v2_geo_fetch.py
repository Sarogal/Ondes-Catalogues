"""Bounded read-only retrieval for independently pinned venue geocoding.

This module is NOT attached to the publisher or a scheduled workflow. The
reviewed_source pin must come from a separately maintained trusted registry,
never from the incoming event or an OpenAgenda-provided URL.

All network results are treated as untrusted. Fail closed, with fixed reason
codes only; never return arbitrary HTTP error messages or event identifiers.
"""
import json
from urllib.parse import quote, parse_qs
from urllib.request import Request, HTTPRedirectHandler, build_opener

from ptitesondes_openagenda_v2_geo_bridge import (
    _url, _place_address, review_direct_with_independent_geo,
    MAX_HTML,
)

GEO_ENDPOINT = "https://data.geopf.fr/geocodage/search"
MAX_GEO_BYTES = 200_000
MAX_QUERY_LENGTH = 320
TIMEOUT = 12
SCHEMA = "ptitesondes.oa2.trusted_geo_fetch_diagnostic.v1"


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def _read(url, content_type, byte_limit, opener):
    """GET one pinned HTTPS URL; never follow redirect or return raw errors."""
    req = Request(url, headers={
        "Accept": content_type,
        "User-Agent": "PtitesOndesIndependentVenueGeo/1.0",
    })
    getter = opener or build_opener(_NoRedirect()).open
    try:
        with getter(req, timeout=TIMEOUT) as res:
            if res.status != 200 or res.geturl() != url:
                raise ValueError("source_not_exact")
            mime = (res.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
            if ((content_type == "text/html" and
                 mime not in ("text/html", "application/xhtml+xml"))
                    or (content_type == "application/json" and
                        mime not in ("application/json", "application/geo+json"))):
                raise ValueError("unexpected_source_media_type")
            data = res.read(byte_limit + 1)
    except Exception:
        # A network exception can contain request details, including private
        # source names. Never return or log the exception object.
        raise ValueError("source_fetch_unavailable") from None
    if not data or len(data) > byte_limit:
        raise ValueError("source_response_empty_or_oversized")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError("invalid_source_utf8") from None


def fetch_official_page(reviewed_source, opener=None):
    """Fetch only a source already independently pinned by a trusted caller."""
    if not isinstance(reviewed_source, dict) or set(reviewed_source) != {
            "approved_host", "exact_url"}:
        raise ValueError("untrusted_source_pin")
    url = reviewed_source.get("exact_url")
    host = reviewed_source.get("approved_host")
    if (not isinstance(host, str) or _url(url, host=host) is None):
        raise ValueError("untrusted_source_pin")
    html = _read(url, "text/html", MAX_HTML, opener)
    return {"url": url, "html": html}


def ban_query_for_official_address(lead, reviewed_source, official_page):
    """Only an independent JSON-LD address can be sent to IGN/BAN."""
    if (not isinstance(lead, dict) or not isinstance(reviewed_source, dict)
            or not isinstance(official_page, dict)
            or set(reviewed_source) != {"approved_host", "exact_url"}
            or set(official_page) != {"url", "html"}
            or _url(reviewed_source.get("exact_url"),
                    host=reviewed_source.get("approved_host")) is None
            or official_page.get("url") != reviewed_source.get("exact_url")):
        return None
    found = _place_address(
        official_page["html"], lead.get("venue"), lead.get("city"))
    if found is None:
        return None
    number, street, postcode, locality, _aliases = found
    address = f"{number} {street} {postcode} {locality}"
    if not 8 <= len(address) <= MAX_QUERY_LENGTH:
        return None
    return GEO_ENDPOINT + "?q=" + quote(address, safe="") + "&limit=2"


def fetch_ban_exact(query_url, opener=None):
    """Read only the bounded official IGN/BAN exact-address search endpoint."""
    u = _url(query_url, host="data.geopf.fr", path="/geocodage/search")
    if u is None:
        raise ValueError("invalid_geocoder_url")
    args = parse_qs(u.query, keep_blank_values=True)
    if (set(args) != {"q", "limit"} or len(args["q"]) != 1
            or not 8 <= len(args["q"][0]) <= MAX_QUERY_LENGTH
            or args["limit"] != ["2"]):
        raise ValueError("invalid_geocoder_query")
    raw = _read(query_url, "application/json", MAX_GEO_BYTES, opener)
    try:
        geo = json.loads(raw)
    except (ValueError, TypeError):
        raise ValueError("invalid_geocoder_json") from None
    if not isinstance(geo, dict) or geo.get("type") != "FeatureCollection":
        raise ValueError("invalid_geocoder_json")
    return geo


def diagnose_pinned_venue(
        lead, api_event, reviewed_agenda, reviewed_source, today,
        official_reader=fetch_official_page, geo_reader=fetch_ban_exact):
    """One independently pinned venue check; no implicit source approval.

    Caller must select the vetted host+page and separately fetch the trusted
    OpenAgenda API event. Do NOT use OpenAgenda's own organiser URL as the pin.
    """
    report = {
        "schema": SCHEMA,
        "geography_verified": False,
        "direct_source_structurally_valid": False,
        "approval_granted": False, "publisher_connected": False,
        "public_writes": 0,
        "reason": "trusted_independent_geometry_not_verified",
    }
    try:
        page = official_reader(reviewed_source)
        query = ban_query_for_official_address(
            lead, reviewed_source, page)
        if query is None:
            return report
        geo = geo_reader(query)
        proof = review_direct_with_independent_geo(
            lead, api_event, reviewed_agenda, reviewed_source,
            page, query, geo, today)
        # Producer-owned structural reasons only; no event/title/URL leaks.
        if proof["geography_verified"] and proof["direct_source_structurally_valid"]:
            return dict(report, geography_verified=True,
                        direct_source_structurally_valid=True,
                        reason="independent_geo_and_direct_structure_verified_only")
        return dict(report,
                    geography_verified=proof["geography_verified"] is True,
                    reason="independent_geo_or_direct_structure_hold")
    except Exception:
        return report
