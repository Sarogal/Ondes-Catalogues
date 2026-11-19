"""First-party event page discovery from a separately vetted organizer INDEX.

The index URL and host are curated ONCE per organizer, not per event.
Only visible same-host links on the independently fetched index can nominate
an event page. A candidate's URLs, API fields and metadata NEVER choose the
official page. The nominated page must be fetched separately and corroborated
by the existing OpenAgenda and first-party session validators.

Pure read-only stage; this is neither institutional ownership attestation
nor an event approval. Any chosen URL stays PRIVATE to a trusted caller.
"""
from html.parser import HTMLParser
from urllib.parse import urljoin

from ptitesondes_family_national_source_preflight import norm_text
from ptitesondes_openagenda_v2_geo_bridge import _url

SCHEMA = "ptitesondes.oa2.independent_organizer_index.v1"
MAX_INDEX_HTML = 350_000
MAX_ANCHORS = 2400
MAX_EVENT_URL = 1800
MAX_LABEL = 260
HIDDEN = frozenset(("script", "style", "noscript", "template", "head",
                    "iframe", "svg"))
VOID = frozenset(("br", "img", "input", "meta", "link", "source",
                  "hr", "wbr", "area", "embed"))


class _VisibleAnchors(HTMLParser):
    """Only read links with visible text; hidden descendants cannot vote."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.links = []
        self.active = []

    def _hidden(self):
        return self.stack[-1][1] if self.stack else False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        style = str(a.get("style") or "").lower()
        hidden = (self._hidden() or tag in HIDDEN or "hidden" in a
                  or str(a.get("aria-hidden") or "").lower() == "true"
                  or "display:none" in style.replace(" ", "")
                  or "visibility:hidden" in style.replace(" ", ""))
        if tag not in VOID:
            self.stack.append((tag, hidden))
        if tag == "a":
            if len(self.links) + len(self.active) >= MAX_ANCHORS:
                raise ValueError("too_many_index_anchors")
            self.active.append({
                "depth": len(self.stack),
                "href": a.get("href"),
                "parts": [],
                "hidden": hidden,
            })

    def handle_data(self, data):
        if self._hidden():
            return
        for link in self.active:
            link["parts"].append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.active:
            current = self.active.pop()
            if not current["hidden"]:
                self.links.append((current["href"], " ".join(current["parts"])))
        for pos in range(len(self.stack)-1, -1, -1):
            if self.stack[pos][0] == tag:
                del self.stack[pos:]
                break


def discover_from_reviewed_index(lead, reviewed_index, fetched_index):
    """Returns an EVENT URL only to an authorized internal caller.

    No URL is logged, returned via public batch diagnostics, or taken from
    intake. Caller must fetch the nominated URL using a bounded HTTPS reader
    with redirects DISABLED, before calling any joined verification.
    """
    held = {
        "schema": SCHEMA, "indexed_event_link_confirmed": False,
        "reason": "invalid_or_unreviewed_index",
        "approval_granted": False, "publisher_connected": False,
        "public_writes": 0, "owner_attested": False,
    }
    if (not isinstance(lead, dict)
            or not isinstance(reviewed_index, dict)
            or set(reviewed_index) != {"approved_host", "exact_index_url"}
            or not isinstance(fetched_index, dict)
            or set(fetched_index) != {"url", "html"}):
        return held
    host = reviewed_index.get("approved_host")
    url = reviewed_index.get("exact_index_url")
    if (not isinstance(host, str)
            or _url(url, host=host) is None
            or fetched_index.get("url") != url):
        return held
    title = lead.get("title")
    if (not isinstance(title, str) or not norm_text(title)
            or len(title) > MAX_LABEL):
        return dict(held, reason="candidate_title_invalid")
    html = fetched_index.get("html")
    if (not isinstance(html, str)
            or not 50 <= len(html) <= MAX_INDEX_HTML):
        return dict(held, reason="index_document_unavailable")
    parser = _VisibleAnchors()
    try:
        parser.feed(html)
        parser.close()
    except (TypeError, ValueError):
        return dict(held, reason="index_document_unavailable")
    matches = set()
    for href, label in parser.links:
        if (not isinstance(href, str) or not 0 < len(href) <= MAX_EVENT_URL
                or not isinstance(label, str)
                or len(label) > MAX_LABEL
                or norm_text(label) != norm_text(title)):
            continue
        target = urljoin(url, href)
        parsed = _url(target, host=host)
        if (parsed is None or parsed.query or parsed.fragment
                or target == url):
            continue
        matches.add(target)
        if len(matches) > 1:
            return dict(held, reason="ambiguous_official_event_links")
    if not matches:
        return dict(held, reason="no_independently_indexed_event_link")
    picked = next(iter(matches))
    return dict(
        held, indexed_event_link_confirmed=True, reason="indexed_page_requires_fetch_and_checks",
        reviewed_organizer={"approved_host": host, "exact_url": picked},
    )


def check_indexed_event_fetch(result, fetched_event):
    """Exact nominated URL must be fetched; this still does NOT approve it."""
    if (not isinstance(result, dict)
            or result.get("schema") != SCHEMA
            or result.get("indexed_event_link_confirmed") is not True
            or not isinstance(fetched_event, dict)
            or set(fetched_event) != {"url", "html"}):
        return False
    pin = result.get("reviewed_organizer")
    if (not isinstance(pin, dict)
            or set(pin) != {"approved_host", "exact_url"}
            or _url(pin.get("exact_url"), host=pin.get("approved_host")) is None):
        return False
    content = fetched_event.get("html")
    return (fetched_event.get("url") == pin["exact_url"]
            and isinstance(content, str)
            and 50 <= len(content) <= 500_000)


def redacted_index_stage(result):
    """Fixed-schema diagnostics safe for aggregate public workflow summaries."""
    known = frozenset((
        "invalid_or_unreviewed_index", "candidate_title_invalid",
        "index_document_unavailable", "ambiguous_official_event_links",
        "no_independently_indexed_event_link",
        "indexed_page_requires_fetch_and_checks",
    ))
    reason = result.get("reason") if isinstance(result, dict) else None
    if reason not in known:
        reason = "invalid_or_unreviewed_index"
    return {
        "schema": SCHEMA,
        "reason": reason,
        "indexed_event_link_confirmed": (
            isinstance(result, dict)
            and result.get("indexed_event_link_confirmed") is True),
        "contains_event_url": False, "approval_granted": False,
        "publisher_connected": False, "public_writes": 0,
    }
