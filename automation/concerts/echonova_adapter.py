"""Echonova (Saint-Avé, 56): bounded official-detail discovery, no approvals.

Require a first-party individual page with the fully written year, exact
venue, concert tag and rock/metal/punk tag. Programme cards and music
biographies alone cannot prove these facts. No automatic publication.
"""
from __future__ import annotations

import datetime as dt
from html import unescape
from html.parser import HTMLParser
import re
import unicodedata
from urllib.parse import urljoin, urlsplit

BASE = "https://lechonova.com"
AGENDA = BASE + "/programmation/"
DETAIL = re.compile(r"/evenement/([a-z0-9][a-z0-9-]{2,140})/")
MONTHS = {
    "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5,
    "juin": 6, "juillet": 7, "aout": 8, "septembre": 9, "octobre": 10,
    "novembre": 11, "decembre": 12,
}
DATE = re.compile(
    r"\b([0-3]?\d)\s+(" + "|".join(MONTHS) +
    r")\s+(20\d{2})\s*[-–]\s*l[' ]?echonova\b"
)
ROCK_TAGS = {
    "rock", "metal", "punk", "post-punk", "hard rock", "rock alternatif",
    "post-rock", "garage rock", "stoner", "doom", "sludge", "noise rock",
}
EXCLUDED = re.compile(
    r"\b(?:annule|reporte|festival|atelier|conference|formation|"
    r"table ronde|dj set|technoparade)\b"
)


def fold(value):
    return (unicodedata.normalize("NFKD", unescape(str(value or "")))
            .casefold().encode("ascii", "ignore").decode("ascii")
            .replace("’", "'"))


def canonical_detail(value):
    u = urlsplit(value)
    if (u.scheme != "https" or u.netloc != "lechonova.com" or
            u.username or u.password or u.port or u.query or u.fragment or
            not DETAIL.fullmatch(u.path)):
        return None
    return BASE + u.path


class _Links(HTMLParser):
    def __init__(self, base):
        super().__init__(convert_charrefs=True)
        self.base = base
        self.urls = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href")
            url = canonical_detail(urljoin(self.base, href)) if href else None
            if url and url not in self.urls:
                self.urls.append(url)


def agenda_links(html, url):
    if url != AGENDA:
        raise ValueError("Unexpected Echonova official programme URL")
    p = _Links(url)
    p.feed(html)
    return p.urls


def select_urls(urls, known, today, limit=6):
    limit = max(1, min(8, int(limit)))
    ordered = sorted(set(x for x in urls if canonical_detail(x) == x))
    unknown = [x for x in ordered if ("officialUrl", x) not in known]
    previous = [x for x in ordered if ("officialUrl", x) in known]
    def rotate(group, amount):
        if not group or amount <= 0:
            return []
        offset = (dt.date.fromisoformat(today).toordinal() * amount) % len(group)
        return [group[(offset + i) % len(group)]
                for i in range(min(len(group), amount))]
    selected = rotate(unknown, limit)
    return selected + rotate(previous, limit - len(selected))


class _Detail(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_main = 0
        self.related = False
        self.skip = 0
        self.li = 0
        self.li_text = []
        self.tags = []
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == "main":
            self.in_main += 1
        elif tag == "article" and self.in_main:
            # Recommendations are not evidence for the detail currently read.
            self.related = True
        if tag in ("script", "style", "nav", "footer", "noscript"):
            self.skip += 1
        if tag == "li" and self.in_main and not self.related:
            self.li += 1
            self.li_text = []

    def handle_endtag(self, tag):
        if tag == "li" and self.li:
            self.tags.append(" ".join(self.li_text).strip())
            self.li = 0
        if tag in ("script", "style", "nav", "footer", "noscript") and self.skip:
            self.skip -= 1
        if tag == "main" and self.in_main:
            self.in_main -= 1

    def handle_data(self, text):
        if not self.in_main or self.related or self.skip or not text.strip():
            return
        piece = " ".join(text.split())
        if piece:
            self.parts.append(piece)
            if self.li:
                self.li_text.append(piece)


def candidate(html, url, source, today):
    if canonical_detail(url) != url:
        raise ValueError("Unrecognized Echonova official event URL")
    if (source.get("name"), source.get("city"), source.get("department")) != (
            "L'Echonova", "Saint-Avé", "56"):
        raise ValueError("Unexpected venue identity")
    p = _Detail()
    p.feed(html)
    parts = p.parts
    date_info = None
    for index, text in enumerate(parts):
        found = DATE.search(fold(text))
        if found:
            date_info = (index, found)
            break
    if not date_info:
        raise ValueError("No full first-party event date and exact venue")
    index, matched = date_info
    try:
        date = dt.date(int(matched[3]), MONTHS[matched[2]], int(matched[1]))
    except ValueError:
        raise ValueError("Invalid official date") from None
    anchor = dt.date.fromisoformat(today)
    if not anchor <= date <= anchor + dt.timedelta(days=365):
        raise ValueError("Past or distant date")
    if index < 1:
        raise ValueError("No named first-party event title")
    title = parts[index - 1]
    if not 4 <= len(title) <= 160 or EXCLUDED.search(fold(title)):
        raise ValueError("Non-concert or uncertain official title")
    tags = {fold(x).strip() for x in p.tags}
    music = sorted(tags & ROCK_TAGS)
    if "concert" not in tags or not music:
        raise ValueError("No official concert and relevant genre tags")
    if "hardcore" in tags and not music:
        raise ValueError("Unqualified electronic hardcore")
    first_party_fact = " ".join(parts[index + 1:index + 12])
    start = re.search(r"\bdebut des concerts\s*:\s*([01]?\d|2[0-3]):([0-5]\d)\b",
                      fold(first_party_fact))
    local_time = (f"{int(start[1]):02d}:{start[2]}" if start else None)
    artist = re.split(r"\s+\+\s+", title, maxsplit=1)[0]
    slug = DETAIL.fullmatch(urlsplit(url).path)[1]
    return {
        "candidateId": "echonova:" + date.isoformat() + ":" + slug,
        "name": title, "leadArtist": artist, "date": date.isoformat(),
        "venue": "L'Echonova", "city": "Saint-Avé", "department": "56",
        "source": "echonova_official_detail_review",
        "sourceUrl": url, "sourcePage": AGENDA,
        "classification": music, "genreToConfirm": True,
        "officialDetailFound": True, "localTime": local_time,
        "sourceConfidence": "Fiche officielle nominative : année, salle, catégorie et concert; heure uniquement si explicitement début des concerts.",
        "publicationAllowed": False, "reviewRequired": True,
    }
