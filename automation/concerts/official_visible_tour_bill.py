"""Generic visible tour bill proof, after independent official origin binding.

A tour heading is NOT an artist. Only an explicitly introduced bill plus
a matching, complete named artist list may supplement sparse structured
event data. No domain-specific selectors or named artist whitelist.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from automation.concerts import official_html_evidence as visible
from automation.concerts.triage import words

TOUR = re.compile(r"\b(?:tour|tournee)\b")
INTRO = re.compile(r"^\s*(?:avec|featuring|line[- ]?up|programmation)\s*(?::|\u241e|\s)\s*(.*)$", re.I)
SUPPORTS = re.compile(r"^(\d+)\s+(?:supports?|premieres? parties?)(?:\s+dans le cadre de la tournee)?$")
LINKED_NAME = re.compile(r"^\s*(.+?)\s+[-–—]\s+(https://[^\s]+)\s*$")
END = visible.END_SECTION | {"vous devriez aimer", "recommandations", "related concerts"}


class TourBlocks(visible.VisibleBlocks):
    """Preserve explicit line breaks and linked artist names in visible blocks."""
    def handle_starttag(self, tag, attrs):
        if tag == "br" and not self.ignored:
            self.handle_data(" \u241e ")
        super().handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        # The base parser truncates long paragraphs for diagnostics; do not
        # silently truncate a named roster. Input bytes are bounded instead.
        if not self.ignored and tag == "p":
            for i in range(len(self.frames) - 1, -1, -1):
                if self.frames[i][0] == tag:
                    frame = self.frames.pop(i)
                    value = " ".join(" ".join(frame[1]).split())
                    if value:
                        self.blocks.append((tag, value))
                    return
        super().handle_endtag(tag)


def _name(value):
    value = " ".join(value.split())
    if not 2 <= len(value) <= 120 or not words(value):
        return None
    if (re.search(r"\b(?:supports?|tba|billetterie|tickets?|concert|tournee|tour|guest|portes)\b",
                  words(value)) or re.search(r"https?://", value, re.I)):
        return None
    return value


def verified_tour(html, title, room, city, day):
    """Return (names, event genre) from one explicitly labelled visible bill.

    Require a unique H1 bound to the structured tour title, an exact full
    date associated with the named room and city, a compact event genre
    near the heading, and an introduction naming artists. If the intro
    specifies unnamed supports, only a separate ordered artist+URL list
    can resolve them, and its count must agree.
    """
    if (not isinstance(html, str) or not 100 <= len(html) <= 400_000
            or not all(isinstance(x, str) and words(x) for x in (title, room, city, day))
            or not TOUR.search(words(title))
            or re.search(r"\b(?:festival|fest)\b", words(title))):
        return None
    parser = TourBlocks()
    try:
        parser.feed(html)
        parser.close()
    except (ValueError, TypeError, RecursionError):
        return None
    headings = [(i, text) for i, (tag, text) in enumerate(parser.blocks) if tag == "h1"]
    if len(headings) != 1:
        return None
    start, headline = headings[0]
    if words(headline) not in {words(title), words(title) + " par", words(title) + " by"}:
        return None
    section = parser.blocks[start + 1:]
    cutoff = next((i for i, (_, t) in enumerate(section) if words(t) in END), len(section))
    section = section[:cutoff]
    if re.search(r"\b(?:annule|annulee|reporte|reportee|cancelled|canceled|postponed|rescheduled)\b",
                 words(" ".join(t for _, t in section))):
        return None
    dates = [(i, t, visible._date_in(t)) for i, (_, t) in enumerate(section)
             if visible._date_in(t)]
    if not dates or {d for _, _, d in dates} != {day}:
        return None
    # Venue and city must be on the very same full-date announcement.
    if not any(visible._contains(t, room) and visible._contains(t, city)
               for _, t, _ in dates):
        return None
    first_date = dates[0][0]
    genres = list(dict.fromkeys(g for tag, t in section[:min(first_date, 16)]
                               if tag in {"p", "span", "strong", "li"}
                               for g in [visible._explicit_label(t)] if g))
    if len(genres) != 1:
        return None
    introductions = [(i, m.group(1)) for i, (tag, t) in enumerate(section)
                     if i > first_date and tag in {"p", "li", "text"}
                     for m in [INTRO.fullmatch(t)] if m]
    if len(introductions) != 1:
        return None
    index, intro = introductions[0]
    parts = [x.strip(" \u241e") for x in re.split(r"\s+\+\s+", intro)]
    count = 0
    suffix = SUPPORTS.fullmatch(words(parts[-1])) if parts else None
    if suffix:
        count = int(suffix.group(1))
        if count < 1:
            return None
        parts.pop()
    names = [_name(part) for part in parts]
    if not names or any(name is None for name in names):
        return None
    if count:
        # Adjacent explicitly named artist profile list, not recommendations
        # or unrelated artists elsewhere on the page. Link content is NOT
        # fetched and does not grant source authority.
        if index + 1 >= len(section) or section[index + 1][0] != "p":
            return None
        roster = []
        for line in section[index + 1][1].split("\u241e"):
            match = LINKED_NAME.fullmatch(line)
            if not match:
                return None
            name = _name(match.group(1))
            try:
                url = urlsplit(match.group(2))
                safe = url.scheme == "https" and url.hostname and not url.username and not url.password
            except ValueError:
                return None
            if not name or not safe:
                return None
            roster.append(name)
        if (len(roster) != len(names) + count
                or [words(x) for x in roster[:len(names)]] != [words(x) for x in names]):
            return None
        names = roster
    if len({words(n) for n in names}) != len(names):
        return None
    return names, genres
