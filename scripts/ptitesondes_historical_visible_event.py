"""Exact same-site visible event corroboration for historical GPS rehearsal.

Only a single event article with one exact title, exact place/city, and exact
date/start in the same visible block may corroborate an existing event.
No fuzzy matching, inferred date, aggregate programme, or cancellation bypass.
This does not approve a venue, a new event or a public correction.
"""
from datetime import date
import json
import re
from urllib.parse import urlsplit

from proof import LD, walk
from ptitesondes_family_national_source_preflight import _Visibility, norm_text, BAD_STATUS
from ptitesondes_dynamic_municipal_source_links import _safe_url
from ptitesondes_independent_venue_site_proof import _osm_website_host
from ptitesondes_delegated_source_authority import _same_host

CLOCK = r"(?:[01]?\d|2[0-3])[:h][0-5]\d"
SINGLE = re.compile(rf"\s*({CLOCK})(?:\s*[-–—]\s*({CLOCK}))?\s*", re.I)
MONTHS = ("janvier", "fevrier", "mars", "avril", "mai", "juin", "juillet",
          "aout", "septembre", "octobre", "novembre", "decembre")
MAX_HTML = 350000


def _contains(text, phrase):
    return bool(phrase and re.search(r"(?<![a-z0-9])" + re.escape(phrase)
                                     + r"(?![a-z0-9])", text))


class Article(_Visibility):
    """Collect only article-scoped visible headings, text and leaf blocks."""
    def __init__(self):
        super().__init__()
        self.articles = []
        self.current = None
        self.heading = None
        self.blocks = []
        self.place = None
        self.place_depth = 0
        self.place_heading = None

    def handle_starttag(self, tag, attrs):
        hidden = super().handle_starttag(tag, attrs)
        if hidden:
            return
        if self.place is not None:
            if tag == "article":
                self.place_depth += 1
                self.current["ambiguous"] = True
            if tag in ("h1", "time"):
                self.current["ambiguous"] = True
            if tag in ("h2", "h3") and self.place_heading is None:
                self.place_heading = (tag, [])
            return
        if tag == "article":
            if self.current is not None:
                if self.current["places"] or self.blocks:
                    self.current["ambiguous"] = True
                self.place = dict(headings=[], text=[])
                self.place_depth = 1
            else:
                self.current = dict(headings=[], text=[], blocks=[], leaf_blocks=[],
                                    places=[], ambiguous=False)
        elif self.current is not None:
            if tag == "h1":
                self.heading = []
            if tag in ("p", "li", "time"):
                self.blocks.append((tag, []))

    def handle_data(self, text):
        if self.current is None or self._hidden():
            return
        if self.place is not None:
            self.place["text"].append(text)
            if self.place_heading is not None:
                self.place_heading[1].append(text)
            return
        self.current["text"].append(text)
        if self.heading is not None:
            self.heading.append(text)
        for _, words in self.blocks:
            words.append(text)

    def handle_endtag(self, tag):
        if self.place is not None and not self._hidden():
            if self.place_heading is not None and tag == self.place_heading[0]:
                self.place["headings"].append(norm_text(" ".join(self.place_heading[1])))
                self.place_heading = None
            if tag == "article":
                self.place_depth -= 1
                if self.place_depth == 0:
                    self.current["places"].append(self.place)
                    self.place = None
                    self.place_heading = None
            super().handle_endtag(tag)
            return
        if self.current is not None and not self._hidden():
            if tag == "h1" and self.heading is not None:
                self.current["headings"].append(norm_text(" ".join(self.heading)))
                self.heading = None
            elif self.blocks and tag == self.blocks[-1][0]:
                _, words = self.blocks.pop()
                block = norm_text(" ".join(words))
                self.current["blocks"].append(block)
                if tag in ("p", "time"):
                    self.current["leaf_blocks"].append(block)
            elif tag == "article":
                self.articles.append(self.current)
                self.current = None
                self.heading = None
                self.blocks = []
        super().handle_endtag(tag)


def _has_structured_event_or_unreadable(html):
    """An existing Event declaration, even contradictory, cannot be bypassed."""
    parser = LD()
    parser.feed(html)
    parser.close()
    if len(parser.blocks) > 20:
        return True
    for block in parser.blocks:
        for node in walk(json.loads(block)):
            types = node.get("@type", [])
            types = [types] if isinstance(types, str) else types
            if isinstance(types, list) and any(isinstance(t, str) and
                    t.casefold().endswith("event") for t in types):
                return True
    return False


def visible_historical_identity(event, html, venue_official):
    if not isinstance(html, str) or not 50 <= len(html) <= MAX_HTML:
        return False
    try:
        source = event.get("source_url")
        if not _safe_url(source) or not _safe_url(venue_official):
            return False
        a, b = _osm_website_host(source), _osm_website_host(venue_official)
        if not a or not b or not _same_host(a, b):
            return False
        if urlsplit(source).path in ("", "/"):
            return False
        day = date.fromisoformat(event["date_start"])
        if event.get("date_end") != day.isoformat():
            return False
        clock = SINGLE.fullmatch(event.get("time") or "")
        if clock is None or _has_structured_event_or_unreadable(html):
            return False
        h, m = re.split("[:h]", clock.group(1).lower())
        dates = tuple(norm_text(x) for x in (
            day.isoformat(), f"{day.day:02d}/{day.month:02d}/{day.year}",
            f"{day.day} {MONTHS[day.month-1]} {day.year}"))
        times = tuple(norm_text(x) for x in (
            f"{int(h):02d}:{m}", f"{int(h)}:{m}", f"{int(h)}h{m}"))
        parser = Article()
        parser.feed(html)
        parser.close()
        if len(parser.articles) != 1 or parser.current is not None:
            return False
        article = parser.articles[0]
        title, venue, city = (norm_text(event.get(k)) for k in ("title", "venue", "city"))
        body = norm_text(" ".join(article["text"]))
        if (article["ambiguous"] or not all((title, venue, city))
                or article["headings"] != [title]
                or not _contains(body, venue)
                or BAD_STATUS.search(body)):
            return False
        blocks = article["blocks"]
        if article["places"]:
            # An embedded address card is not a second event article.
            # Require one exact named place, postal city and no event date or
            # cancellation in that card. Never use its text for session proof.
            if len(article["places"]) != 1:
                return False
            place = article["places"][0]
            place_body = norm_text(" ".join(place["text"]))
            if (place["headings"] != [venue]
                    or not re.search(r"\b\d{5} " + re.escape(city) + r"\b", place_body)
                    or BAD_STATUS.search(place_body)
                    or re.search(r"\b(?:[0-3]?\d) (?:" + "|".join(MONTHS)
                                 + r") \d{4}\b", place_body)):
                return False
            blocks = article["leaf_blocks"]
            if clock.group(2):
                eh, em = re.split("[:h]", clock.group(2).lower())
                end_times = tuple(norm_text(x) for x in (
                    f"{int(eh):02d}:{em}", f"{int(eh)}:{em}", f"{int(eh)}h{em}"))
                blocks = [block for block in blocks
                          if any(_contains(block, f"{start} {joiner}{end}")
                                 for start in times for end in end_times
                                 for joiner in ("a ", "au ", ""))]
        elif not _contains(body, city):
            return False
        return any(any(_contains(block, d) for d in dates)
                   and any(_contains(block, t) for t in times)
                   for block in blocks)
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError, OverflowError):
        return False
