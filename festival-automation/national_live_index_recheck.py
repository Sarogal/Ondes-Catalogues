"""Bounded live rediscovery of a festival detail in an approved index.

Private leads identify what to look for, never which new pages may be fetched.
Re-fetch a fixed approved regional index; follow only visibly linked canonical
pagination on that same approved HTTPS path (maximum three index requests).
Each publisher and preflight run must independently rediscover the exact
visible titled link before requesting the event detail.
"""
from collections import deque

from national_detail_qualification import _seen_again
from official_watch import permitted_url
from regional_agenda_pagination import canonical_page_url, discover_pagination
from regional_festival_discovery import APPROVED, RegionalEventAnchors

MAX_INDEX_FETCHES = 3


def live_index_for_exact_link(source, fetch):
    if not isinstance(source, dict):
        return None
    origin = source.get("index_url")
    requested_page = source.get("index_page")
    if origin not in APPROVED or not isinstance(requested_page, str):
        return None
    if (requested_page != origin
            and canonical_page_url(requested_page, origin, permitted_url)
                != requested_page):
        return None
    if (not isinstance(source.get("title"), str)
            or not isinstance(source.get("url"), str)):
        return None
    pending = deque([requested_page])
    if requested_page != origin:
        # A previously linked page can be stale; also consult the fixed root.
        pending.append(origin)
    visited = set()
    while pending and len(visited) < MAX_INDEX_FETCHES:
        current = pending.popleft()
        if current in visited:
            continue
        visited.add(current)
        # All requests are to either an immutable approved root or a
        # canonical, visibly linked page (never a new host or arbitrary query).
        html = fetch(current)
        if _seen_again(html, {**source, "index_page": current}):
            return html
        pages = discover_pagination(
            html, current, origin, RegionalEventAnchors, permitted_url)
        for page in pages:
            if (page not in visited and page not in pending
                    and len(visited) + len(pending) < MAX_INDEX_FETCHES):
                pending.append(page)
    return None
