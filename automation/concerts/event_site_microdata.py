"""Strict generic schema.org HTML microdata reader for official concert pages.

This only reads evidence from a freshly fetched first-party page. It does not
grant host, source, venue, musical genre or publication authority. An Event
must still pass the independent event-site verifier and cloud publisher.
"""
from __future__ import annotations

import html.parser
import re

SCHEMA_TYPE = re.compile(r"https?://schema[.]org/([A-Za-z][A-Za-z0-9]*)\Z")
HIDDEN = frozenset({"script", "style", "template", "noscript", "svg"})
VOID = frozenset({"area", "base", "br", "col", "embed", "hr", "img",
                  "input", "link", "meta", "param", "source", "track", "wbr"})
FIELDS = frozenset({
    "name", "url", "startDate", "eventStatus", "performer", "genre",
    "location", "address", "streetAddress", "postalCode", "addressLocality",
    "addressRegion", "addressCountry", "sameAs",
})


class _Node:
    def __init__(self, tag, attrs, visible):
        self.tag = tag
        self.attrs = dict(attrs)
        self.visible = visible
        self.children = []
        self.contents = []


class _Tree(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("_root", [], True)
        self.stack = [self.root]
        self.node_count = 0

    def _start(self, tag, attrs, void):
        self.node_count += 1
        if self.node_count > 12000 or len(self.stack) > 96:
            raise ValueError("HTML microdata document too complex")
        values = dict(attrs)
        style = str(values.get("style") or "")
        visible = (self.stack[-1].visible and tag not in HIDDEN
                   and "hidden" not in values
                   and values.get("aria-hidden") != "true"
                   and not re.search(
                       r"display\s*:\s*none|visibility\s*:\s*hidden",
                       style, re.I))
        node = _Node(tag, attrs, visible)
        self.stack[-1].children.append(node)
        if not void:
            self.stack.append(node)

    def handle_starttag(self, tag, attrs):
        self._start(tag, attrs, tag in VOID)

    def handle_startendtag(self, tag, attrs):
        self._start(tag, attrs, True)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if self.stack[-1].visible:
            self.stack[-1].contents.append(data)


def _visible_text(node):
    if not node.visible:
        return ""
    parts = list(node.contents)
    for child in node.children:
        if child.visible:
            parts.append(_visible_text(child))
    return " ".join(" ".join(parts).split())[:1000]


def _type(node):
    value = node.attrs.get("itemtype")
    if ("itemscope" not in node.attrs
            or not isinstance(value, str) or " " in value):
        return None
    found = SCHEMA_TYPE.fullmatch(value)
    return found[1] if found else None


def _scalar(node):
    attrs = node.attrs
    if node.tag in {"meta", "data"} and attrs.get("content"):
        return attrs["content"]
    if node.tag in {"a", "link"} and attrs.get("href"):
        return attrs["href"]
    if node.tag == "time" and attrs.get("datetime"):
        return attrs["datetime"]
    value = _visible_text(node)
    return value if 0 < len(value) <= 1000 else None


def _properties(root):
    """Only properties belonging to THIS itemscope; no sibling borrowing."""
    values = {}

    def collect(node):
        for child in node.children:
            if not child.visible:
                continue
            prop = child.attrs.get("itemprop")
            typ = _type(child)
            if isinstance(prop, str):
                if prop not in FIELDS:
                    continue
                value = _object(child) if typ else _scalar(child)
                if value is None:
                    continue
                if prop in values:
                    previous = values[prop]
                    values[prop] = (previous if isinstance(previous, list)
                                    else [previous]) + [value]
                else:
                    values[prop] = value
                # NEVER traverse children of an itemprop boundary: this would
                # allow a side panel/related item to donate another field.
                continue
            if typ:
                continue  # Nested item unrelated to the current Event.
            collect(child)
    collect(root)
    return values


def _object(node):
    typ = _type(node)
    if typ is None:
        return None
    return {"@type": typ, **_properties(node)}


def read_microdata_events(page_html):
    """Return isolated Event/MusicEvent objects, or [] for unsafe HTML.

    The event-site rechecker itself makes the final unambiguous selection,
    then checks the entire lineup, precise site and first-party identity.
    """
    if not isinstance(page_html, str) or len(page_html) > 1_000_000:
        return []
    tree = _Tree()
    try:
        tree.feed(page_html)
        tree.close()
    except (ValueError, TypeError, RecursionError):
        return []
    events = []

    def scan(node):
        if not node.visible:
            return
        typ = _type(node)
        if typ in {"Event", "MusicEvent"}:
            event = _object(node)
            if event is not None:
                events.append(event)
            return
        if typ:
            return
        for child in node.children:
            scan(child)

    try:
        scan(tree.root)
    except (ValueError, RecursionError):
        return []
    return events
