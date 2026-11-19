"""Generic, read-only first-party HTML evidence for the *current event*.

Official HTML may contain genre badges/artist genre headings even when JSON-LD
has no usable Event.genre. This module NEVER approves, reclassifies, or publishes
a concert. It requires one exact event heading, first-party HTTPS identity,
the visible event date, and the visible venue/city. Biographies, menus,
recommended concerts and free-form descriptions are NOT genre evidence.
"""
from __future__ import annotations

import datetime as dt
from html.parser import HTMLParser
import re

import official_rss_jsonld_bridge as bridge
from triage import POSITIVE_GENRES, words

BLOCKS = frozenset({"h1", "h2", "h3", "h4", "h5", "p", "span",
                    "strong", "time", "li"})
IGNORE = frozenset({"nav", "footer", "aside", "script", "style",
                    "noscript", "svg", "form"})
VOID = frozenset({"area", "base", "br", "col", "embed", "hr", "img",
                  "input", "link", "meta", "param", "source", "track", "wbr"})
MONTHS = dict(zip(
    ("janvier", "fevrier", "mars", "avril", "mai", "juin", "juillet",
     "aout", "septembre", "octobre", "novembre", "decembre"),
    range(1, 13)))
DATE_RE = re.compile(
    r"(?<!\\d)([0-3]?\\d)\\s+("
    + "|".join(MONTHS)
    + r")\\s+(20\\d{2})(?!\\d)"
)
END_SECTION = frozenset({
    "vous aimerez aussi", "evenements similaires", "autres concerts",
    "concerts similaires", "related events", "you may also like",
    "decouvrez aussi", "a decouvrir",
})
KNOWN_GENRES = tuple(words(tag) for tag in POSITIVE_GENRES)


class VisibleBlocks(HTMLParser):
    """Minimal text structure, ignoring navigation/marketing/script content."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks = []
        self.frames = []
        self.ignored = 0

    def handle_starttag(self, tag, attrs):
        if self.ignored:
            if tag not in VOID:
                self.ignored += 1
            return
        if tag in IGNORE:
            self.ignored = 1
            return
        if tag in BLOCKS:
            self.frames.append([tag, []])

    def handle_data(self, data):
        if self.ignored:
            return
        for frame in self.frames:
            frame[1].append(data)
        if not self.frames and data.strip():
            self.blocks.append(("text", " ".join(data.split())))

    def handle_endtag(self, tag):
        if self.ignored:
            if tag not in VOID:
                self.ignored -= 1
            return
        if tag not in BLOCKS:
            return
        for i in range(len(self.frames) - 1, -1, -1):
            if self.frames[i][0] == tag:
                frame = self.frames.pop(i)
                value = " ".join(" ".join(frame[1]).split())
                if value:
                    self.blocks.append((tag, value[:1000]))
                return


def _date_in(text):
    found = DATE_RE.search(words(text))
    if not found:
        return None
    try:
        return dt.date(int(found[3]), MONTHS[found[2]], int(found[1])).isoformat()
    except ValueError:
        return None


def _contains(text, needle):
    needle = words(needle)
    return bool(needle and re.search(
        r"(?<!\\w)" + re.escape(needle) + r"(?!\\w)", words(text)))


def _explicit_label(value):
    """Only a compact single genre label, never natural-language biographies."""
    w = words(value)
    if not (2 <= len(w) <= 48 and len(w.split()) <= 4):
        return None
    if w in ("rock", "musique", "concert", "live"):
        return None
    if not any(re.search(
            r"(?<!\\w)" + re.escape(genre) + r"(?!\\w)", w)
            for genre in KNOWN_GENRES):
        return None
    return " ".join(value.split())[:80]


def _heading_genre(text, artists):
    """E.g. '► EISBRECHER – Metal Indus –' or '► BAND – Deathcore'."""
    parts = re.split(r"\\s+[–—]\\s+|\\s+-\\s+", text, maxsplit=2)
    if len(parts) < 2 or words(parts[0]) not in artists:
        return None
    return _explicit_label(parts[1])


def inspect(candidate, html, actual_url, source):
    """A fixed diagnostic code; no discovery/review/publisher trust mutation."""
    def outcome(code, genres=()):
        return {"status": code, "genres": list(genres),
                "publicationAllowed": False, "approvalsProposed": 0}

    if (not isinstance(candidate, dict) or not isinstance(source, dict)
            or not isinstance(html, str) or len(html) > 1_000_000):
        return outcome("html_evidence_unreadable")
    expected = candidate.get("sourceUrl")
    base = source.get("url")
    if (not bridge.official_event_url(expected, base)
            or not bridge.official_event_url(actual_url, base)
            or expected.rstrip("/") != actual_url.rstrip("/")):
        return outcome("html_official_url_not_correlated")
    if (words(candidate.get("venue")) != words(source.get("name"))
            or words(candidate.get("city")) != words(source.get("city"))
            or str(candidate.get("department")) != str(source.get("department"))):
        return outcome("html_source_venue_not_correlated")
    try:
        expected_day = dt.date.fromisoformat(candidate.get("date")).isoformat()
    except (TypeError, ValueError):
        return outcome("html_event_date_unavailable")
    if (not isinstance(candidate.get("name"), str)
            or not isinstance(candidate.get("leadArtist"), str)):
        return outcome("html_event_bill_unavailable")

    parser = VisibleBlocks()
    try:
        parser.feed(html)
        parser.close()
    except (ValueError, TypeError):
        return outcome("html_evidence_unreadable")
    headings = [(i, t) for i, (tag, t) in enumerate(parser.blocks)
                if tag == "h1"]
    if len(headings) != 1:
        return outcome("html_event_heading_ambiguous")
    start, headline = headings[0]
    if words(headline) != words(candidate["name"]):
        return outcome("html_event_heading_mismatch")

    artists = [words(x) for x in candidate["leadArtist"].split(" + ")]
    headline_parts = {words(x) for x in headline.split(" + ")}
    if (not artists or any(not a or a not in headline_parts for a in artists)):
        return outcome("html_named_bill_not_correlated")

    following = parser.blocks[start + 1:]
    cutoff = next((i for i, (tag, text) in enumerate(following)
                   if tag in {"h2", "h3"} and
                   words(text) in END_SECTION), len(following))
    detail = following[:min(cutoff, 160)]
    # A first date next to the event title must be the event date; sale dates
    # and tour biographies later in the document must never fill it.
    first_date = next((_date_in(t) for tag, t in detail[:16]
                       if tag in {"strong", "time", "p", "text"}
                       and _date_in(t)), None)
    if first_date != expected_day:
        return outcome("html_event_date_not_correlated")
    venue_present = any(_contains(t, source.get("name")) for _, t in detail)
    city_present = any(_contains(t, source.get("city")) for _, t in detail)
    if not venue_present or not city_present:
        return outcome("html_visible_venue_or_city_missing")

    genres = []
    for tag, text in detail[:16]:
        # A standalone event tag near the title, not a genre mentioned in a
        # biography or an unrelated link. 'Rock' alone is too broad.
        if tag in ("p", "span", "li"):
            g = _explicit_label(text)
            if g and g not in genres:
                genres.append(g)
    for tag, text in detail:
        if tag == "h4":
            g = _heading_genre(text, set(artists))
            if g and g not in genres:
                genres.append(g)
    if not genres:
        return outcome("html_event_genre_unconfirmed")
    return outcome("html_explicit_event_genre_correlated", genres[:20])
