"""Le 106 (Rouen): paginated first-party agenda -> review-only rock/metal leads.

The agenda card is the source of the *year and date*. The named individual
event page confirms the headline and room but may OMIT the year in its HTML.
Never fabricate a year from current context or treat 106 advertised door times
as start times. No publication/approval is performed by this adapter.
"""
from __future__ import annotations

import datetime as dt
from html import unescape
from html.parser import HTMLParser
import re
import unicodedata
from urllib.parse import urljoin, urlsplit

AGENDA = "https://le106.com/agenda"
HOST = "le106.com"
EVENT = re.compile(r"/agenda/([a-z0-9][a-z0-9-]{2,120})/?")
ROCK = re.compile(
    r"\b(?:metal|punk|hardcore|stoner|doom|sludge|grind|post[- ]rock|"
    r"garage|psych[eé]d[eé]lique|rock|noise|shoegaze|grunge|indus)\b", re.I)
STOP = re.compile(r"\b(?:annul[eé]|report[eé]|cancelled|postponed|"
                  r"festival|atelier|conf[eé]rence|formation)\b", re.I)
ISO = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})(?:[Tt][\d:]+)?\b")
MONTHS = {
    "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5,
    "juin": 6, "juillet": 7, "aout": 8, "septembre": 9,
    "octobre": 10, "novembre": 11, "decembre": 12,
}
FRENCH = re.compile(
    r"\b(\d{1,2})\s+(janvier|fevrier|mars|avril|mai|juin|juillet|"
    r"aout|septembre|octobre|novembre|decembre)\s+(20\d{2})\b")
DRUPAL = re.compile(
    r"\b(\d{1,2})\.\s*(janvier|fevrier|mars|avril|mai|juin|juillet|"
    r"aout|septembre|octobre|novembre|decembre)\s*(\d{1,2})\.\s*(20\d{2})\b")
SKIP = {"script", "style", "nav", "footer", "noscript", "svg"}
VOID = {"br", "hr", "img", "input", "meta", "link", "source", "area", "wbr"}


def fold(value):
    return unicodedata.normalize("NFKD", unescape(str(value or "")).casefold()
                                   ).encode("ascii", "ignore").decode("ascii")


def event_url(href, base=AGENDA):
    result = urljoin(base, href or "")
    u = urlsplit(result)
    if (u.scheme != "https" or u.hostname != HOST or
            u.username or u.password or u.port or u.query or u.fragment or
            not EVENT.fullmatch(u.path)):
        return None
    return result


def valid_agenda(url):
    u = urlsplit(url)
    if u.scheme != "https" or u.hostname != HOST or u.path != "/agenda":
        return False
    if u.username or u.password or u.port or u.fragment:
        return False
    return not u.query or bool(re.fullmatch(r"page=[1-5]", u.query))


def parse_day(value):
    text = fold(value)
    match = ISO.search(text)
    if match:
        try:
            return dt.date(*map(int, match.groups())).isoformat()
        except ValueError:
            return None
    match = DRUPAL.search(text)
    if match:
        d, name, numeric_month, y = match.groups()
        if MONTHS[name] != int(numeric_month):
            return None
        try:
            return dt.date(int(y), int(numeric_month), int(d)).isoformat()
        except ValueError:
            return None
    match = FRENCH.search(text)
    if match:
        d, month, y = match.groups()
        try:
            return dt.date(int(y), MONTHS[month], int(d)).isoformat()
        except ValueError:
            return None
    return None


class _Agenda(HTMLParser):
    """Capture only bounded DOM cards/anchors that connect URL, date and genre."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.candidates = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        params = dict(attrs)
        if tag in SKIP:
            self.skip += 1
        if tag in VOID:
            return
        node = {"tag": tag, "class": params.get("class", ""),
                "text": [], "urls": [], "datetimes": []}
        self.stack.append(node)
        link = event_url(params.get("href")) if tag == "a" else None
        if link:
            for n in self.stack:
                n["urls"].append(link)
        date = params.get("datetime", "")
        if tag == "time" and ISO.search(date):
            for n in self.stack:
                n["datetimes"].append(date)

    def handle_endtag(self, tag):
        if tag in SKIP and self.skip:
            self.skip -= 1
        if tag in VOID:
            return
        while self.stack:
            n = self.stack.pop()
            if self.skip == 0:
                classes = n["class"].casefold()
                is_card = (
                    n["tag"] in ("article", "a")
                    or (n["tag"] in ("div", "li", "section")
                        and any(word in classes for word in
                                ("views-row", "event-card", "agenda-item",
                                 "event-item", "concert-card", "event-block")))
                )
                if is_card:
                    self.candidates.append(n)
            if n["tag"] == tag:
                break

    def handle_data(self, data):
        if self.skip:
            return
        text = " ".join(data.split())
        if text:
            for node in self.stack:
                node["text"].append(text)


def agenda_cards(html, url=AGENDA, today="2026-11-03"):
    """Never infer year or use navigation-wide category labels as proof."""
    if not valid_agenda(url):
        raise ValueError("Only official paginated 106 agenda allowed")
    parser = _Agenda()
    parser.feed(html)
    day = dt.date.fromisoformat(today)
    result = {}
    for node in parser.candidates:
        urls = set(node["urls"])
        if len(urls) != 1:
            continue
        link = next(iter(urls))
        text = " ".join(node["text"])
        parsed_date = None
        for value in node["datetimes"] + [text]:
            parsed_date = parse_day(value)
            if parsed_date:
                break
        if not parsed_date:
            continue
        when = dt.date.fromisoformat(parsed_date)
        if not day <= when <= day + dt.timedelta(days=365):
            continue
        if STOP.search(fold(text)):
            continue
        genre = ROCK.search(fold(text))
        if not genre:
            continue
        row = {
            "url": link, "date": parsed_date,
            "classification": genre.group(0).title(),
            "evidence": "official_agenda_card_with_year",
        }
        # A large parent card is more useful than a tiny same-link anchor;
        # never override an existing item with missing year or genre.
        result[link] = row
    return sorted(result.values(), key=lambda x: (x["date"], x["url"]))


def selected_cards(cards, known, today, limit=8):
    limit = max(1, min(12, int(limit)))
    unique = {x["url"]: x for x in cards}
    future = sorted(unique.values(), key=lambda x: (x["date"], x["url"]))
    unseen = [x for x in future if ("officialUrl", x["url"]) not in known]
    existing = [x for x in future if ("officialUrl", x["url"]) in known]
    def rotate(items, count):
        if not items or count <= 0:
            return []
        count = min(count, len(items))
        start = (dt.date.fromisoformat(today).toordinal() * count) % len(items)
        return [items[(start + i) % len(items)] for i in range(count)]
    first = rotate(unseen, limit)
    return first + rotate(existing, limit - len(first))


class _Detail(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.inside_main = 0
        self.inside_h1 = 0
        self.title = []
        self.visible = []
        self.skipped = 0

    def handle_starttag(self, tag, attrs):
        if tag == "main":
            self.inside_main += 1
        if tag in SKIP:
            self.skipped += 1
        if tag == "h1" and self.inside_main:
            self.inside_h1 += 1

    def handle_endtag(self, tag):
        if tag in SKIP and self.skipped:
            self.skipped -= 1
        if tag == "h1" and self.inside_h1:
            self.inside_h1 -= 1
        if tag == "main" and self.inside_main:
            self.inside_main -= 1

    def handle_data(self, text):
        if self.skipped or not self.inside_main:
            return
        clean = " ".join(text.split())
        if clean:
            self.visible.append(clean)
            if self.inside_h1:
                self.title.append(clean)


def candidate(html, url, card, source, today):
    if (event_url(url) != url or card.get("url") != url or
            source.get("name") != "Le 106" or
            source.get("city") != "Rouen" or
            source.get("department") != "76"):
        raise ValueError("Mismatched first-party venue or detail URL")
    if not card.get("date") or card["date"] != parse_day(card["date"]):
        raise ValueError("Agenda has no full date")
    when = dt.date.fromisoformat(card["date"])
    day = dt.date.fromisoformat(today)
    if not day <= when <= day + dt.timedelta(days=365):
        raise ValueError("Outside concert horizon")
    if not ROCK.search(fold(card.get("classification", ""))):
        raise ValueError("Unproven rock/metal/punk genre")
    p = _Detail()
    p.feed(html)
    title = " ".join(p.title).strip()
    title = re.sub(r"\s*\+\s*", " + ", title)
    if not 3 <= len(title) <= 180 or not p.visible:
        raise ValueError("Official named event headline missing")
    if STOP.search(fold(title + " ".join(p.visible[:8]))):
        raise ValueError("Event cancelled, festival or workshop")
    if not re.search(r"\ble 106\b", fold(" ".join(p.visible))):
        raise ValueError("Exact venue not confirmed in detail")
    lead = title.split(" + ", 1)[0].strip()
    if not re.search(r"[a-z]{3}", fold(lead)):
        raise ValueError("No identified headline act")
    slug = EVENT.fullmatch(urlsplit(url).path)[1]
    return {
        "candidateId": "le106:" + card["date"] + ":" + slug,
        "name": title, "leadArtist": lead, "date": card["date"],
        "venue": "Le 106", "city": "Rouen", "department": "76",
        "classification": [card["classification"]],
        "genreEvidence": "official_agenda_event_card",
        "genreToConfirm": False,
        "source": "agenda_officiel_le106_review_only",
        "sourcePage": AGENDA, "sourceUrl": url,
        "sourceConfidence": (
            "Agenda officiel daté avec année + fiche nominative de la salle. "
            "L'heure annoncée au 106 peut être celle des portes; heure musicale inconnue. "
            "Line-up complet et disponibilité à confirmer avant toute approbation."),
        "officialDetailFound": True,
        "localTime": None, "publicationAllowed": False, "reviewRequired": True,
    }
