"""Le Tetris (Le Havre): bounded first-party detail leads, NEVER approvals.

The visible agenda and event headers frequently omit the year. Date/year is
accepted ONLY from the same first-party event header, valid <time datetime>,
or a matching first-party JSON-LD MusicEvent with matching venue and title.
The current date and already-published catalogue are not year evidence.
No advertised hour is interpreted as the musical starting time.
"""
from __future__ import annotations

import datetime as dt
from html import unescape
from html.parser import HTMLParser
import json
import re
import unicodedata
from urllib.parse import urljoin, urlsplit

AGENDA = "https://letetris.fr/agenda"
HOST = "letetris.fr"
DETAIL = re.compile(r"/agenda/([a-z0-9][a-z0-9-]{2,125})/?")
BLOCKED_SLUGS = {"archives", "recherche", "search", "page", "category"}
MONTHS = {
    "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4,
    "mai": 5, "juin": 6, "juillet": 7, "aout": 8,
    "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12,
}
MONTH_NAMES = "|".join(MONTHS)
DAY_MONTH = re.compile(r"\b([0-3]?\d)\.\s*(" + MONTH_NAMES + r")\b|"
                       r"\b([0-3]?\d)\s+(" + MONTH_NAMES + r")\b")
FULL_FRENCH = re.compile(r"\b([0-3]?\d)\.?\s+(" + MONTH_NAMES +
                         r")\s+(20\d{2})\b")
ISO_DATE = re.compile(r"^(20\d{2})-(\d{2})-(\d{2})(?:T[\d:.+-Z]+)?$")
GENRE = re.compile(
    r"\b(?:hardcore|punk(?:\s+rock)?|metal|stoner|doom|sludge|noise|"
    r"grunge|shoegaze|post[- ]rock|garage|heavy|rock)\b")
NONCONCERT = re.compile(
    r"\b(?:festival|exposition|atelier|conference|rencontre|formation|"
    r"jeune public|masterclass|visite|cinema|annulation|annule|"
    r"reporte|report du|postponed|cancelled|canceled)\b")
ROOM = re.compile(r"\ble tetris\b.{0,100}\b(?:le club|la grande salle)\b")
SKIP = {"script", "style", "nav", "footer", "noscript", "svg"}


def fold(value):
    return unicodedata.normalize(
        "NFKD", unescape(str(value or "")).casefold()
    ).encode("ascii", "ignore").decode("ascii")


def valid_agenda(url):
    u = urlsplit(url)
    return (u.scheme == "https" and u.hostname == HOST and u.path == "/agenda"
            and not (u.port or u.username or u.password or u.query or u.fragment))


def event_url(href, base=AGENDA):
    url = urljoin(base, href or "")
    u = urlsplit(url)
    match = DETAIL.fullmatch(u.path)
    if (u.scheme != "https" or u.hostname != HOST or u.port or u.username or
            u.password or u.query or u.fragment or not match or
            match.group(1) in BLOCKED_SLUGS):
        return None
    return url


def iso(value):
    match = ISO_DATE.fullmatch(str(value or "").strip())
    if not match:
        return None
    try:
        return dt.date(*(int(x) for x in match.groups())).isoformat()
    except ValueError:
        return None


def daymonth(value):
    found = set()
    for match in DAY_MONTH.finditer(fold(value)):
        d, m = match.group(1, 2) if match.group(1) else match.group(3, 4)
        try:
            date = dt.date(2024, MONTHS[m], int(d))  # leap-year validation only
        except ValueError:
            return None
        found.add((date.month, date.day))
    return next(iter(found)) if len(found) == 1 else None


class EventPage(HTMLParser):
    """Only first-party main/article content; never global navigation or recommendations."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.main = 0
        self.skipped = 0
        self.h1_depth = 0
        self.h2_depth = 0
        self.tokens = []
        self.heading = []
        self.h1_end = None
        self.h2_at = None
        self.dates = []
        self.ld_blocks = []
        self.in_ld = False
        self.ld_parts = []
        self.og_title = None

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        props = dict(attrs)
        if tag == "a":
            link = event_url(props.get("href"))
            if link and link not in self.links:
                self.links.append(link)
        if tag == "meta" and props.get("property") == "og:title":
            self.og_title = props.get("content")
        if tag == "script" and props.get("type") == "application/ld+json":
            self.in_ld = True
            self.ld_parts = []
        if tag in SKIP:
            self.skipped += 1
        if tag == "main":
            self.main += 1
        if self.main and not self.skipped:
            if tag == "h1":
                self.h1_depth += 1
            if tag == "h2":
                self.h2_depth += 1
                if self.h2_at is None:
                    self.h2_at = len(self.tokens)
            if tag == "time" and props.get("datetime"):
                self.dates.append(props["datetime"])

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "h1" and self.h1_depth:
            self.h1_depth -= 1
            self.h1_end = len(self.tokens)
        if tag == "h2" and self.h2_depth:
            self.h2_depth -= 1
        if tag == "main" and self.main:
            self.main -= 1
        if tag == "script" and self.in_ld:
            self.ld_blocks.append("".join(self.ld_parts))
            self.in_ld = False
        if tag in SKIP and self.skipped:
            self.skipped -= 1

    def handle_data(self, value):
        if self.in_ld:
            self.ld_parts.append(value)
        if self.skipped or not self.main:
            return
        text = " ".join(value.split())
        if text:
            self.tokens.append(text)
            if self.h1_depth:
                self.heading.append(text)


def agenda_links(page, url=AGENDA):
    if not valid_agenda(url):
        raise ValueError("Unexpected Le Tetris agenda URL")
    parsed = EventPage()
    parsed.feed(page)
    return parsed.links


def choose(urls, known, today, limit=8):
    quota = max(1, min(8, int(limit)))
    clean = sorted(set(u for u in urls if event_url(u) == u))
    unseen = [u for u in clean if ("officialUrl", u) not in known]
    existing = [u for u in clean if ("officialUrl", u) in known]
    def rotate(items, n):
        if not items or n <= 0:
            return []
        start = dt.date.fromisoformat(today).toordinal() % len(items)
        return [items[(start + i) % len(items)] for i in range(min(n, len(items)))]
    selected = rotate(unseen, quota)
    return selected + rotate(existing, quota - len(selected))


def _json_events(raw):
    if isinstance(raw, list):
        for item in raw:
            yield from _json_events(item)
    elif isinstance(raw, dict):
        if raw.get("@type") in ("MusicEvent", "Event"):
            yield raw
        for child in raw.get("@graph", []):
            yield from _json_events(child)


def _official_year(parser, title, observed_daymonth):
    """Return (iso-day, proof) only with year matching displayed day/month."""
    possible = set()
    # The header ends before the first artist biography <h2>.
    end = min(parser.h2_at or len(parser.tokens), 85)
    header = " ".join(parser.tokens[:end])
    for d, month, year in FULL_FRENCH.findall(fold(header)):
        try:
            possible.add(dt.date(int(year), MONTHS[month], int(d)).isoformat())
        except ValueError:
            pass
    for value in parser.dates:
        parsed = iso(value)
        if parsed:
            possible.add(parsed)
    for block in parser.ld_blocks:
        try:
            record = json.loads(block)
        except (ValueError, TypeError):
            continue
        for event in _json_events(record):
            where = event.get("location", {})
            if isinstance(where, dict):
                where = where.get("name", "")
            name = fold(event.get("name", ""))
            title_f = fold(title)
            if ("le tetris" not in fold(where) or not name or
                    not (name in title_f or title_f in name)):
                continue
            parsed = iso(event.get("startDate"))
            if parsed:
                possible.add(parsed)
    possible = {
        value for value in possible
        if (int(value[5:7]), int(value[8:10])) == observed_daymonth
    }
    if len(possible) != 1:
        return None, None
    return next(iter(possible)), "explicit_first_party_year"


def candidate(page, url, source, today):
    if (event_url(url) != url or source.get("name") != "Le Tetris" or
            source.get("city") != "Le Havre" or
            source.get("department") != "76"):
        raise ValueError("Invalid first-party event or venue")
    parsed = EventPage()
    parsed.feed(page)
    if parsed.h1_end is None or parsed.h2_at is None:
        raise ValueError("Unrecognized official concert detail structure")
    title = " ".join(" ".join(parsed.heading).split())
    if not (3 <= len(title) <= 160):
        raise ValueError("Event headline missing")
    # Some Tetris pages put '+ supporting act' immediately after the H1.
    after = parsed.tokens[parsed.h1_end:parsed.h2_at]
    if after and after[0].strip() == "+" and len(after) > 1:
        title += " + " + after[1].strip()
    elif after and re.match(r"^\+\s+\S", after[0]):
        title += " " + after[0].strip()
    title = re.sub(r"\s+\+\s+", " + ", title).strip()
    end = min(parsed.h2_at, 85)
    header_tokens = parsed.tokens[:end]
    header = fold(" ".join(header_tokens))
    # Genre must be in the event's pre-biography category/header, not in
    # advertising, a related-event card, or the performers' narrative.
    genre_text = fold(" ".join(after[:18]))
    match = GENRE.search(genre_text)
    if not match:
        raise ValueError("Not an explicitly rock/punk/metal concert")
    if NONCONCERT.search(fold(title)) or NONCONCERT.search(header):
        raise ValueError("Festival, workshop, cancellation or postponed date")
    if not ROOM.search(header):
        raise ValueError("Exact Le Tetris room not established")
    observed = daymonth(" ".join(header_tokens[:35]))
    if observed is None:
        raise ValueError("Event's visible day and month absent/ambiguous")
    date, year_proof = _official_year(parsed, title, observed)
    if date is not None:
        d = dt.date.fromisoformat(date)
        ref = dt.date.fromisoformat(today)
        if not ref <= d <= ref + dt.timedelta(days=365):
            raise ValueError("Outside one-year future horizon")
    lead = re.split(r"\s+\+\s+", title, maxsplit=1)[0].strip()
    if len(re.findall(r"[a-z]", fold(lead))) < 3:
        raise ValueError("Unidentified headlining performer")
    slug = DETAIL.fullmatch(urlsplit(url).path)[1]
    return {
        "candidateId": "tetris:" + slug,
        "name": title, "leadArtist": lead,
        "date": date,
        "displayedDayMonth": f"{observed[1]:02d}-{observed[0]:02d}",
        "dateEvidence": year_proof or "year_not_established",
        "venue": "Le Tetris", "city": "Le Havre", "department": "76",
        "classification": [match.group(0).title()],
        "genreToConfirm": True,
        "source": "tetris_official_detail_review",
        "sourcePage": AGENDA, "sourceUrl": url,
        "sourceConfidence": (
            "Fiche nominative officielle du Tetris: titre, genre, salle et "
            "jour/mois contrôlés. Année absente si date=null: corroboration "
            "indépendante nécessaire. Début du concert inconnu; programmation "
            "et statut à revérifier avant approbation."
        ),
        "officialDetailFound": True, "localTime": None,
        "reviewRequired": True, "publicationAllowed": False,
    }
