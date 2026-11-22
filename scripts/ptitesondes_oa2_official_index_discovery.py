"""Discover OpenAgenda root candidates from independently pinned official indexes.

PRIVATE REVIEW QUEUE ONLY. This is a source discovery aid, never a registry
approval. All candidates require independently authenticated agenda UID,
institution attribution, timezone and editorial/rights reviews before any
subsequent use in the trusted institutional registry.

No candidate lead, untrusted search snippet or OpenAgenda metadata can nominate
the official index URL. Public summaries expose only bounded fixed counters.
"""
from html.parser import HTMLParser
from urllib.parse import urlsplit

from ptitesondes_family_national_source_preflight import norm_text
from ptitesondes_openagenda_v2_direct_evidence import SLUG, _uid
from ptitesondes_openagenda_v2_geo_bridge import _url
from ptitesondes_openagenda_v2_geo_fetch import fetch_official_page
from ptitesondes_openagenda_v2_organizer_index import _VisibleAnchors
from ptitesondes_openagenda_v2_institutional_delegation import CUE

SCHEMA = "ptitesondes.oa2.pinned_institution_agenda_discovery.v1"
MAX_HTML = 350_000
MAX_AGENDA_ROWS = 500
MAX_ROOTS = 250


def _root_slug(href):
    """Recognize only absolute HTTPS OpenAgenda agenda ROOT links."""
    if not isinstance(href, str) or len(href) > 1200:
        return None
    try:
        p = urlsplit(href)
        if (p.scheme != "https" or p.hostname != "openagenda.com"
                or p.username or p.password or p.port not in (None, 443)
                or p.query or p.fragment):
            return None
        segments = p.path.strip("/").split("/")
        if len(segments) == 2 and segments[0] in ("fr", "en"):
            segments = segments[1:]
        if len(segments) != 1 or SLUG.fullmatch(segments[0]) is None:
            return None
        return segments[0]
    except ValueError:
        return None


def _empty(reason="unreviewed_institutional_index"):
    return {
        "schema": SCHEMA,
        "reason": reason,
        # These are PRIVATE review candidates, *not* trusted pins.
        "private_review_queue": [],
        "counts": {
            "observed_unique_roots": 0,
            "matched_listed_api_metadata": 0,
            "unlisted_slug_for_api_resolution": 0,
            "ambiguous_api_metadata_held": 0,
        },
        "institution_ownership_attested": False,
        "trusted_registry_mutated": False,
        "approval_granted": False,
        "publisher_connected": False,
        "public_writes": 0,
    }


def _metadata_by_slug(agenda_metadata):
    """Index untrusted reference metadata; duplicates are never auto-selected."""
    if not isinstance(agenda_metadata, list) or len(agenda_metadata) > MAX_AGENDA_ROWS:
        raise ValueError("invalid_agenda_metadata")
    index = {}
    for item in agenda_metadata:
        if (not isinstance(item, dict) or set(item) != {"uid", "slug"}
                or not _uid(item.get("uid"))
                or not isinstance(item.get("slug"), str)
                or SLUG.fullmatch(item["slug"]) is None):
            raise ValueError("invalid_agenda_metadata")
        index.setdefault(item["slug"], []).append(str(item["uid"]))
    return index


def discover_pinned_official_index(pinned_index, fetched_index, agenda_metadata):
    """Generate provisional review entries for ROOT URLs visible on an official page.

    Source host/page are selected separately from the incoming candidate.
    The supplied API metadata is a *matching hint*, not independent proof
    of an institution, agenda administrator or actual event session.
    """
    result = _empty()
    if (not isinstance(pinned_index, dict)
            or set(pinned_index) != {"approved_host", "exact_index_url"}
            or not isinstance(fetched_index, dict)
            or set(fetched_index) != {"url", "html"}):
        return result
    host = pinned_index.get("approved_host")
    page_url = pinned_index.get("exact_index_url")
    if (not isinstance(host, str)
            or _url(page_url, host=host) is None
            or fetched_index.get("url") != page_url):
        return result
    markup = fetched_index.get("html")
    if not isinstance(markup, str) or not 50 <= len(markup) <= MAX_HTML:
        return _empty("institutional_index_unavailable")
    try:
        metadata = _metadata_by_slug(agenda_metadata)
        anchors = _VisibleAnchors()
        anchors.feed(markup)
        anchors.close()
    except (ValueError, TypeError, OverflowError):
        return _empty("invalid_index_or_metadata")
    found = set()
    for href, label in anchors.links:
        if (not isinstance(label, str) or len(label) > 500
                or CUE.search(norm_text(label)) is None):
            continue
        slug = _root_slug(href)
        if slug:
            found.add(slug)
            if len(found) > MAX_ROOTS:
                return _empty("too_many_agenda_roots")

    proposals = []
    counts = result["counts"].copy()
    for slug in sorted(found):
        uids = metadata.get(slug, [])
        # Pending entries are deliberately incompatible with the trusted
        # registry's exact five-field schema.
        if len(uids) == 1:
            status = "api_slug_match_requires_independent_review"
            counts["matched_listed_api_metadata"] += 1
            uid = uids[0]
        elif not uids:
            status = "agenda_uid_unresolved"
            counts["unlisted_slug_for_api_resolution"] += 1
            uid = None
        else:
            status = "ambiguous_api_metadata_held"
            counts["ambiguous_api_metadata_held"] += 1
            uid = None
        proposals.append({
            "institution_host": host,
            "institution_index_url": page_url,
            "observed_agenda_slug": slug,
            "listed_agenda_uid": uid,
            "status": status,
            "approved": False,
            "timezone": None,
            "review_required": True,
        })
    counts["observed_unique_roots"] = len(found)
    return dict(result, reason="index_observed_requires_review",
                private_review_queue=proposals, counts=counts)


def discover_from_live_official_index(pinned_index, agenda_metadata, opener=None):
    """Fetch a pre-pinned official page with hard HTTP checks; read-only."""
    try:
        page = fetch_official_page({
            "approved_host": pinned_index["approved_host"],
            "exact_url": pinned_index["exact_index_url"],
        }, opener=opener)
    except (ValueError, TypeError, KeyError, OSError):
        return _empty("institutional_index_unavailable")
    return discover_pinned_official_index(pinned_index, page, agenda_metadata)


def redacted_discovery_counts(report):
    """Safe for aggregate dashboard: no slugs, hosts, pages or identifiers."""
    empty = _empty("unreviewed_institutional_index")
    if not isinstance(report, dict) or report.get("schema") != SCHEMA:
        report = empty
    counts = report.get("counts")
    if not isinstance(counts, dict):
        counts = empty["counts"]
    allow = empty["counts"]
    safe = {}
    for field in allow:
        n = counts.get(field)
        safe[field] = n if type(n) is int and 0 <= n <= MAX_ROOTS else 0
    return {
        "schema": SCHEMA,
        "counts": safe,
        "contains_private_identifiers": False,
        "institution_ownership_attested": False,
        "approval_granted": False,
        "publisher_connected": False,
        "public_writes": 0,
    }
