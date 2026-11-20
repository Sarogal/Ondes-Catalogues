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
    r"(?<!\d)([0-3]?\d)\s+("
    + "|".join(MONTHS)
    + r")\s+(20\d{2})(?!\d)"
)
# Explicit full dates also appear as HTML <time datetime>, ISO or dd/mm/yyyy.
# All forms require a year; day/month-only and ticket-sale dates do not qualify.
ISO_DATE_RE = re.compile(r"(?<![0-9])(20[0-9]{2})-([01][0-9])-([0-3][0-9])(?![0-9])")
NUMERIC_DATE_RE = re.compile(r"(?<![0-9])([0-3]?[0-9])/([01]?[0-9])/(20[0-9]{2})(?![0-9])")
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
            # A machine-readable *event* date can be explicit even when the
            # visible <time> text is a weekday or a short local date. Keep
            # it bound to the same element, not a page-wide JSON-LD hint.
            content = []
            if tag == "time":
                attr = dict(attrs).get("datetime") or ""
                if isinstance(attr, str) and re.fullmatch(
                        r"20[0-9]{2}-[01][0-9]-[0-3][0-9](?:T[0-9:.,+Z-]+)?",
                        attr):
                    content.append(attr)
            self.frames.append([tag, content])

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
    """One complete date per event block; disagreement fails closed.

    A date from <time datetime> is treated as local calendar day, never as
    a concert start hour. Multiple different dates in the same block could
    denote an on-sale day versus the show: they are not interchangeable.
    """
    dates = []
    for found in DATE_RE.finditer(words(text)):
        try:
            dates.append(dt.date(int(found[3]), MONTHS[found[2]],
                                 int(found[1])).isoformat())
        except ValueError:
            return "_invalid_date"
    for found in ISO_DATE_RE.finditer(text):
        try:
            dates.append(dt.date(int(found[1]), int(found[2]),
                                 int(found[3])).isoformat())
        except ValueError:
            return "_invalid_date"
    for found in NUMERIC_DATE_RE.finditer(text):
        try:
            dates.append(dt.date(int(found[3]), int(found[2]),
                                 int(found[1])).isoformat())
        except ValueError:
            return "_invalid_date"
    if len(set(dates)) > 1:
        return "_conflicting_dates"
    return dates[0] if dates else None


def _contains(text, needle):
    needle = words(needle)
    return bool(needle and re.search(
        r"(?<!\w)" + re.escape(needle) + r"(?!\w)", words(text)))


def _explicit_label(value):
    """Only a compact single genre label, never natural-language biographies."""
    label = " ".join(value.strip(" \t\r\n–—-:•").split())
    w = words(label)
    if not (2 <= len(w) <= 48 and len(w.split()) <= 4):
        return None
    if w in ("rock", "musique", "concert", "live"):
        return None
    if not any(re.search(
            r"(?<!\w)" + re.escape(genre) + r"(?!\w)", w)
            for genre in KNOWN_GENRES):
        return None
    return label[:80]


def _heading_genre(text, artists):
    """E.g. '► EISBRECHER – Metal Indus –' or '► BAND – Deathcore'."""
    parts = re.split(r"\s+[–—]\s+|\s+-\s+", text, maxsplit=2)
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
    named_genre_headings = set()
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
            if g:
                # An explicit artist-genre heading is stronger than an
                # event title alone. Capture every artist, even when
                # several headings share a single genre label.
                heading_name = re.split(
                    r"\s+[–—]\s+|\s+-\s+", text, maxsplit=1)[0]
                named_genre_headings.add(words(heading_name))
                if g not in genres:
                    genres.append(g)
    if not genres:
        return outcome("html_event_genre_unconfirmed")
    # A source's JSON-LD may contain the generic Organization placeholder
    # instead of real named MusicGroup/Person performers. A matching event
    # headline is not independent line-up proof: keep this signal separate.
    if candidate.get("structuredPerformerProof") == "missing_review_only":
        # The structured performer was missing/Organization. Full-band
        # headings are useful PRIVATE evidence, but never a publisher
        # signature or a source trust grant.
        if named_genre_headings == set(artists) and len(set(artists)) == len(artists):
            return outcome("html_explicit_named_artist_headings_review_only",
                           genres[:20])
        return outcome("html_event_genre_visible_lineup_unverified", genres[:20])
    return outcome("html_explicit_event_genre_correlated", genres[:20])
