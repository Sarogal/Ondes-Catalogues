"""Le Temps Machine (Joué-lès-Tours): first-party, review-only concert discovery.

A list item gives a useful link, NOT an approval. A named detail page must
corroborate the year, category and exact room. The site's own access page says
ticket times are DOOR times, so never infer concert start times.
"""
from __future__ import annotations

import datetime as dt
from html import unescape
from html.parser import HTMLParser
import re
import unicodedata
from urllib.parse import parse_qs, urljoin, urlsplit

SITE = "https://letempsmachine.com"
AGENDA = SITE + "/agenda?category=All&location=All"
DETAIL_PATH = re.compile(r"/agenda/([a-z0-9][a-z0-9-]{2,125})")
MONTHS = {
    "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4,
    "mai": 5, "juin": 6, "juillet": 7, "aout": 8,
    "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12,
}
FULL_DATE = re.compile(
    r"\b([0-3]?\d)\s+(janvier|fevrier|mars|avril|mai|juin|juillet|aout|"
    r"septembre|octobre|novembre|decembre)\s+(20\d{2})\b")
GENRE = re.compile(
    r"\b(?:metal|punk|rock|garage|hardcore|stoner|doom|noise|"
    r"grunge|shoegaze|sludge)\b", re.I)
ROOM = re.compile(r"\ble temps machine\b.{0,100}\b(?:le club|la grande salle|grande salle)\b", re.I)
STOP = re.compile(
    r"\b(?:annule|annulation|reporte|festival|atelier|conference|"
    r"formation|reunion|comedie musicale|jeune public|visite)\b", re.I)


def fold(value):
    return unicodedata.normalize("NFKD", unescape(str(value or "")).casefold()
                                   ).encode("ascii", "ignore").decode("ascii")


def detail_url(value, base=SITE + "/agenda"):
    url = urljoin(base, value or "")
    u = urlsplit(url)
    if (u.scheme != "https" or u.netloc != "letempsmachine.com"
            or not DETAIL_PATH.fullmatch(u.path)
            or u.path in ("/agenda/archives", "/agenda/recherche")
            or u.query or u.fragment or u.username or u.password or u.port):
        return None
    return url


def valid_agenda(url):
    u = urlsplit(url)
    if (u.scheme != "https" or u.netloc != "letempsmachine.com"
            or u.path != "/agenda" or u.fragment or u.username or u.password):
        return False
    pairs = parse_qs(u.query, keep_blank_values=True)
    if set(pairs) not in ({"category", "location"}, {"category", "location", "page"}):
        return False
    if pairs.get("category") != ["All"] or pairs.get("location") != ["All"]:
        return False
    return "page" not in pairs or pairs["page"] == ["1"]


def parse_day(text):
    dates = set()
    for day, month, year in FULL_DATE.findall(fold(text)):
        try:
            dates.add(dt.date(int(year), MONTHS[month], int(day)).isoformat())
        except ValueError:
            return None
    return next(iter(dates)) if len(dates) == 1 else None


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.title = ""
        self.h1 = []
        self.h1_level = 0
        self.main_level = 0
        self.main_text = []
        self.og = None
        self.skip_level = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        props = dict(attrs)
        if tag == "meta" and props.get("property") == "og:title":
            self.og = props.get("content")
        if tag == "a" and props.get("href"):
            url = detail_url(props["href"])
            if url and url not in self.links:
                self.links.append(url)
        if tag in ("script", "style", "noscript"):
            self.skip_level += 1
        if tag == "main":
            self.main_level += 1
        if tag == "h1" and self.main_level:
            self.h1_level += 1

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "h1" and self.h1_level:
            self.h1_level -= 1
        if tag == "main" and self.main_level:
            self.main_level -= 1
        if tag in ("script", "style", "noscript") and self.skip_level:
            self.skip_level -= 1

    def handle_data(self, data):
        if self.skip_level:
            return
        if self.main_level:
            self.main_text.append(data)
        if self.h1_level:
            self.h1.append(data)


def agenda_links(page, url):
    if not valid_agenda(url):
        raise ValueError("Unexpected official Drupal agenda URL")
    parser = Page()
    parser.feed(page)
    return parser.links


def choose(urls, known, today, limit=8):
    limit = max(1, min(9, int(limit)))
    valid = sorted(set(x for x in urls if detail_url(x) == x))
    unknown = [x for x in valid if ("officialUrl", x) not in known]
    existing = [x for x in valid if ("officialUrl", x) in known]

    def rotate(items, quota):
        if not items or quota < 1:
            return []
        # The offset changes every day without a persistent database.
        start = dt.date.fromisoformat(today).toordinal() % len(items)
        return [items[(start+i) % len(items)] for i in range(min(quota, len(items)))]
    first = rotate(unknown, limit)
    return first + rotate(existing, limit-len(first))


def candidate(html, url, source, today):
    if (detail_url(url) != url or source.get("name") != "Le Temps Machine"
            or source.get("city") != "Joué-lès-Tours"
            or source.get("department") != "37"):
        raise ValueError("Foreign source or venue")
    parser = Page()
    parser.feed(html)
    if not parser.og or not parser.og.endswith(" | Le Temps Machine"):
        raise ValueError("Absent official first-party metadata")
    title = " ".join(" ".join(parser.h1).split())
    if not title or len(title) > 175 or len(title) < 4:
        raise ValueError("No named event title")
    detail = fold(" ".join(parser.main_text))
    heading = fold(title)
    if heading not in detail:
        raise ValueError("Event heading mismatches official detail")
    # The first section on the page is the actual event identity. Never
    # take genres or dates from subsequent related listings or the footer.
    start = detail.find(heading)
    header = detail[start:start+1300]
    date_match = FULL_DATE.search(header)
    if not date_match:
        raise ValueError("No year on the first party event")
    # Genre must be an official category AFTER the headline, never a genre
    # guessed from the band's name itself.
    predate = header[len(heading):date_match.start()]
    if not GENRE.search(predate):
        raise ValueError("No first-party genre category near the event heading")
    date = parse_day(header[:date_match.end()])
    if not date:
        raise ValueError("Year or calendar date ambiguous")
    ref = dt.date.fromisoformat(today)
    concert_day = dt.date.fromisoformat(date)
    if not ref <= concert_day <= ref + dt.timedelta(days=365):
        raise ValueError("Date not future within 365 days")
    if STOP.search(fold(title)) or STOP.search(predate):
        raise ValueError("Festival, cancelled or non-concert page")
    if not ROOM.search(header[:1050]):
        raise ValueError("On-site Le Temps Machine club/large hall not established")
    lead = re.split(r"\s+\+\s+", title, maxsplit=1)[0].strip()
    if len(lead) < 3:
        raise ValueError("Missing first-party lead artist")
    genre = GENRE.search(predate).group(0)
    return {
        "candidateId": "letempsmachine:" + date + ":" +
                       DETAIL_PATH.fullmatch(urlsplit(url).path)[1],
        "name": title, "leadArtist": lead, "date": date,
        "venue": "Le Temps Machine", "city": "Joué-lès-Tours",
        "department": "37", "classification": [genre],
        "genreToConfirm": True, "source": "letempsmachine_official_detail_review",
        "sourcePage": AGENDA, "sourceUrl": url,
        "officialDetailFound": True, "localTime": None,
        "sourceConfidence": (
            "Page nominative Drupal : année, catégorie et lieu Le Temps "
            "Machine vérifiés; sous-genre et éventuelles premières parties "
            "à examiner manuellement. Le site précise que les horaires "
            "des billets correspondent à l'ouverture des portes."),
        "reviewRequired": True, "publicationAllowed": False,
    }
