"""Le Cargö (Caen): read-only review leads from exact official concert details.

Unlike the broad event category on the programme, an individual page gives
a calendar year and separates DOOR time from actual musical start. Restrict
date extraction to the ticket facts near 'Ouverture des portes'; artist bios
can mention album-release years and MUST NOT be used as concert dates.
"""
from __future__ import annotations

import datetime as dt
from html import unescape
from html.parser import HTMLParser
import re
import unicodedata
from urllib.parse import urljoin, urlsplit

AGENDA = "https://lecargo.fr/programmation/concert/"
HOST = "lecargo.fr"
DETAIL = re.compile(r"/programmation/concert/([a-z0-9][a-z0-9-]{2,125})/")
MONTHS = {
    "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5,
    "juin": 6, "juillet": 7, "aout": 8, "septembre": 9,
    "octobre": 10, "novembre": 11, "decembre": 12,
}
FRENCH = re.compile(
    r"\b([0-3]?\d)\s+(janvier|fevrier|mars|avril|mai|juin|juillet|"
    r"aout|septembre|octobre|novembre|decembre)\s+(20\d{2})\b")
GENRE = re.compile(
    r"\b(?:hardcore|heavy\s+rock|hard\s+rock|post[- ]rock|rock|"
    r"thrash|metal|punk|stoner|doom|sludge|noise|grunge|"
    r"shoegaze|garage|deathcore|grind)\b")
NONCONCERT = re.compile(
    r"\b(?:festival|atelier|conference|exposition|masterclass|"
    r"rencontre|jeune public|comedie|spectacle)\b")
ROOM = re.compile(r"\b(?:club|grande salle)\b")
DOORS = re.compile(r"\bouverture des portes\s*:\s*([01]?\d|2[0-3])\s*h\s*([0-5]?\d)?\b")
START = re.compile(r"\bdebut des concerts\s*:\s*([01]?\d|2[0-3])\s*h\s*([0-5]?\d)?\b")
SKIP = {"script", "style", "nav", "footer", "noscript", "svg"}


def fold(value):
    return unicodedata.normalize(
        "NFKD", unescape(str(value or "")).casefold()
    ).encode("ascii", "ignore").decode("ascii")


def valid_agenda(url):
    u = urlsplit(url)
    return (u.scheme == "https" and u.hostname == HOST and
            u.path == "/programmation/concert/" and
            not (u.port or u.username or u.password or u.query or u.fragment))


def event_url(value, base=AGENDA):
    url = urljoin(base, value or "")
    u = urlsplit(url)
    return (url if (u.scheme == "https" and u.hostname == HOST and
                    not (u.port or u.username or u.password or u.query or u.fragment)
                    and DETAIL.fullmatch(u.path)) else None)


class OfficialPage(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.main = 0
        self.skips = 0
        self.in_h1 = 0
        self.heading = []
        self.text = []
        self.h1_end = None

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "a":
            url = event_url(dict(attrs).get("href"))
            if url and url not in self.links:
                self.links.append(url)
        if tag in SKIP:
            self.skips += 1
        if tag == "main":
            self.main += 1
        if tag == "h1" and self.main and not self.skips:
            self.in_h1 += 1

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "h1" and self.in_h1:
            self.in_h1 -= 1
            self.h1_end = len(self.text)
        if tag == "main" and self.main:
            self.main -= 1
        if tag in SKIP and self.skips:
            self.skips -= 1

    def handle_data(self, value):
        if self.skips or not self.main:
            return
        text = " ".join(value.split())
        if text:
            self.text.append(text)
            if self.in_h1:
                self.heading.append(text)


def agenda_links(page, url=AGENDA):
    if not valid_agenda(url):
        raise ValueError("Not an allowlisted official Cargö concert listing")
    parser = OfficialPage()
    parser.feed(page)
    return parser.links


def selected_urls(urls, known, today, limit=8):
    quota = max(1, min(8, int(limit)))
    unique = sorted(set(u for u in urls if event_url(u) == u))
    fresh = [u for u in unique if ("officialUrl", u) not in known]
    old = [u for u in unique if ("officialUrl", u) in known]
    def rotate(items, count):
        if not items or count <= 0:
            return []
        start = dt.date.fromisoformat(today).toordinal() % len(items)
        return [items[(start+i) % len(items)] for i in range(min(count, len(items)))]
    first = rotate(fresh, quota)
    return first + rotate(old, quota-len(first))


def _clock(match):
    if match is None:
        return None
    return f"{int(match[1]):02d}:{int(match[2] or '0'):02d}"


def candidate(page, url, source, today):
    if (event_url(url) != url or source.get("name") != "Le Cargö" or
            source.get("city") != "Caen" or source.get("department") != "14"):
        raise ValueError("Unexpected concert URL or venue")
    parser = OfficialPage()
    parser.feed(page)
    title = " ".join(" ".join(parser.heading).split())
    if parser.h1_end is None or not 3 <= len(title) <= 170:
        raise ValueError("First-party named event heading missing")
    if NONCONCERT.search(fold(title)):
        raise ValueError("Not a distinct single concert")
    body = fold(" ".join(parser.text))
    if not body:
        raise ValueError("No official event detail text")
    doors = list(re.finditer(r"\bouverture des portes\s*:", body))
    if len(doors) != 1:
        raise ValueError("Missing or ambiguous event ticket facts")
    idx = doors[0].start()
    # Ticket summary immediately precedes 'Ouverture des portes'. The page's
    # biographical section can mention several other years: ignore it.
    facts = body[max(0, idx-330):idx]
    dates = list(FRENCH.finditer(facts))
    if not dates:
        raise ValueError("No full concert year in first-party ticket section")
    chosen = dates[-1]
    day, month, year = chosen.groups()
    try:
        concert_day = dt.date(int(year), MONTHS[month], int(day))
    except ValueError as error:
        raise ValueError("Invalid official concert date") from error
    current = dt.date.fromisoformat(today)
    if not current <= concert_day <= current + dt.timedelta(days=365):
        raise ValueError("Outside one-year date horizon")
    between = facts[chosen.end():]
    if not ROOM.search(between):
        raise ValueError("Cargö room is not established (potential offsite)")
    if re.search(r"\b(?:bibliotheque|auditorium|hors les murs)\b", between):
        raise ValueError("Off-site event without venue confirmation")
    # Broad 'Concert' is not a music genre. The actual artist/event
    # description must contain a relevant genre before the ticket facts.
    artist_context = body[:idx]
    match = GENRE.search(artist_context)
    if not match:
        raise ValueError("Music genre not relevant or not substantiated")
    lead = re.split(r"\s+\+\s+", title, maxsplit=1)[0]
    if len(re.findall(r"[a-z]", fold(lead))) < 3:
        raise ValueError("Performer identity unavailable")
    tail = body[idx:idx+220]
    actual_start = _clock(START.search(tail))
    door_time = _clock(DOORS.search(tail))
    cancelled = bool(re.search(r"\b(?:annulation|annule|reporte)\b", fold(title)))
    slug = DETAIL.fullmatch(urlsplit(url).path)[1]
    return {
        "candidateId": "cargo:" + concert_day.isoformat() + ":" + slug,
        "name": title, "leadArtist": lead, "date": concert_day.isoformat(),
        "venue": "Le Cargö", "city": "Caen", "department": "14",
        "classification": [match.group(0).title()],
        "genreToConfirm": True,
        "source": "cargo_official_detail_review",
        "sourcePage": AGENDA, "sourceUrl": url,
        "officialDetailFound": True,
        "dateEvidence": "first_party_full_date_in_ticket_facts",
        "localTime": actual_start, "announcedDoorTime": door_time,
        "timeMeaning": ("explicit_first_party_concert_start"
                        if actual_start is not None else "unknown"),
        "cancellationNotice": cancelled,
        "sourceConfidence": (
            "Fiche officielle Le Cargö: date complète et salle dans le bloc "
            "billetterie; genre à confirmer depuis la biographie des artistes. "
            "Ouverture des portes distincte du début des concerts; "
            "aucune publication sans validation."
        ),
        "publicationAllowed": False, "reviewRequired": True,
    }
