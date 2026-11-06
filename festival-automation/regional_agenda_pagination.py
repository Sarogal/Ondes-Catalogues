"""Bounded, next-day-only pagination of curator-approved regional event indexes.

Discovered page parameters are *not* arbitrary URLs: exact approved hostname,
exact index path, the same fixed query if any, and a single integer page=1..6.
All pages are observed privately. No event detail URLs are ever fetched here.
"""
from datetime import date, timedelta
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

MAX_PAGE = 6
MAX_PAGE_QUEUE = 45
MAX_PAGES_DISCOVERED_PER_SCAN = 2
PAGE_STALE_DAYS = 30
RECHECK_DAYS = 7
STATUS = "UNVERIFIED_INDEX_PAGE"


def canonical_page_url(value, origin, permitted_url):
    """Return canonical URL iff it is a single tightly scoped page parameter."""
    if not isinstance(value, str) or not isinstance(origin, str):
        return None
    try:
        base = urlsplit(origin)
        target = urlsplit(value)
        if (not permitted_url(value) or base.hostname != target.hostname
                or base.scheme != "https" or target.scheme != "https"
                or base.netloc != target.netloc or base.path != target.path
                or target.fragment or base.fragment):
            return None
        original = parse_qsl(base.query, keep_blank_values=True, strict_parsing=True)
        actual = parse_qsl(target.query, keep_blank_values=True, strict_parsing=True)
        if any(k == "page" for k, _ in original):
            return None
        added = [(k, v) for k, v in actual if k == "page"]
        remain = [(k, v) for k, v in actual if k != "page"]
        if len(added) != 1 or remain != original:
            return None
        raw_number = added[0][1]
        if not raw_number.isascii() or not raw_number.isdecimal():
            return None
        number = int(raw_number)
        if not 1 <= number <= MAX_PAGE or raw_number != str(number):
            return None
        canonical = urlunsplit((base.scheme, base.netloc, base.path,
                               urlencode(original + [("page", str(number))]), ""))
        return canonical if target.geturl() == canonical else None
    except (ValueError, TypeError):
        return None


def discover_pagination(html, source_page, origin, anchors_class, permitted_url):
    """Only visible, explicitly labelled index pagination links are accepted."""
    if not isinstance(html, str) or len(html) > 650_000:
        raise ValueError("HTML index inadmissible")
    parser = anchors_class()
    parser.feed(html)
    pages = []
    for href, label, _prefix in parser.anchors[:500]:
        if not isinstance(href, str) or not isinstance(label, str):
            continue
        label = " ".join(label.lower().split()).strip(" >»❯→")
        if label not in ("1", "2", "3", "4", "5", "6", "suivant", "page suivante", "next"):
            continue
        page_url = canonical_page_url(urljoin(source_page, href), origin, permitted_url)
        if page_url and page_url != source_page and page_url not in pages:
            pages.append(page_url)
            if len(pages) == MAX_PAGES_DISCOVERED_PER_SCAN:
                break
    return pages


def prune_page_queue(pending, approved, today, permitted_url):
    """Fail closed for hostile private state and bound long-term storage."""
    if not isinstance(pending, dict):
        raise ValueError("file pagination invalide")
    now = date.fromisoformat(today)
    kept = {}
    for key, rec in list(pending.items())[:MAX_PAGE_QUEUE * 3]:
        if not isinstance(rec, dict):
            continue
        origin = rec.get("source_index")
        if (not isinstance(origin, str) or origin not in approved
                or rec.get("publication_authorized") is not False
                or rec.get("status") != STATUS
                or canonical_page_url(key, origin, permitted_url) != key
                or rec.get("candidate_url") != key):
            continue
        try:
            first = date.fromisoformat(rec["firstSeen"])
            last = date.fromisoformat(rec["lastSeen"])
            checked = date.fromisoformat(rec["lastChecked"]) if rec.get("lastChecked") else None
            # Legacy lastChecked values represented completed successful scans.
            attempted = (date.fromisoformat(rec["lastAttempted"])
                         if rec.get("lastAttempted") else checked)
        except (KeyError, TypeError, ValueError):
            continue
        if (first > last or last > now or first > now
                or now - last > timedelta(days=PAGE_STALE_DAYS)
                or checked is not None and (checked > now or checked < first)
                or attempted is not None and (attempted > now or attempted < first)
                or checked is not None and attempted is not None
                and checked > attempted):
            continue
        kept[key] = {"candidate_url": key, "source_index": origin,
                     "firstSeen": first.isoformat(), "lastSeen": last.isoformat(),
                     "lastChecked": checked.isoformat() if checked else "",
                     "lastAttempted": attempted.isoformat() if attempted else "",
                     "status": STATUS, "publication_authorized": False}
        if len(kept) >= MAX_PAGE_QUEUE:
            break
    pending.clear()
    pending.update(kept)


def eligible_page_checks(pending, approved, today, permitted_url, limit=2):
    """Never crawl discovered pagination on its first day."""
    if not 0 <= limit <= 2:
        raise ValueError("budget pagination invalide")
    now = date.fromisoformat(today)
    due = []
    for url, rec in pending.items():
        origin = rec.get("source_index") if isinstance(rec, dict) else None
        if (not isinstance(origin, str) or origin not in approved
                or canonical_page_url(url, origin, permitted_url) != url
                or not isinstance(rec, dict) or rec.get("status") != STATUS
                or rec.get("publication_authorized") is not False):
            continue
        try:
            first = date.fromisoformat(rec["firstSeen"])
            checked = date.fromisoformat(rec["lastChecked"]) if rec.get("lastChecked") else None
            attempted = (date.fromisoformat(rec["lastAttempted"])
                         if rec.get("lastAttempted") else checked)
        except (KeyError, TypeError, ValueError):
            continue
        # Failure retry is next-day eligible, but never same-day eligible.
        if (first >= now or attempted is not None and attempted >= now
                or checked is not None and
                (now - checked < timedelta(days=RECHECK_DAYS))):
            continue
        # Oldest attempt first prevents an unavailable page from starvation.
        due.append((attempted.isoformat() if attempted else "",
                    first.isoformat(), url, origin))
    due.sort()
    return [(origin, url) for _attempted, _first, url, origin in due[:limit]]


def remember_page_links(pending, urls, origin, today, permitted_url):
    """Cache bounded index links, never event URLs or approval fields."""
    count = 0
    for url in urls:
        if canonical_page_url(url, origin, permitted_url) != url:
            continue
        previous = pending.get(url)
        if previous is not None and previous.get("source_index") != origin:
            continue
        if previous is None and len(pending) >= MAX_PAGE_QUEUE:
            continue
        pending[url] = {
            "candidate_url": url, "source_index": origin,
            "firstSeen": previous["firstSeen"] if previous else today,
            "lastSeen": today,
            "lastChecked": previous["lastChecked"] if previous else "",
            "lastAttempted": previous.get("lastAttempted", previous["lastChecked"]) if previous else "",
            "status": STATUS, "publication_authorized": False,
        }
        if previous is None:
            count += 1
    return count
