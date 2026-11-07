"""Bounded, source-specific discovery of Totems family events on Pacé's official site.

Links from the city's agenda are only hints. Every candidate must be supported
by a fresh, exact first-party detail showing title, day, year, start time,
child suitability and the known Totems venue. No public output or patch.
"""
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
import re
import unicodedata
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo
from ptitesondes_place_agenda_curated import time_value, times_written

INDEX_ID = "pace-totems-official-agenda"
DETAIL_PATH = re.compile(r"/evenement/[a-z0-9]+(?:-[a-z0-9]+)*/")
MONTHS = ("janvier", "fevrier", "mars", "avril", "mai", "juin",
          "juillet", "aout", "septembre", "octobre", "novembre", "decembre")
WEEKDAYS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
CHILD_TITLES = ("bebes lecteurs", "histoires du mercredi", "la bobine des enfants",
                "la bobine du samedi", "les histoires de mauricette",
                "eveil musical", "les petits singuliers", "petites histoires",
                "ludo", "conte pour enfants", "atelier enfants")
MAX_DETAILS_PER_CYCLE = 6


def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", s).split())


def detail_url(base, link):
    if not isinstance(link, str) or len(link) > 400:
        return None
    url = urljoin(base, link)
    p = urlparse(url)
    if (p.scheme != "https" or p.hostname != "www.ville-pace.bzh"
            or p.username or p.password or p.port or p.query or p.fragment
            or not DETAIL_PATH.fullmatch(p.path)):
        return None
    return url


class AgendaLinks(HTMLParser):
    IGNORE = {"header", "nav", "footer", "script", "style", "noscript", "svg"}
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.href = None
        self.text = []
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag in self.IGNORE:
            self.hidden += 1
        if tag == "a" and not self.hidden:
            self.href = dict(attrs).get("href")
            self.text = []

    def handle_endtag(self, tag):
        if tag == "a" and self.href is not None:
            self.links.append((self.href, " ".join(" ".join(self.text).split())))
            self.href = None
            self.text = []
        if tag in self.IGNORE and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if self.href is not None and not self.hidden:
            self.text.append(data)


class DetailText(HTMLParser):
    IGNORE = {"header", "nav", "footer", "script", "style", "noscript", "svg"}
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.h1_depth = 0
        self.title_parts = []
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in self.IGNORE:
            self.hidden += 1
        if tag == "h1" and not self.hidden:
            self.h1_depth += 1

    def handle_endtag(self, tag):
        if tag == "h1" and not self.hidden:
            self.h1_depth = max(self.h1_depth - 1, 0)
        if tag in self.IGNORE and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden and data.strip():
            self.parts.append(data)
            if self.h1_depth:
                self.title_parts.append(data)

    @property
    def title(self):
        return " ".join(" ".join(self.title_parts).split())


def find_index_hints(index_url, html, today):
    if not isinstance(html, str) or len(html.encode("utf-8")) > 300_000:
        return []
    p = AgendaLinks()
    p.feed(html)
    found = {}
    for link, label in p.links:
        title = norm(label)
        if not any(needle in title for needle in CHILD_TITLES):
            continue
        url = detail_url(index_url, link)
        if url:
            found[url] = title
    # Deterministic rolling coverage, maximum six pages per day.
    ordered = sorted(found)
    if not ordered:
        return []
    shift = today.toordinal() % len(ordered)
    return (ordered[shift:] + ordered[:shift])[:MAX_DETAILS_PER_CYCLE]


def child_age_proven(body):
    return bool(
        re.search(r"\b\d{1,2}\s+mois\s+a\s+\d{1,2}\s+ans\b", body)
        or re.search(r"\b(?:a partir de|des)\s+\d{1,2}\s+ans\b", body)
        or re.search(r"\bde\s+\d{1,2}(?:\s+ans?)?\s+a\s+\d{1,2}\s+ans\b", body)
        or re.search(r"\benfants?\s+(?:de|a partir de)\s+\d{1,2}\s+ans\b", body)
    )


def detail_candidates(source, detail_url_value, html, today):
    if detail_url(source["url"], detail_url_value) != detail_url_value:
        return []
    if not isinstance(html, str) or len(html.encode("utf-8")) > 300_000:
        return []
    doc = DetailText()
    doc.feed(html)
    title = doc.title
    if not 5 <= len(title) <= 130:
        return []
    content = " ".join(" ".join(doc.parts).split())
    body = norm(content)
    # Both institution name and exact physical address must be part of this
    # individual event, not merely the agenda index or navigation.
    if not all(term in body for term in (
            "totems", "12 chemin de la metairie", "35740 pace")):
        return []
    if not child_age_proven(body):
        return []
    if any(x in norm(title + " " + content) for x in
           ("annule", "reporte", "complet", "adulte uniquement")):
        return []
    # Use the actual detail's full-year date, not the index's month label.
    month_words = "|".join(MONTHS)
    official = re.search(
        r"\ble\s+(\d{1,2})\s+(" + month_words + r")\s+(20\d{2})"
        r"\s+(\d{1,2})\s+([0-5]\d)\b", body)
    if not official:
        return []
    d, month, year = int(official.group(1)), MONTHS.index(official.group(2)) + 1, int(official.group(3))
    try:
        day = date(year, month, d)
    except ValueError:
        return []
    if day < today or day > today + timedelta(days=183):
        return []
    # The same detail must explicitly mention its weekday and its start time
    # in prose. A generic exhibition period or hours of opening cannot pass.
    anchor = re.search(
        r"\b(" + "|".join(WEEKDAYS) + r")\s+" + str(d) + r"\s+"
        + MONTHS[month - 1] + r"\s+a\s+(\d{1,2})h(\d{0,2})"
        + r"(?:\s+et\s+a\s+\d{1,2}h\d{0,2})?", norm(content).replace(
            " a ", " à "))
    # Normalize diacritics while preserving the hour separator.
    raw = unicodedata.normalize("NFKD", content.lower())
    raw = "".join(c for c in raw if not unicodedata.combining(c))
    anchor = re.search(
        r"\b(" + "|".join(WEEKDAYS) + r")\s+" + str(d) + r"\s+"
        + MONTHS[month - 1] + r"\s+(a\s+\d{1,2}h\d{0,2}"
        r"(?:\s+et\s+a\s+\d{1,2}h\d{0,2})?)", raw)
    if not anchor or day.weekday() != WEEKDAYS.index(anchor.group(1)):
        return []
    sessions = times_written(anchor.group(2))
    if not sessions:
        return []
    listed_start = time_value(official.group(4), official.group(5))
    if listed_start != sessions[0]:
        return []
    result = []
    for clock in sessions[:3]:
        stamp = datetime.combine(day, datetime.strptime(clock, "%H:%M").time(),
                                 tzinfo=ZoneInfo("Europe/Paris"))
        result.append({
            "place_id": source["place_id"], "name": title,
            "start": stamp.isoformat(timespec="minutes"),
            "end": None, "source_url": detail_url_value,
            "status": "requires_independent_session_proof",
            "age_evidence": "âge présent dans la fiche officielle",
            "extraction": "pace_official_event_detail_v1",
        })
    return result


def pace_agenda_leads(source, html, today, getter):
    if source.get("id") != INDEX_ID:
        return []
    leads = []
    for link in find_index_hints(source["url"], html, today):
        try:
            detail_html = getter(link)
            leads.extend(detail_candidates(source, link, detail_html, today))
        except (OSError, ValueError, TypeError, UnicodeError):
            # A single stale or unavailable detail must not block the index.
            continue
    return leads
