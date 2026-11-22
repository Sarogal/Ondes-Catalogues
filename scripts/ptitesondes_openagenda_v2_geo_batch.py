"""Bounded national geometry review: reuse evidence at the SAME pinned venue URL.

Purely private diagnostic, not connected to publisher, scheduler or data patch.
Never return title, UID, venue, city, official URL, coordinates, raw errors,
untrusted reason strings, or source record. Only fixed-schema counts.
"""
from collections import Counter
from datetime import date

from ptitesondes_openagenda_v2_geo_bridge import (
    _url, review_direct_with_independent_geo,
)
from ptitesondes_openagenda_v2_geo_fetch import (
    fetch_official_page, ban_query_for_official_address, fetch_ban_exact,
)

SCHEMA = "ptitesondes.oa2.independent_geometry_batch.v1"
MAX_BATCH = 60


def diagnose_batch(cases, today, *,
                   official_reader=fetch_official_page, geo_reader=fetch_ban_exact):
    """Inspect at most sixty leads with vetted independent official source pins.

    Each supplied reviewed_source MUST be looked up by the caller in an
    independently curated trusted registry; this function never derives a pin
    from OpenAgenda or a collector. The same pinned official page and exact
    BAN search may be cached only within this single invocation.
    """
    if (type(today) is not date or not isinstance(cases, list)
            or not 1 <= len(cases) <= MAX_BATCH
            or not callable(official_reader) or not callable(geo_reader)):
        raise ValueError("invalid_geometry_batch")
    counts = Counter()
    page_cache = {}
    ban_cache = {}
    pages_requested = 0
    ban_requests = 0
    for row in cases:
        if (not isinstance(row, dict) or set(row) != {
                "lead", "api_event", "reviewed_agenda", "reviewed_source"}):
            counts["case_shape_invalid"] += 1
            continue
        source = row["reviewed_source"]
        if (not isinstance(source, dict)
                or set(source) != {"approved_host", "exact_url"}):
            counts["pin_unreviewed"] += 1
            continue
        host, url = source.get("approved_host"), source.get("exact_url")
        if not isinstance(host, str) or _url(url, host=host) is None:
            counts["pin_unreviewed"] += 1
            continue
        # Only an exact pinned HTTPS document is cached across leads.
        key = (host, url)
        if key not in page_cache:
            pages_requested += 1
            try:
                page_cache[key] = official_reader(source)
            except Exception:
                page_cache[key] = None
        page = page_cache[key]
        if (not isinstance(page, dict) or set(page) != {"url", "html"}
                or page.get("url") != url):
            counts["institutional_page_unavailable_or_mismatch"] += 1
            continue
        try:
            q = ban_query_for_official_address(row["lead"], source, page)
        except Exception:
            q = None
        if q is None:
            counts["institutional_address_not_independently_confirmed"] += 1
            continue
        if q not in ban_cache:
            ban_requests += 1
            try:
                ban_cache[q] = geo_reader(q)
            except Exception:
                ban_cache[q] = None
        geo = ban_cache[q]
        if not isinstance(geo, dict):
            counts["ign_ban_unavailable"] += 1
            continue
        try:
            result = review_direct_with_independent_geo(
                row["lead"], row["api_event"], row["reviewed_agenda"],
                source, page, q, geo, today)
        except Exception:
            counts["independent_review_failed_closed"] += 1
            continue
        if result.get("geography_verified") is not True:
            counts["independent_geo_not_concordant"] += 1
        elif result.get("direct_source_structurally_valid") is not True:
            counts["direct_api_structure_or_audience_hold"] += 1
        else:
            counts["geo_and_direct_structurally_verified"] += 1
    return {
        "schema": SCHEMA, "mode": "readonly_private_funnel_count_only",
        "checked_leads": len(cases),
        "pinned_pages_attempted": pages_requested,
        "ign_ban_queries_attempted": ban_requests,
        "reason_counts": dict(sorted(counts.items())),
        "publisher_connected": False, "approval_granted": False,
        "public_writes": 0, "contains_candidate_identifiers": False,
        "organizer_independently_attested": False,
        "event_rights_reviewed": False,
        "category_and_access_fully_verified": False,
        "historic_deduplication_checked": False,
    }
