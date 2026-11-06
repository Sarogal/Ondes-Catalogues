"""Chato'do (Blois): official event-detail leads, never automatic approvals.

The listing often omits the year and contains links to photo galleries.
Only named event detail pages with an unambiguous year, genre, room and
first-party metadata are eligible for a review-only candidate.
"""
from __future__ import annotations

import datetime as dt
from html import unescape
from html.parser import HTMLParser
import re
import unicodedata
from urllib.parse import urljoin, urlsplit

AGENDA = "https://chatodo.com/agenda/"
DOMAIN = "chatodo.com"
EVENT_PATH = re.compile(r"/agenda/evenement/([a-z0-9][a-z0-9-]{2,125})/")
MONTHS = {
    "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5,
    "juin": 6, "juillet": 7, "aout": 8, "septembre": 9,
    "octobre": 10, "novembre": 11, "decembre": 12,
}
DATE = re.compile(
    r"\b([0-3]?\d)\s+(janvier|fevrier|mars|avril|mai|juin|juillet|aout|"
    r"septembre|octobre|novembre|decembre)\s+(20\d{2})\b")
GENRE = re.compile(
    r"\b(?:rock|garage|metal|punk|hardcore|heavy|stoner|doom|"
    r"sludge|noise|grind|post[- ]rock|shoegaze|psych[eé]d[eé]lique)\b")
STOP = re.compile(
    r"\b(?:annul[eé]|annulation|report[eé]|festival|atelier|"
    r"conf[eé]rence|masterclass|canceled|cancelled|postponed)\b")
ROOM = re.compile(r"\b(?:le club|grande salle|la grande salle)\b")
SKIP = {"style", "script", "nav", "footer", "noscript"}
VOID = {"meta", "link", "input", "img", "br", "hr", "source"}


def fold(value):
    return unicodedata.normalize("NFKD", unescape(str(value or "")).casefold()
                                   ).encode("ascii", "ignore").decode("ascii")


def event_url(value, base=AGENDA):
    url = urljoin(base, value or "")
    u = urlsplit(url)
    if (u.scheme != "https" or u.hostname != DOMAIN or u.port
            or u.username or u.password or u.query or u.fragment
            or not EVENT_PATH.fullmatch(u.path)):
        return None
    return url


def agenda_url(value):
    u = urlsplit(value)
    return bool(u.scheme == "https" and u.hostname == DOMAIN
                and not u.username and not u.password and not u.port
                and not u.query and not u.fragment and
                re.fullmatch(r"/agenda/(?:page/[2-4]/)?", u.path))


def parse_dates(value):
    results = set()
    for day, month, year in DATE.findall(fold(value)):
        try:
            results.add(dt.date(int(year), MONTHS[month], int(day)).isoformat())
        except ValueError:
            return set()
    return results


def parse_date(value):
    dates = parse_dates(value)
    return next(iter(dates)) if len(dates) == 1 else None


class AgendaLinks(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href")
        link = event_url(href) if href else None
        if link and link not in self.links:
            self.links.append(link)


def official_links(page, source_url):
    if not agenda_url(source_url):
        raise ValueError("Expected official Chato'do event agenda")
    parser = AgendaLinks()
    parser.feed(page)
    return parser.links


def selected_urls(urls, known, day, limit=8):
    limit = max(1, min(10, int(limit)))
    distinct = sorted(set(u for u in urls if event_url(u) == u))
    unseen = [u for u in distinct if ("officialUrl", u) not in known]
    existing = [u for u in distinct if ("officialUrl", u) in known]

    def rotation(items, n):
        if not items or n <= 0:
            return []
        n = min(n, len(items))
        start = (dt.date.fromisoformat(day).toordinal() * n) % len(items)
        return [items[(start + i) % len(items)] for i in range(n)]

    first = rotation(unseen, limit)
    return first + rotation(existing, limit-len(first))


class Detail(HTMLParser):
    """Keep first-party OG title and a bounded ordered set of article fields."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.og_title = None
        self.page_title = []
        self.in_title = False
        self.in_main = 0
        self.in_article = 0
        self.in_p = 0
        self.paragraph = []
        self.fields = []
        self.skips = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        properties = dict(attrs)
        if tag == "meta" and properties.get("property") == "og:title":
            self.og_title = properties.get("content")
        if tag == "title":
            self.in_title = True
        if tag in SKIP:
            self.skips += 1
        if tag == "main":
            self.in_main += 1
        if tag == "article" and self.in_main:
            self.in_article += 1
        if tag == "p" and self.in_article:
            self.in_p += 1
            if self.in_p == 1:
                self.paragraph = []

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in SKIP and self.skips:
            self.skips -= 1
        if tag == "title":
            self.in_title = False
        if tag == "p" and self.in_p:
            self.in_p -= 1
            if self.in_p == 0:
                item = " ".join(" ".join(self.paragraph).split())
                if item:
                    self.fields.append(item)
        if tag == "article" and self.in_article:
            self.in_article -= 1
        if tag == "main" and self.in_main:
            self.in_main -= 1

    def handle_data(self, data):
        if self.in_title:
            self.page_title.append(data)
        if not self.skips and self.in_main and self.in_article and self.in_p:
            self.paragraph.append(data)


def candidate(detail_html, url, source, today):
    slug = event_url(url)
    if (slug != url or source.get("name") != "Le Chato'do"
            or source.get("city") != "Blois"
            or source.get("department") != "41"):
        raise ValueError("Untrusted venue or event URL")
    p = Detail()
    p.feed(detail_html)
    heading = (p.og_title or " ".join(p.page_title)).strip()
    if not heading.endswith(" - Chato'do"):
        raise ValueError("First-party event title missing or foreign")
    name = heading.removesuffix(" - Chato'do").strip()
    if not 3 <= len(name) <= 160 or STOP.search(fold(name)):
        raise ValueError("Not a named live concert")
    header = p.fields[:24]
    if not header:
        raise ValueError("No official article details")
    dates = {d for field in header for d in parse_dates(field)}
    if len(dates) != 1:
        raise ValueError("Concert date absent or ambiguous")
    date = dates.pop()
    day = dt.date.fromisoformat(today)
    date_obj = dt.date.fromisoformat(date)
    if not day <= date_obj <= day + dt.timedelta(days=365):
        raise ValueError("Concert outside the valid future horizon")
    genre_field = next((x for x in header[:18]
                        if len(x) <= 55 and GENRE.search(fold(x))), None)
    if genre_field is None:
        raise ValueError("Official event genre not rock/metal/punk")
    if not any(ROOM.search(fold(x)) for x in header[:24]):
        raise ValueError("Exact room at Chato'do not established")
    if STOP.search(fold(" ".join(header[:11]))):
        raise ValueError("Cancelled, postponed or festival context")
    # Only the first-party headline lists identified performers; review will
    # determine the complete official lineup before any future approval.
    lead = re.split(r"\s+\+\s+", name, maxsplit=1)[0].strip()
    if len(lead) < 3:
        raise ValueError("Unknown headlining artist")
    return {
        "candidateId": "chatodo:" + date + ":" +
                       EVENT_PATH.fullmatch(urlsplit(url).path)[1],
        "name": name, "leadArtist": lead, "date": date,
        "venue": "Le Chato'do", "city": "Blois", "department": "41",
        "classification": [genre_field],
        "genreEvidence": "official_first_party_event_header",
        "genreToConfirm": False,
        "source": "agenda_officiel_chatodo_detail_review",
        "sourcePage": AGENDA, "sourceUrl": url,
        "sourceConfidence": (
            "Fiche officielle Chato'do: année, titre, genre et salle. "
            "Piste à vérifier avant approbation, notamment les premières parties. "
            "L'horaire de portes ne vaut pas heure de concert."),
        "officialDetailFound": True, "localTime": None,
        "reviewRequired": True, "publicationAllowed": False,
    }
