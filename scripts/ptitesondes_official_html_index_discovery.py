"""Read-only generic same-host event-page discovery from independently pinned HTML.

An institution's exact approved index URL must be selected independently of
all candidates. Every discovered link is only a PRIVATE ROUTING SUGGESTION.
No date, venue, child age, source rights, origin ownership or publication can
be inferred from an index link. The child's full page must be separately
fetched and verified using the existing evidence gates.

The module does no I/O by default; the optional trusted reader uses the
already hardened exact-HTTPS/no-redirect official page transport.
"""
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from ptitesondes_family_national_source_preflight import norm_text
from ptitesondes_openagenda_v2_geo_bridge import _url
from ptitesondes_openagenda_v2_geo_fetch import fetch_official_page

SCHEMA = "ptitesondes.official_html_index_private_routing.v1"
MAX_HTML = 400_000
MAX_LINKS = 1500
MAX_PROPOSALS = 200
MAX_LABEL = 260
MAX_DEPTH = 70
VOID = frozenset(("br", "img", "input", "meta", "link", "source",
                  "hr", "wbr", "area", "embed"))
HIDDEN = frozenset(("script", "style", "noscript", "template", "head",
                    "iframe", "svg", "nav", "footer", "header"))


def _blank(reason="invalid_or_unreviewed_index"):
    return {
        "schema": SCHEMA,
        "stage": reason,
        "private_routing_proposals": [],
        "counts": {
            "visible_index_anchors": 0,
            "same_host_child_pages": 0,
            "out_of_scope_links": 0,
            "duplicate_child_links": 0,
        },
        "independent_event_session_verified": False,
        "rights_reviewed": False,
        "institution_owner_attested": False,
        "approval_granted": False,
        "publisher_connected": False,
        "public_writes": 0,
    }


class _OfficialIndexLinks(HTMLParser):
    """Visible anchors in <main>, excluding site navigation and hidden trees."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.active = []
        self.links = []

    def handle_starttag(self, tag, attrs):
        if len(self.stack) >= MAX_DEPTH:
            raise ValueError("index_structure_too_deep")
        attributes = dict(attrs)
        css = str(attributes.get("style") or "").lower().replace(" ", "")
        parent = self.stack[-1] if self.stack else (False, False)
        hidden = (
            parent[1] or tag in HIDDEN or "hidden" in attributes
            or str(attributes.get("aria-hidden") or "").lower() == "true"
            or "display:none" in css or "visibility:hidden" in css
        )
        in_main = parent[0] or tag == "main"
        if tag not in VOID:
            self.stack.append((in_main, hidden, tag))
        if tag == "a":
            if len(self.links) + len(self.active) >= MAX_LINKS:
                raise ValueError("too_many_links")
            self.active.append({
                "href": attributes.get("href"),
                "parts": [],
                "eligible": in_main and not hidden,
            })

    def handle_data(self, data):
        if self.stack and self.stack[-1][1]:
            return
        for item in self.active:
            if item["eligible"]:
                item["parts"].append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.active:
            item = self.active.pop()
            if item["eligible"]:
                self.links.append((item["href"], " ".join(item["parts"])))
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][2] == tag:
                del self.stack[i:]
                break


def discover_html_event_pages(reviewed_index, fetched_page):
    """Suggest child URLs from a trusted index, not independently verified events.

    reviewed_index must come from a separately approved source authority,
    never an incoming candidate, search snippet, OpenAgenda or ODS.
    """
    base = _blank()
    if (not isinstance(reviewed_index, dict)
            or set(reviewed_index) != {"approved_host", "exact_index_url"}
            or not isinstance(fetched_page, dict)
            or set(fetched_page) != {"url", "html"}):
        return base
    host, page = reviewed_index.get("approved_host"), reviewed_index.get("exact_index_url")
    if (not isinstance(host, str) or _url(page, host=host) is None
            or fetched_page["url"] != page):
        return base
    markup = fetched_page["html"]
    if not isinstance(markup, str) or not 50 <= len(markup) <= MAX_HTML:
        return _blank("index_html_unavailable")
    parser = _OfficialIndexLinks()
    try:
        parser.feed(markup)
        parser.close()
    except (ValueError, TypeError, OverflowError):
        return _blank("index_html_unavailable")
    counts = base["counts"].copy()
    seen = set()
    proposals = []
    for href, label in parser.links:
        counts["visible_index_anchors"] += 1
        if (not isinstance(href, str) or not 1 <= len(href) <= 1500
                or not isinstance(label, str)
                or not 3 <= len(label) <= MAX_LABEL
                or not norm_text(label)):
            counts["out_of_scope_links"] += 1
            continue
        # Resolve only a relative path or an exact HTTPS URL; no scheme-relative,
        # javascript:, mailto:, query-only, or fragment-only links.
        try:
            parsed = urlsplit(href)
            if (href.startswith(("//", "#", "?"))
                    or parsed.scheme not in ("", "https")
                    or parsed.fragment or parsed.query):
                counts["out_of_scope_links"] += 1
                continue
            target = urljoin(page, href)
            dest = _url(target, host=host)
            if dest is None or dest.query or dest.fragment or target == page:
                counts["out_of_scope_links"] += 1
                continue
        except (ValueError, TypeError):
            counts["out_of_scope_links"] += 1
            continue
        if target in seen:
            counts["duplicate_child_links"] += 1
            continue
        seen.add(target)
        proposals.append({
            "url": target,  # PRIVATE only, never place in public report
            "index_label_hint": " ".join(label.split()),
            "status": "requires_exact_child_fetch_and_independent_event_proof",
            "approved": False,
        })
        if len(proposals) > MAX_PROPOSALS:
            return _blank("too_many_index_candidates")
    counts["same_host_child_pages"] = len(proposals)
    return dict(base, stage="routing_suggestions_only",
                private_routing_proposals=proposals, counts=counts)


def discover_live_html_event_pages(reviewed_index, opener=None):
    """Use existing bounded no-redirect HTTPS fetch for an approved index."""
    if not isinstance(reviewed_index, dict):
        return _blank()
    try:
        page = fetch_official_page({
            "approved_host": reviewed_index["approved_host"],
            "exact_url": reviewed_index["exact_index_url"],
        }, opener=opener)
    except (ValueError, TypeError, OSError, KeyError):
        return _blank("index_html_unavailable")
    return discover_html_event_pages(reviewed_index, page)


def redacted_html_index_counts(report):
    """Only fixed nonnegative bounded aggregate counts may leave private review."""
    template = _blank()["counts"]
    supplied = report.get("counts") if isinstance(report, dict) and report.get("schema") == SCHEMA else {}
    safe = {}
    for key in template:
        value = supplied.get(key) if isinstance(supplied, dict) else None
        safe[key] = value if type(value) is int and 0 <= value <= MAX_LINKS else 0
    return {
        "schema": SCHEMA, "counts": safe,
        "contains_private_identifiers": False,
        "approval_granted": False, "publisher_connected": False,
        "public_writes": 0,
    }
