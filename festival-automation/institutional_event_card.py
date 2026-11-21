"""Exact date of a named touring concert in an independently checked agenda card.

A government agenda can print "12 Fév 2027" on an event card while its linked
article discusses the tour without repeating the date. This is REVIEW data
only. The card must contain one exact event title, one link to the approved
same-host detail, and one unambiguous date. The Concerts engine will repeat
both institutional requests independently. Never use this as festival proof.
"""
from __future__ import annotations

from datetime import date
from html.parser import HTMLParser
import re
from urllib.parse import urljoin

from grossesondes_official_html_edition import fold
from source_qualification import normalized

MONTH = {
    "jan": 1, "janv": 1, "janvier": 1,
    "fev": 2, "fevr": 2, "fevrier": 2,
    "mar": 3, "mars": 3,
    "avr": 4, "avril": 4,
    "mai": 5, "juin": 6,
    "juil": 7, "juillet": 7,
    "aout": 8, "sep": 9, "sept": 9, "septembre": 9,
    "oct": 10, "octobre": 10,
    "nov": 11, "novembre": 11,
    "dec": 12, "decembre": 12,
}


class Cards(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.card = None
        self.h2 = False
        self.in_time = False
        self.time_raw = None
        self.h2_text = []
        self.time_text = []
        self.cards = []

    def handle_starttag(self, tag, attrs):
        props = dict(attrs)
        if tag == "article":
            if self.depth == 0:
                self.card = {"heading": "", "links": [], "times": []}
            self.depth += 1
        if not self.depth:
            return
        if (props.get("aria-hidden") == "true"
                or "hidden" in props
                or "display:none" in (props.get("style") or "").replace(" ", "").lower()):
            return
        if tag == "h2":
            self.h2, self.h2_text = True, []
        elif tag == "time":
            self.in_time, self.time_raw = True, props.get("datetime")
            self.time_text = []
        elif tag == "a" and isinstance(props.get("href"), str):
            self.card["links"].append(props["href"])

    def handle_data(self, value):
        if self.depth:
            if self.h2:
                self.h2_text.append(value)
            if self.in_time:
                self.time_text.append(value)

    def handle_endtag(self, tag):
        if not self.depth:
            return
        if tag == "h2" and self.h2:
            self.card["heading"] = " ".join(self.h2_text).strip()
            self.h2 = False
        if tag == "time" and self.in_time:
            self.card["times"].append((" ".join(self.time_text), self.time_raw))
            self.in_time = False
        if tag == "article":
            self.depth -= 1
            if self.depth == 0:
                self.cards.append(self.card)
                self.card = None


def parse_exact_time(text, machine=None):
    if isinstance(machine, str) and re.match(
            r"^20[2-4][0-9]-[01][0-9]-[0-3][0-9](?:$|[T ])", machine):
        try:
            return date.fromisoformat(machine[:10])
        except ValueError:
            return None
    if not isinstance(text, str):
        return None
    clean = " ".join(fold(text).replace(".", " ").split())
    match = re.fullmatch(r"([0-3]?\d)\s+([a-z]{2,10})\s+(20[2-4]\d)", clean)
    if not match:
        return None
    month = MONTH.get(match.group(2))
    if month is None:
        return None
    try:
        return date(int(match.group(3)), month, int(match.group(1)))
    except ValueError:
        return None


def exact_event_card_day(html, source):
    if (not isinstance(html, str) or not 0 < len(html) <= 650_000
            or not isinstance(source, dict)
            or not isinstance(source.get("title"), str)
            or not isinstance(source.get("url"), str)
            or not isinstance(source.get("index_page"), str)
            or type(source.get("year")) is not int):
        return None
    parser = Cards()
    parser.feed(html)
    parser.close()
    matches = []
    for card in parser.cards[:150]:
        if normalized(card["heading"]) != normalized(source["title"]):
            continue
        # Indexes containing identical event names but DIFFERENT cards or
        # venues are ambiguous and cannot prove a transferable date.
        targets = []
        for href in card["links"][:30]:
            try:
                targets.append(urljoin(source["index_page"], href))
            except (ValueError, TypeError):
                pass
        # A single card with competing outbound event links is ambiguous.
        # The index authorizes ONLY its one exact named event detail.
        if not targets or set(targets) != {source["url"]}:
            continue
        parsed = [parse_exact_time(text, machine)
                  for text, machine in card["times"]]
        if len(parsed) != 1 or parsed[0] is None:
            continue
        if parsed[0].year != source["year"]:
            continue
        matches.append(parsed[0])
    return matches[0] if len(matches) == 1 else None
