#!/usr/bin/env python3
"""Private one-hop discovery of a named venue page on a DILA-confirmed site.

Strictly no free crawling or publication. An exact visible link can suggest
ONE page to check; the page itself must still independently prove the
venue name and full address before any positive geography diagnostic.
"""
from html.parser import HTMLParser
import re
from urllib.parse import urljoin, urlsplit

from proof import norm
from ptitesondes_dila_municipal_domains import approved_municipal_page_host

MAX_HTML = 350_000
MAX_ANCHORS = 700
BAD_TAGS = frozenset(("script", "style", "noscript", "template", "svg", "iframe"))
VOID_TAGS = frozenset(("area", "base", "br", "col", "embed", "hr",
                       "img", "input", "link", "meta", "param",
                       "source", "track", "wbr"))


class VisibleLinks(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.current = None
        self.links = []

    def _hidden(self):
        return bool(self.stack and self.stack[-1][1])

    def handle_starttag(self, tag, attrs):
        attr = dict(attrs)
        style = str(attr.get("style") or "").lower()
        hidden = (
            self._hidden() or tag in BAD_TAGS or "hidden" in attr
            or str(attr.get("aria-hidden") or "").lower() == "true"
            or re.search(r"display\s*:\s*none|visibility\s*:\s*hidden",
                         style) is not None
        )
        if tag == "a" and not hidden and self.current is None:
            href = attr.get("href")
            if isinstance(href, str) and 1 <= len(href) <= 600:
                self.current = {"href": href, "text": [], "depth": len(self.stack)}
        if tag not in VOID_TAGS:
            self.stack.append((tag, hidden))

    def handle_data(self, data):
        if self.current is not None and not self._hidden():
            self.current["text"].append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.current is not None:
            if len(self.links) < MAX_ANCHORS:
                self.links.append((
                    self.current["href"], " ".join(self.current["text"])))
            self.current = None
        for i in range(len(self.stack)-1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                return


def exact_named_venue_page(venue, current_url, html, city, dila_response):
    """Find ONE approved same-site link whose visible text is the venue name.

    The site-scope policy relies exclusively on DILA, not OSM/OA claims.
    No site search, external redirects, or automatic verification.
    """
    if (not isinstance(venue, str) or not 1 <= len(venue) <= 180
            or not norm(venue) or not isinstance(html, str)
            or not 30 <= len(html) <= MAX_HTML
            or approved_municipal_page_host(
                current_url, city, dila_response) is None):
        return None
    page = urlsplit(current_url)
    parser = VisibleLinks()
    try:
        parser.feed(html)
        parser.close()
    except (ValueError, TypeError, OverflowError):
        return None
    if len(parser.links) >= MAX_ANCHORS:
        return None
    matches = set()
    for href, label in parser.links:
        if norm(label) != norm(venue):
            continue
        candidate = urljoin(current_url, href)
        try:
            u = urlsplit(candidate)
        except ValueError:
            continue
        if (u.scheme != "https" or u.username or u.password
                or u.query or u.fragment or u.path in ("", "/")
                or len(candidate) > 600 or candidate == current_url
                or approved_municipal_page_host(
                    candidate, city, dila_response) is None):
            continue
        # A one-hop path to a same-site page is a hint, not venue proof.
        matches.add(candidate)
        if len(matches) > 1:
            return None
    return next(iter(matches)) if len(matches) == 1 else None
