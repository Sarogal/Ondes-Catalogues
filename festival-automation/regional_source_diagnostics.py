"""Bounded private diagnostics for approved regional festival index scans.

This persistence contains only trusted index URLs, counters and failure classes:
no HTML, candidate names, arbitrary discovered links, secrets or publishing flags.
It is persisted exclusively by the private intake checkout in the public runner.
"""
from datetime import date
from urllib.parse import urlsplit

from regional_agenda_pagination import canonical_page_url

KEY = "regional_festival_source_diagnostics_review_only"
MAX_RECORDS = 70
MAX_AGE_DAYS = 45
MAX_COUNT = 10000
STATUSES = frozenset(("SCANNED", "INACCESSIBLE"))
DIAGNOSTICS = frozenset((
    "CANDIDATE_LINKS_REVIEW_ONLY",
    "VISIBLE_LINKS_NO_CANDIDATE",
    "NO_VISIBLE_LINKS",
    "FETCH_FAILED",
))


def _safe_url(url, origin, approved, permitted_url):
    if not isinstance(origin, str) or origin not in approved:
        return False
    if not isinstance(url, str) or not permitted_url(url):
        return False
    if url == origin:
        return True
    return canonical_page_url(url, origin, permitted_url) == url


def _bounded_count(value):
    return value if type(value) is int and 0 <= value <= MAX_COUNT else 0


def _safe_previous(key, row, approved, today, permitted_url):
    if not isinstance(row, dict):
        return None
    origin = row.get("source_index")
    if not _safe_url(key, origin, approved, permitted_url):
        return None
    if (row.get("checked_url") != key
            or row.get("region") != approved[origin]
            or row.get("publication_authorized") is not False
            or row.get("status") not in STATUSES):
        return None
    try:
        attempted = date.fromisoformat(row["lastAttempted"])
        successful_raw = row.get("lastSuccessful", "")
        successful = date.fromisoformat(successful_raw) if successful_raw else None
        now = date.fromisoformat(today)
    except (KeyError, ValueError, TypeError):
        return None
    if (attempted > now or (now - attempted).days > MAX_AGE_DAYS
            or successful is not None and successful > attempted):
        return None
    status = row["status"]
    if status == "SCANNED" and successful != attempted:
        return None
    if row.get("page_kind") != ("ROOT" if key == origin else "PAGINATION"):
        return None
    anchors = _bounded_count(row.get("visible_anchors"))
    links = _bounded_count(row.get("thematic_links"))
    if (row.get("page_diagnostic") not in DIAGNOSTICS
            or (status == "INACCESSIBLE" and
                row.get("page_diagnostic") != "FETCH_FAILED")):
        return None
    return {
        "source_index": origin, "checked_url": key,
        "region": approved[origin],
        "page_kind": "ROOT" if key == origin else "PAGINATION",
        "lastAttempted": attempted.isoformat(),
        "lastSuccessful": successful.isoformat() if successful else "",
        "status": status, "page_diagnostic": row["page_diagnostic"],
        "visible_anchors": anchors if status == "SCANNED" else 0,
        "thematic_links": links if status == "SCANNED" else 0,
        "possible_dynamic": row.get("possible_dynamic") is True
        if status == "SCANNED" else False,
        "publication_authorized": False,
    }


def record_regional_diagnostics(state, outcomes, approved, today, permitted_url):
    """Keep per-URL last outcome, including failed fetches, in PRIVATE state.

    Old malformed rows are dropped; a diagnostic can never create fetch targets
    or authorize a festival. Do not persist arbitrary URLs from page HTML.
    """
    if not isinstance(state, dict) or not isinstance(outcomes, list):
        raise ValueError("état de diagnostic régional invalide")
    date.fromisoformat(today)
    old = state.get(KEY, {})
    if not isinstance(old, dict):
        old = {}
    safe = {}
    for key, row in list(old.items())[:MAX_RECORDS * 3]:
        previous = _safe_previous(key, row, approved, today, permitted_url)
        if previous is not None:
            safe[key] = previous
    for row in outcomes:
        if not isinstance(row, dict):
            continue
        origin, url = row.get("index_url"), row.get("checked_url")
        if not _safe_url(url, origin, approved, permitted_url):
            continue
        if row.get("region") != approved[origin]:
            continue
        status = row.get("status")
        if status not in STATUSES:
            continue
        previously = safe.get(url, {})
        links = _bounded_count(row.get("thematic_links"))
        anchors = _bounded_count(row.get("visible_anchors"))
        if status == "SCANNED":
            diagnostic = ("CANDIDATE_LINKS_REVIEW_ONLY" if links
                          else "VISIBLE_LINKS_NO_CANDIDATE" if anchors
                          else "NO_VISIBLE_LINKS")
        else:
            diagnostic = "FETCH_FAILED"
        safe[url] = {
            "source_index": origin, "checked_url": url,
            "region": approved[origin],
            "page_kind": "ROOT" if url == origin else "PAGINATION",
            "lastAttempted": today,
            "lastSuccessful": (today if status == "SCANNED"
                               else previously.get("lastSuccessful", "")),
            "status": status, "page_diagnostic": diagnostic,
            "visible_anchors": anchors if status == "SCANNED" else 0,
            "thematic_links": links if status == "SCANNED" else 0,
            "possible_dynamic": bool(
                status == "SCANNED" and row.get("script_backed_linkless_hint") is True),
            "publication_authorized": False,
        }
    # Bound private storage even if an older state contained excessive rows.
    newest = sorted(safe.items(),
                    key=lambda item: (item[1]["lastAttempted"], item[0]),
                    reverse=True)[:MAX_RECORDS]
    state[KEY] = dict(newest)
    return len(newest)
