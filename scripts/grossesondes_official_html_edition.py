"""Strict visible-first-party HTML evidence for a future festival edition.

Called only AFTER the publisher independently fetches the immutable registered
officialSite. Never accepts text or URLs carried in the private intake patch.
No inherited artists, venue, geography, tickets or map markers are certified.
"""
from datetime import date
from html.parser import HTMLParser
import re
import unicodedata

MONTHS = {
    "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5,
    "juin": 6, "juillet": 7, "aout": 8, "septembre": 9, "octobre": 10,
    "novembre": 11, "decembre": 12, "january": 1, "february": 2,
    "march": 3, "april": 4, "may": 5, "june": 6, "july": 7,
    "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}
MONTH_WORD = "|".join(sorted(MONTHS, key=len, reverse=True))
DATE_EXPRESSION = re.compile(
    r"(?<![0-9])(?:du\s+|les\s+)?"
    r"(?P<days>[0-3]?\d(?:\s*(?:[.,/|&–—-]|\bet\b|\bau\b|\band\b|\bto\b)\s*[0-3]?\d){0,5})"
    r"\s*(?:[|,–—-]\s*)?(?P<month>" + MONTH_WORD + r")"
    r"\s*(?:[|,–—-]\s*)?(?P<year>20[2-4]\d)(?!\d)",
    re.IGNORECASE,
)
DAY = re.compile(r"\d{1,2}")
CANCEL = re.compile(
    r"\b(?:annul(?:e|ee|ees|es|ation)|cancel(?:led|ed|lation)?|"
    r"reporte|reportee|postponed|rescheduled|date[s]?\s+a\s+confirmer)\b",
    re.IGNORECASE,
)
HIDDEN = {"head", "script", "style", "noscript", "template", "svg", "iframe"}
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr"}
BREAKS = {"div", "section", "article", "header", "footer", "main", "p",
          "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr"}


def fold(value):
    normalized = unicodedata.normalize("NFKD", str(value).casefold())
    return "".join(c for c in normalized if not unicodedata.combining(c))


class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.parts = []

    def hidden(self):
        return bool(self.stack and self.stack[-1][1])

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        style = fold(attributes.get("style") or "")
        invisible = (tag in HIDDEN or "hidden" in attributes
                     or attributes.get("aria-hidden") == "true"
                     or re.search(r"(?:display\s*:\s*none|visibility\s*:\s*hidden)",
                                  style) is not None)
        if tag in BREAKS and not self.hidden() and not invisible:
            self.parts.append(" ")
        if tag not in VOID:
            self.stack.append((tag, invisible or self.hidden()))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag in BREAKS and not self.hidden():
            self.parts.append(" ")
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        if not self.hidden():
            self.parts.append(data)

def explicit_ranges(text, year):
    """Only printed calendar dates with an explicit month and edition year."""
    for match in DATE_EXPRESSION.finditer(text):
        if int(match.group("year")) != year:
            continue
        days = [int(x) for x in DAY.findall(match.group("days"))]
        if not days or any(not 1 <= x <= 31 for x in days):
            continue
        if len(days) > 2 and days != list(range(days[0], days[-1] + 1)):
            continue
        if len(days) == 2 and any(
                separator in match.group("days") for separator in (",", "&", ".")):
            # "25 & 26 juin" is a full two-day range, not merely June 26.
            # "25 & 27", "13, 15" and "13.15" are not continuous proof.
            if days[1] != days[0] + 1:
                continue
        try:
            first = date(year, MONTHS[fold(match.group("month"))], days[0])
            last = date(year, MONTHS[fold(match.group("month"))], days[-1])
        except ValueError:
            continue
        if first <= last and (last - first).days <= 7:
            yield match.start(), match.end(), first, last


def dominant_visible_range(ranges):
    """Keep one complete interval, ignoring only contained SINGLE days.

    A two-day announcement and a separate mention of its Saturday describe
    the same period. Two different multi-day ranges (even if one contains
    the other), disjoint days and partially overlapping claims are conflicts.
    """
    unique = set(ranges)
    enclosing = [candidate for candidate in unique if all(
        (other == candidate or
         (other[0] == other[1] and
          candidate[0] <= other[0] <= candidate[1]))
        for other in unique)]
    return enclosing[0] if len(enclosing) == 1 else None


class VisibleParagraphs(VisibleText):
    """A conservative visible-paragraph view for year-specific identity checks.

    Metadata, scripts, hidden elements and text spread across unrelated
    paragraphs never form a same-paragraph edition announcement.
    """
    PARAGRAPHS = frozenset({"p", "h1", "h2", "h3", "h4", "li"})
    SEP = "\x1f"

    def handle_starttag(self, tag, attrs):
        if tag in self.PARAGRAPHS and not self.hidden():
            self.parts.append(self.SEP)
        super().handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag in self.PARAGRAPHS and not self.hidden():
            self.parts.append(self.SEP)
        super().handle_endtag(tag)


ADMINISTRATIVE_ONSALE = re.compile(
    r"\b(?:ouverture\s+(?:de\s+|des\s+|du\s+|d\s+)?"
    r"(?:la\s+)?(?:billetterie|prevente?s?|reservations?|inscriptions?)"
    r"|(?:la\s+)?billetterie\s+(?:ouvre|ouvrira)"
    r"|mise\s+en\s+vente\s+(?:des\s+)?(?:billets?|places?)"
    r"|prevente?s?\s+(?:ouvrent|ouvre|ouvriront)"
    r"|(?:ticket\s+sales?|presales?)\s+(?:open|opens|start|starts))\b",
    re.IGNORECASE,
)


def administrative_calendar_dates(html, edition_title, year):
    """Identify only clearly NON-event single dates in isolated visible blocks.

    "Ouverture de la billetterie le 26 mars 2027" must not contradict an
    independently explicit festival weekend. A generic date, another festival,
    a mixed paragraph, a cancellation, an embedded script or a multi-day date
    NEVER enters this exclusion list. This is a negative classification, not
    festival proof, a year inference or a newly approved source.
    """
    if (not isinstance(html, str) or not 0 < len(html) <= 1_400_000
            or not isinstance(edition_title, str)
            or type(year) is not int):
        return set()
    words = re.findall(
        r"[a-z0-9]+",
        re.sub(r"\b20[2-4]\d\b", "", fold(edition_title)),
    )
    if not words or len("".join(words)) < 8:
        return set()
    exact_name = re.compile(
        r"(?<![a-z0-9])" + r"[\W_]+".join(map(re.escape, words))
        + r"(?![a-z0-9])"
    )
    parser = VisibleParagraphs()
    try:
        parser.feed(html)
        parser.close()
    except (ValueError, TypeError, UnicodeError):
        return set()
    exclusions = set()
    for block in " ".join(parser.parts).split(VisibleParagraphs.SEP):
        if not 0 < len(block) <= 220:
            continue
        paragraph = " ".join(fold(block).split())
        if (exact_name.search(paragraph) or CANCEL.search(paragraph)
                or re.search(r"\bfest(?:ival)?\b", paragraph)):
            continue
        dates = list(explicit_ranges(paragraph, year))
        if len(dates) != 1:
            continue
        offset, _end, first, last = dates[0]
        if first != last:
            continue
        preceding = paragraph[max(0, offset - 110):offset]
        if ADMINISTRATIVE_ONSALE.search(preceding):
            exclusions.add((first, last))
    return exclusions


def _current_edition_same_paragraph(html, name, start, end):
    """An explicit, noncancelled current-year name/date in ONE visible block."""
    parser = VisibleParagraphs()
    parser.feed(html)
    parser.close()
    year = start.year
    for raw in " ".join(parser.parts).split(VisibleParagraphs.SEP):
        if not 0 < len(raw) <= 1600:
            continue
        paragraph = " ".join(fold(raw).split())
        if not name.search(paragraph) or CANCEL.search(paragraph):
            continue
        years = {int(x) for x in re.findall(
            r"(?<!\d)20[2-4]\d(?!\d)", paragraph)}
        if not years or years != {year}:
            continue
        dates = {(a, b) for _x, _y, a, b in explicit_ranges(paragraph, year)}
        if dominant_visible_range(dates) != (start, end):
            continue
        for mention in name.finditer(paragraph):
            after = re.match(r"\s*(20[2-4]\d)(?!\d)",
                             paragraph[mention.end():mention.end() + 14])
            if after is None or int(after.group(1)) == year:
                return True
    return False


def visible_official_edition(html, edition_title, start, end):
    """Fail closed if the exact edition is not corroborated by visible HTML.

    The event name and explicit dates must be close together in visible text.
    Historical mentions, metadata, JSON-LD, unrelated date blocks, canceled
    announcements and contradictory ranges never certify an edition.
    """
    if (not isinstance(html, str) or not 0 < len(html) <= 1_400_000
            or not isinstance(edition_title, str)
            or not isinstance(start, date) or not isinstance(end, date)
            or start.year != end.year):
        return False
    text_parser = VisibleText()
    try:
        text_parser.feed(html)
        text_parser.close()
    except (ValueError, TypeError):
        return False
    text = " ".join(fold(" ".join(text_parser.parts)).split())
    words = re.findall(r"[a-z0-9]+", re.sub(r"\b20[2-4]\d\b", "", fold(edition_title)))
    if not words or len("".join(words)) < 8:
        return False
    # Word boundaries prevent "Festival 666" from matching "Festival 6666".
    name = re.compile(r"(?<![a-z0-9])" +
                      r"[\W_]+".join(map(re.escape, words)) +
                      r"(?![a-z0-9])")
    mentions = list(name.finditer(text))
    if not mentions:
        return False
    year = start.year
    ignored_administrative_days = administrative_calendar_dates(
        html, edition_title, year)
    matches = set()
    for mention in mentions[:80]:
        left = max(0, mention.start() - 300)
        right = min(len(text), mention.end() + 420)
        excerpt = text[left:right]
        dates = list(explicit_ranges(excerpt, year))
        if not dates:
            continue
        # A historical-year label cannot itself corroborate this edition.
        # It remains a veto UNLESS the current edition has an independent,
        # exact name/year/date statement within the same visible paragraph.
        # This avoids mistaking archived 2026 recaps near a 2027 announcement
        # for a contradiction, without trusting generic adjacent text.
        after_name = re.match(r"\s*(20[2-4]\d)(?!\d)",
                              text[mention.end():mention.end() + 14])
        if after_name and int(after_name.group(1)) != year:
            if not _current_edition_same_paragraph(
                    html, name, start, end):
                return False
            continue
        # A cancellation or unresolved postponement of the same edition
        # anywhere in the relevant announcement blocks forbids admission.
        if CANCEL.search(excerpt):
            return False
        for _begin, _end, actual_start, actual_end in dates:
            if (actual_start, actual_end) not in ignored_administrative_days:
                matches.add((actual_start, actual_end))
    return dominant_visible_range(matches) == (start, end)
