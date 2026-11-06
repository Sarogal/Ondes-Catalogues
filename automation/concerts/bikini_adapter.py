"""Official Le Bikini listing -> first-party detail LEADS only (never publish).

The venue frequently labels door opening times; no time from this adapter
can be interpreted as the start of a concert. Live venue geolocation is
also left untouched until an independently reviewed correction.
"""
from __future__ import annotations

import datetime as dt
from html import unescape
from html.parser import HTMLParser
import re
import unicodedata
from urllib.parse import urljoin, urlsplit


DOMAIN = "lebikini.com"
DETAIL = re.compile(r"^/(20\d{2})/(0[1-9]|1[0-2])/(0[1-9]|[12]\d|3[01])/([a-z0-9-]+)/?$")
GENRES = re.compile(
    r"(?<!\w)(?:metal|metalcore|hardcore|punk|rock|stoner|doom|sludge|thrash|grunge)(?!\w)",
    re.I,
)
CANCELLED = re.compile(r"\b(?:annul[eé]|annul[eé]e|report[eé]|report[eé]e|cancelled|postponed|d[eé]plac[eé])\b", re.I)
MONTHS = {
    "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5,
    "juin": 6, "juillet": 7, "aout": 8, "septembre": 9,
    "octobre": 10, "novembre": 11, "decembre": 12,
}
DATE_LABEL = re.compile(
    r"\b(\d{1,2})\s+(janvier|fevrier|mars|avril|mai|juin|juillet|aout|"
    r"septembre|octobre|novembre|decembre)\s+(20\d{2})\b"
)


def plain(value):
    return unicodedata.normalize("NFKD", unescape(str(value)).casefold()).encode(
        "ascii", "ignore").decode("ascii")


def detail_date(url):
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname != DOMAIN
            or parsed.username or parsed.password or parsed.port
            or parsed.query or parsed.fragment):
        return None
    match = DETAIL.fullmatch(parsed.path)
    if not match:
        return None
    try:
        return dt.date(int(match[1]), int(match[2]), int(match[3]))
    except ValueError:
        return None


class _Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            for name, value in attrs:
                if name.lower() == "href" and value:
                    self.hrefs.append(value)


class _Details(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.h1 = []
        self.heading_begin = None
        self.heading_end = None
        self.in_heading = False
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in ("head", "script", "style", "nav", "footer"):
            self.hidden += 1
        if tag == "h1" and not self.hidden and self.heading_begin is None:
            self.heading_begin = len(self.parts)
            self.in_heading = True

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "h1" and self.in_heading:
            self.heading_end = len(self.parts)
            self.in_heading = False
        if tag in ("head", "script", "style", "nav", "footer") and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if self.hidden:
            return
        text = " ".join(data.split())
        if text:
            self.parts.append(text)
            if self.in_heading:
                self.h1.append(text)


def detail_urls(html, listing_url, today, horizon_days=365):
    parsed = urlsplit(listing_url)
    if parsed.scheme != "https" or parsed.hostname != DOMAIN:
        raise ValueError("Agenda official Le Bikini required")
    day = dt.date.fromisoformat(today)
    parser = _Links()
    parser.feed(html)
    urls = set()
    for href in parser.hrefs:
        full = urljoin(listing_url, href)
        when = detail_date(full)
        if when and day <= when <= day + dt.timedelta(days=horizon_days):
            urls.add(full)
    return sorted(urls, key=lambda u: (detail_date(u), u))


def detail_candidate(html, url, source, today):
    when = detail_date(url)
    day = dt.date.fromisoformat(today)
    if when is None or not day <= when <= day + dt.timedelta(days=365):
        raise ValueError("Non-venue detail or out-of-range day")
    if source.get("name") != "Le Bikini":
        raise ValueError("Venue identity not approved")
    page = _Details()
    page.feed(html)
    if page.heading_begin is None or page.heading_end is None or not page.h1:
        raise ValueError("One first-party event heading required")
    title = " ".join(page.h1).strip()
    before = plain(" ".join(page.parts[max(0, page.heading_begin-22):page.heading_begin]))
    after_parts = page.parts[page.heading_end:]
    if not after_parts or len(title) < 3 or len(title) > 180:
        raise ValueError("No detailed event bill")
    label_dates = {
        dt.date(int(y), MONTHS[mo], int(d))
        for d, mo, y in DATE_LABEL.findall(before)
        if 1 <= int(d) <= 31
    }
    if label_dates != {when}:
        raise ValueError("Date must match both page heading and official URL")
    if "le bikini" not in before:
        raise ValueError("Other venue listed on venue website")
    genre = after_parts[0].strip()
    if not 2 <= len(genre) <= 55 or not GENRES.search(plain(genre)):
        raise ValueError("Genre tag not relevant or missing")
    after = plain(" ".join(after_parts[:120]))
    if not ("ou" in after and "le bikini" in after
            and "parc technologique du canal" in after):
        raise ValueError("Actual venue identity missing on first-party detail")
    if CANCELLED.search(" ".join(page.parts[max(0,page.heading_begin-5):page.heading_end+12])):
        raise ValueError("Cancelled or postponed listing is not a concert")
    # The same venue also hosts multi-day passes and club parties.
    # They remain a cross-calendar review, never a confirmed single concert.
    multi_day = bool(re.search(r"\bpass\s+(?:2\s+jours|vendredi|samedi)\b", plain(title)))
    lead = re.split(r"\s+\+\s+", title, maxsplit=1)[0].strip()
    slug = DETAIL.fullmatch(urlsplit(url).path)[4]
    return {
        "candidateId": f"bikini:{when.isoformat()}:{slug}",
        "date": when.isoformat(), "name": title, "leadArtist": lead,
        "venue": "Le Bikini", "city": source["city"],
        "department": source.get("department", "31"),
        "classification": [genre], "genreToConfirm": True,
        "source": "agenda_officiel_bikini_detail_review",
        "sourcePage": source["url"], "sourceUrl": url,
        "sourceConfidence": "Fiche individuelle officielle datée ; ouverture des portes exclue et identité de salle confirmée. Aucun horaire de début exploité.",
        "officialDetailFound": True, "localTime": None,
        "festivalContext": multi_day,
        "geoReviewRequired": True,
        "publicationAllowed": False, "reviewRequired": True,
    }
