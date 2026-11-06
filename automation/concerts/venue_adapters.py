"""Adaptateurs légers pour agendas officiels de salles.
Aucune méthode ici n'autorise une publication.
"""
from __future__ import annotations

import datetime as dt
import html
from html.parser import HTMLParser
import re
import urllib.parse

MONTHS = {
    "janvier":1, "fevrier":2, "février":2, "mars":3, "avril":4, "mai":5,
    "juin":6, "juillet":7, "aout":8, "août":8, "septembre":9,
    "octobre":10, "novembre":11, "decembre":12, "décembre":12,
}
GENRE_KEYS = (
    "metal", "hard-rock", "heavy", "stoner", "sludge", "doom", "grind",
    "punk", "deathcore", "metalcore", "black-metal", "death-metal",
)
DATE_PATTERN = re.compile(
    r"\b(?:lun|mar|mer|jeu|ven|sam|dim)\s+(\d{1,2})\s+"
    r"(janvier|fevrier|février|mars|avril|mai|juin|juillet|aout|août|septembre|"
    r"octobre|novembre|decembre|décembre)\s+(\d{4})\s*[-–]\s*"
    r"(\d{1,2})\s*[hH]\s*(\d{2})", re.I
)
GENRES_PATTERN = re.compile(r"\(([\wÀ-ÿ\s|-]+)\)")
EVENT_PATH = re.compile(r"^/fr/programmation/[^/?#]+/?$", re.I)


class RexList(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.parts = []
        self.links = []
        self.rows = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "li":
            if self.depth == 0:
                self.parts, self.links = [], []
            self.depth += 1
        elif self.depth and tag == "a":
            href = attrs.get("href", "")
            if href:
                self.links.append(href)

    def handle_data(self, data):
        if self.depth:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == "li" and self.depth:
            self.depth -= 1
            if self.depth == 0:
                self.rows.append((" ".join(self.parts), self.links[:]))


def normalize_space(value):
    return " ".join(html.unescape(value or "").split())


def is_metal_genre(genre):
    """Rejette par exemple 'hard-techno' et 'hard-bounce'."""
    tokens = [x.strip().lower().replace(" ", "-") for x in genre.split("|")]
    return any(any(key in token for key in GENRE_KEYS) for token in tokens)


def rex_candidates(page, base_url, venue, today):
    """Le Rex Toulouse, programmation server-rendered avec genres explicites."""
    parser = RexList()
    parser.feed(page)
    results = []
    seen = set()
    for content, links in parser.rows:
        line = normalize_space(content)
        found = DATE_PATTERN.search(line)
        if not found:
            continue
        day, month, year, hour, minute = found.groups()
        try:
            event_date = dt.date(int(year), MONTHS[month.lower()], int(day)).isoformat()
        except ValueError:
            continue
        if event_date < today:
            continue
        tail = line[found.end():]
        genre_matches = list(GENRES_PATTERN.finditer(tail))
        match = next((m for m in genre_matches
                      if is_metal_genre(m.group(1))), None)
        if not match:
            continue
        title = tail[:match.start()].strip(" -–•")
        # Les intitulés incomplets ou gigantesques ne doivent pas être intégrés.
        if not title or len(title) > 180:
            continue
        genres = [x.strip() for x in match.group(1).split("|") if x.strip()]
        official_event_url = None
        for href in links:
            u = urllib.parse.urljoin(base_url, href)
            parsed = urllib.parse.urlsplit(u)
            base = urllib.parse.urlsplit(base_url)
            if (parsed.scheme == "https" and parsed.netloc.lower() == base.netloc.lower()
                    and EVENT_PATH.match(parsed.path)):
                official_event_url = u.split("#")[0]
                break
        source_url = official_event_url or base_url
        key = (event_date, title.casefold())
        if key in seen:
            continue
        seen.add(key)
        results.append({
            "candidateId": "rex:" + event_date + ":" +
                           re.sub(r"[^a-z0-9]+", "-", title.casefold())[:80],
            "source": "agenda_officiel_rex_genre",
            "sourceUrl": source_url, "sourcePage": base_url,
            "date": event_date, "localTime": f"{int(hour):02d}:{minute}",
            "name": title, "leadArtist": title,
            "venue": venue["name"], "city": venue["city"],
            "department": venue["department"],
            "classification": genres,
            "genreToConfirm": False,
            "reviewRequired": True, "publicationAllowed": False,
            "sourceConfidence": "Agenda officiel du Rex avec genre ; vérification manuelle requise",
        })
    return results
