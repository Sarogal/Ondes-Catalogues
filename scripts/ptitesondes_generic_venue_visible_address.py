#!/usr/bin/env python3
"""Read one exact venue heading and postal address from municipal HTML.

Use ONLY after independent DILA host approval and OSM+BANO coordinates.
This is a conservative alternative for authentic institutional pages that
do not publish schema.org Place data. It never certifies a session, venue
registry record or publication.
"""
from html.parser import HTMLParser
import re

from proof import norm

MAX_HTML = 350_000
MAX_NODES = 3500
MAX_TEXT = 350
BAD = frozenset(("script", "style", "template", "noscript", "svg",
                 "iframe", "nav", "footer"))
VOID = frozenset(("area", "base", "br", "col", "embed", "hr",
                  "img", "input", "link", "meta", "param",
                  "source", "track", "wbr"))


class VisiblePostal(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.active = []
        self.headings = []
        self.addresses = []
        self.count = 0

    def _hidden(self):
        return bool(self.stack and self.stack[-1][1])

    def handle_starttag(self, tag, attrs):
        self.count += 1
        if self.count > MAX_NODES:
            raise ValueError("too_many_html_nodes")
        attr = dict(attrs)
        style = str(attr.get("style") or "").lower()
        hidden = (self._hidden() or tag in BAD or
                  "hidden" in attr or
                  str(attr.get("aria-hidden") or "").lower() == "true" or
                  re.search(r"display\s*:\s*none|visibility\s*:\s*hidden",
                            style) is not None)
        if not hidden and tag in ("h1", "address"):
            self.active.append({"tag": tag, "depth": len(self.stack),
                                "text": []})
        if tag not in VOID:
            self.stack.append((tag, hidden))

    def handle_data(self, value):
        if not self._hidden():
            for rec in self.active:
                if sum(map(len, rec["text"])) <= MAX_TEXT:
                    rec["text"].append(value)

    def handle_endtag(self, tag):
        for rec in list(self.active):
            if rec["tag"] == tag:
                word = " ".join(rec["text"]).strip()
                if len(word) <= MAX_TEXT:
                    target = (self.headings if tag == "h1"
                              else self.addresses)
                    target.append(word)
                self.active.remove(rec)
        for i in range(len(self.stack)-1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                return


def visible_venue_identity_matches(group, candidate, html):
    """Exactly one visible H1 and one <address>, equal to OSM/BAN address.

    No keyword search, inference, title snippets or hidden elements.
    Multiple venue headings / address blocks fail closed.
    """
    if (not isinstance(group, dict) or not isinstance(candidate, dict)
            or not isinstance(html, str) or not 30 <= len(html) <= MAX_HTML):
        return False
    try:
        expected = " ".join([
            candidate["housenumber"], candidate["street"],
            candidate["postcode"], candidate["city"],
        ])
        if (norm(group["city"]) != norm(candidate["city"])
                or norm(group["venue"]) != norm(candidate["venue"])
                or not norm(expected) or not norm(group["venue"])):
            return False
    except (ValueError, TypeError, KeyError):
        return False
    parser = VisiblePostal()
    try:
        parser.feed(html)
        parser.close()
    except (TypeError, ValueError, RecursionError, OverflowError):
        return False
    return (len(parser.headings) == 1
            and norm(parser.headings[0]) == norm(group["venue"])
            and len(parser.addresses) == 1
            and norm(parser.addresses[0]) == norm(expected))
