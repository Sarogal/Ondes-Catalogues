"""Generic RSS 2.0 / Atom first-party event link nomination, read-only.

Only a separately curated official feed's exact HTTPS URL can be inspected.
Feed item titles locate candidate event PAGES, not event dates or evidence
of age, organizer ownership, reuse rights or publication eligibility.

This parser does not fetch anything. Never print feed item titles, UIDs, URLs
or arbitrary source errors in an Actions summary or public CI.
"""
from urllib.parse import urljoin
from xml.etree import ElementTree

from ptitesondes_family_national_source_preflight import norm_text
from ptitesondes_openagenda_v2_geo_bridge import _url

SCHEMA = "ptitesondes.oa2.first_party_feed_nomination.v1"
MAX_FEED = 450_000
MAX_ITEMS = 600
MAX_NAME = 260
MAX_URL = 1800
ATOM = "{http://www.w3.org/2005/Atom}"
FEED_MIMES = frozenset((
    "application/rss+xml", "application/atom+xml",
    "application/xml", "text/xml",
))
KNOWN_REASONS = frozenset((
    "invalid_reviewed_feed", "candidate_title_invalid",
    "official_feed_unavailable", "feed_format_not_supported",
    "ambiguous_first_party_event_links",
    "no_exact_first_party_event_link",
    "first_party_feed_link_needs_direct_event_proof",
))


def _held(reason="invalid_reviewed_feed"):
    return {
        "schema": SCHEMA,
        "reason": reason,
        "first_party_event_link_nominated": False,
        "organizer_ownership_attested": False,
        "approval_granted": False,
        "publisher_connected": False,
        "public_writes": 0,
    }


def _label(node):
    if node is None:
        return ""
    text = "".join(node.itertext())
    return text if len(text) <= MAX_NAME else ""


def _entry_urls(entry, kind):
    if kind == "rss":
        for link in entry.findall("link"):
            if link.text and not list(link):
                yield link.text.strip()
    else:
        for link in entry.findall(ATOM + "link"):
            if (link.get("rel", "alternate") == "alternate"
                    and link.get("type", "text/html") == "text/html"
                    and not list(link)):
                yield link.get("href")


def nominate_from_reviewed_feed(lead, reviewed_feed, fetched_feed):
    """Return private organizer page pin only after exact first-party matching.

    Format belongs to the approved registry, not to the untrusted lead.
    Caller must fetch the nominated page with a bounded no-redirect reader,
    then run the joined GPS/source/session checks. Never treat an RSS pubDate
    as the event's scheduled date.
    """
    if (not isinstance(lead, dict)
            or not isinstance(reviewed_feed, dict)
            or set(reviewed_feed) != {
                "approved_host", "exact_feed_url", "feed_format"}
            or not isinstance(fetched_feed, dict)
            or set(fetched_feed) != {"url", "content", "content_type"}):
        return _held()
    host = reviewed_feed.get("approved_host")
    source_url = reviewed_feed.get("exact_feed_url")
    kind = reviewed_feed.get("feed_format")
    if (not isinstance(host, str) or kind not in ("rss", "atom")
            or _url(source_url, host=host) is None
            or fetched_feed.get("url") != source_url):
        return _held()
    target_title = lead.get("title")
    if (not isinstance(target_title, str)
            or not 1 <= len(target_title) <= MAX_NAME
            or not norm_text(target_title)):
        return _held("candidate_title_invalid")
    content = fetched_feed.get("content")
    mime = fetched_feed.get("content_type")
    if (not isinstance(content, str)
            or not 30 <= len(content) <= MAX_FEED
            or not isinstance(mime, str)
            or mime.split(";", 1)[0].strip().lower() not in FEED_MIMES):
        return _held("official_feed_unavailable")
    # ElementTree has no external HTTP resolver; explicitly refuse DTD and
    # internal entity definitions, even when the XML parser would support them.
    if "<!doctype" in content.lower() or "<!entity" in content.lower():
        return _held("feed_format_not_supported")
    try:
        root = ElementTree.fromstring(content)
    except (ElementTree.ParseError, ValueError):
        return _held("feed_format_not_supported")
    if kind == "rss":
        if root.tag != "rss" or root.find("channel") is None:
            return _held("feed_format_not_supported")
        items = root.find("channel").findall("item")
        title_tag = "title"
    else:
        if root.tag != ATOM + "feed":
            return _held("feed_format_not_supported")
        items = root.findall(ATOM + "entry")
        title_tag = ATOM + "title"
    if len(items) > MAX_ITEMS:
        return _held("feed_format_not_supported")
    matches = set()
    for entry in items:
        if norm_text(_label(entry.find(title_tag))) != norm_text(target_title):
            continue
        # A single item containing several distinct first-party links is
        # ambiguous, even when they share an exact matching item title.
        item_matches = set()
        for raw in _entry_urls(entry, kind):
            if not isinstance(raw, str) or not 0 < len(raw) <= MAX_URL:
                continue
            target = urljoin(source_url, raw)
            u = _url(target, host=host)
            if (u is None or u.query or u.fragment or target == source_url):
                continue
            item_matches.add(target)
        if len(item_matches) > 1:
            return _held("ambiguous_first_party_event_links")
        matches.update(item_matches)
        if len(matches) > 1:
            return _held("ambiguous_first_party_event_links")
    if not matches:
        return _held("no_exact_first_party_event_link")
    return dict(
        _held("first_party_feed_link_needs_direct_event_proof"),
        first_party_event_link_nominated=True,
        reviewed_organizer={
            "approved_host": host, "exact_url": next(iter(matches))},
    )


def verify_nominated_feed_page(nomination, fetched_event):
    """Exact URL, bounded HTML: still no admission, metadata or rights claim."""
    if (not isinstance(nomination, dict)
            or nomination.get("schema") != SCHEMA
            or nomination.get("first_party_event_link_nominated") is not True
            or not isinstance(fetched_event, dict)
            or set(fetched_event) != {"url", "html"}):
        return False
    pin = nomination.get("reviewed_organizer")
    if (not isinstance(pin, dict) or set(pin) != {
            "approved_host", "exact_url"} or
            _url(pin.get("exact_url"), host=pin.get("approved_host")) is None):
        return False
    html = fetched_event.get("html")
    return (fetched_event.get("url") == pin["exact_url"]
            and isinstance(html, str) and 50 <= len(html) <= 500_000)


def redacted_feed_stage(nomination):
    """Safe fixed-schema summary for public Actions (never raw feed data)."""
    reason = nomination.get("reason") if isinstance(nomination, dict) else None
    if reason not in KNOWN_REASONS:
        reason = "invalid_reviewed_feed"
    return {
        "schema": SCHEMA,
        "reason": reason,
        "contains_event_url_or_identifiers": False,
        "approval_granted": False,
        "publisher_connected": False,
        "public_writes": 0,
    }
