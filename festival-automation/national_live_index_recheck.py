"""Bounded live rediscovery of a festival detail in an approved index.

Private leads identify what to look for, never which new pages may be fetched.
Re-fetch a fixed approved regional index; follow only visibly linked canonical
pagination on that same approved HTTPS path (maximum six index requests).
Each publisher and preflight run must independently rediscover the exact
visible titled link before requesting the event detail.
"""
from collections import deque
from urllib.parse import urljoin, urlsplit, parse_qs

from national_detail_qualification import _seen_again
from official_watch import permitted_url
from regional_agenda_pagination import canonical_page_url
from regional_festival_discovery import APPROVED, RegionalEventAnchors

MAX_INDEX_FETCHES = 6
MAX_ANCHORS = 500
PAGINATION_LABELS = frozenset({
    "1", "2", "3", "4", "5", "6",
    "suivant", "page suivante", "next",
})


def visible_canonical_pages(html, source_page, origin):
    """Follow only visible pagination links, never private paths or redirects.

    The regional discovery scan intentionally queues at most two pages.
    Reproof of an EXACT already-discovered event must cover deeper pages
    (e.g. page 4) without changing the broad crawler or its trust scope.
    """
    if not isinstance(html, str) or not 0 < len(html) <= 650_000:
        raise ValueError("Unusable approved institutional index HTML")
    parser = RegionalEventAnchors()
    parser.feed(html)
    parser.close()
    pages = set()
    for href, label, _prefix in parser.anchors[:MAX_ANCHORS]:
        if not isinstance(href, str) or not isinstance(label, str):
            continue
        label = " ".join(label.lower().split()).strip(" >»❯→")
        if label not in PAGINATION_LABELS:
            continue
        target = canonical_page_url(
            urljoin(source_page, href), origin, permitted_url)
        if target is not None:
            pages.add(target)
    # Exact canonical numbered pages only, from the already approved root.
    # Never trust a URL carried by a report, or page=0 / page=999.
    return sorted(
        pages,
        key=lambda page: int(parse_qs(urlsplit(page).query)["page"][0]),
    )




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
        pages = visible_canonical_pages(html, current, origin)
        for page in pages:
            if (page not in visited and page not in pending
                    and len(visited) + len(pending) < MAX_INDEX_FETCHES):
                pending.append(page)
    return None
