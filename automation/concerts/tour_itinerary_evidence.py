"""Visible, first-party touring itineraries as PRIVATE source evidence only.

Unknown music-tour domains often publish one page with several cities, dates
and venues rather than MusicEvent JSON-LD on one URL per concert. These
research hints NEVER grant source authority, place approval, genre proof or
permission to publish. Caller must fetch with pinned DNS, TLS and robots.
No venue, artist, city, date or host allowlist.
"""
from __future__ import annotations

from datetime import date
from html.parser import HTMLParser
import re
import unicodedata

MAX_HTML_BYTES = 400_000
MAX_ENTRIES = 300
REGIONAL_FLAG = re.compile(r"^[\U0001f1e6-\U0001f1ff]{2}$")
SHOW_LINE = re.compile(
    r"^\s*(?P<first>\d{1,2})/(?P<second>\d{1,2})\s+"
    r"(?P<country>[\U0001f1e6-\U0001f1ff]{2}|FR|France)\s+"
    r"(?P<city>.+?)\s+[–—-]\s+(?P<venue>.+?)\s*$",
    re.I,
)
TOUR_WORD = re.compile(r"\b(?:tour|touring|tournee|itinerant)\b")
SHOW_WORD = re.compile(r"\b(?:concerts?|shows?|dates?)\b")
VENUE_STOPWORDS = frozenset({
    "le", "la", "les", "l", "de", "du", "des", "d", "the", "and", "et",
    "centre", "culturel", "municipal", "salle", "rue", "avenue", "boulevard",
    "place", "port", "ter",
})


def norm(value):
    raw = unicodedata.normalize("NFKD", str(value).casefold())
    return " ".join(re.findall(
        r"[a-z0-9]+", "".join(c for c in raw if not unicodedata.combining(c))
    ))


class VisibleLines(HTMLParser):
    """Text divided by actual visible semantic line boundaries, never JS."""

    VOID = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"})
    BREAKS = frozenset({"br", "p", "li", "tr", "article", "div", "section"})
    HIDDEN_TAGS = frozenset({"script", "style", "noscript", "svg", "template"})

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.hidden = 0
        self.parts = []
        self.bad_nesting = False

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        props = dict(attrs)
        class_names = set((props.get("class") or "").lower().split())
        blocked = (tag in self.HIDDEN_TAGS
                   or "hidden" in props or props.get("aria-hidden") == "true"
                   or bool(class_names.intersection({
                       "hidden", "d-none", "sr-only", "visually-hidden",
                       "screen-reader-text", "u-hidden"}))
                   or "display:none" in (props.get("style") or "").replace(
                       " ", "").lower())
        if tag in self.BREAKS and self.hidden == 0 and not blocked:
            self.parts.append("\n")
        if tag not in self.VOID:
            self.stack.append((tag, blocked))
            self.hidden += blocked

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in self.BREAKS and self.hidden == 0:
            self.parts.append("\n")
        if not self.stack or self.stack[-1][0] != tag:
            self.bad_nesting = True
            return
        _, blocked = self.stack.pop()
        self.hidden -= blocked

    def handle_data(self, data):
        if not self.hidden and len(self.parts) < 30000:
            self.parts.append(data)


def _same_phrase(haystack, needle):
    needle = norm(needle)
    if len(needle) < 4:
        return False
    return re.search(r"(?<![a-z0-9])" + re.escape(needle) + r"(?![a-z0-9])",
                     norm(haystack)) is not None


def _same_venue(official, recorded):
    original = norm(official)
    candidate = norm(recorded)
    if len(original) < 5 or len(candidate) < 5:
        return False
    if _same_phrase(candidate, original):
        return True
    # A promoter may print "CCO John Lennon" while a venue catalogue writes
    # "Centre culturel municipal John-Lennon, 41 ter rue de Feytiat".
    # Require two DISTINCT specific words; one common word isn't evidence.
    informative = {
        word for word in original.split()
        if len(word) >= 4 and word not in VENUE_STOPWORDS
    }
    return len(informative.intersection(candidate.split())) >= 2


def matching_tour_stop(html, expected_day, candidate_city, candidate_venue):
    """Return only a research flag for an exact dated French tour stop.

    Numeric 2/4 is AMBIGUOUS until a DIFFERENT itinerary row proves whether
    this site writes month/day (e.g. 1/20) or day/month (e.g. 20/1).
    The reference YEAR must appear explicitly in visible context preceding
    the itinerary. One dated city+venue pair must be unique.
    """
    if (not isinstance(html, str) or not 0 < len(html) <= MAX_HTML_BYTES
            or not isinstance(candidate_city, str)
            or not isinstance(candidate_venue, str)
            or not 4 <= len(candidate_city) <= 160
            or not 5 <= len(candidate_venue) <= 300):
        return False
    try:
        target = date.fromisoformat(expected_day)
        page = VisibleLines()
        page.feed(html)
        page.close()
        if page.bad_nesting or page.hidden:
            return False
        raw = "".join(page.parts)
        if len(raw) < 100:
            return False
        matched = []
        itinerary_start = None
        offset = 0
        for raw_line in raw.splitlines(keepends=True):
            line = " ".join(raw_line.split())
            result = SHOW_LINE.fullmatch(line) if len(line) <= 400 else None
            if result is not None:
                if itinerary_start is None:
                    itinerary_start = offset
                m, d = int(result["first"]), int(result["second"])
                if not 1 <= m <= 31 or not 1 <= d <= 31:
                    return False
                matched.append((m, d, result["country"],
                                result["city"], result["venue"]))
            offset += len(raw_line)
        if not 2 <= len(matched) <= MAX_ENTRIES:
            return False
        # Ignore ambiguous 2/4 unless a different stop makes the order
        # indisputable; reject a site mixing day/month and month/day.
        month_first = any(d > 12 for m, d, _, _, _ in matched)
        day_first = any(m > 12 for m, d, _, _, _ in matched)
        if month_first == day_first:
            return False
        if itinerary_start is None:
            return False
        before = norm(raw[:itinerary_start][-3000:])
        # The year must be carried by the tour itself, not by a page footer.
        # The last explicit calendar year BEFORE the listing must match,
        # even if an earlier page heading mentions a future tour.
        years = re.findall(r"(?<![0-9])20[2-4][0-9](?![0-9])", before)
        if not years or years[-1] != str(target.year):
            return False
        if not TOUR_WORD.search(before) or not SHOW_WORD.search(before):
            return False
        possible_venues = []
        for first, second, country, city, venue in matched:
            if country.lower() not in ("fr", "france", "🇫🇷"):
                continue
            month, day = (first, second) if month_first else (second, first)
            try:
                official_day = date(target.year, month, day)
            except ValueError:
                return False
            if official_day != target or not _same_phrase(candidate_city, city):
                continue
            possible_venues.append(venue)
        return (len(possible_venues) == 1
                and _same_venue(possible_venues[0], candidate_venue))
    except (ValueError, TypeError, OverflowError, UnicodeError):
        return False
