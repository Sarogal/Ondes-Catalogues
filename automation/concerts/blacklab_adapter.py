"""The Black Lab (Wasquehal) official concert-page discovery, review ONLY.

The site uses The Events Calendar: many current-year cards omit the year.
A complete year on an individual official detail is mandatory. Event clocks
represent a venue schedule, not a documented concert start time.
"""
from __future__ import annotations

import datetime as dt
from html import unescape
from html.parser import HTMLParser
import re
import unicodedata
from urllib.parse import urljoin, urlsplit


HOST = "theblacklab.fr"
AGENDA = "https://theblacklab.fr/agenda/"
PATH = re.compile(r"^/agenda/([a-z0-9][a-z0-9-]{2,140})/?$")
RESERVED = {
    "liste", "mois", "semaine", "jour", "aujourdhui",
    "categorie", "today", "tag", "venue", "organizer",
}
MONTHS = {
    "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4,
    "mai": 5, "juin": 6, "juillet": 7, "aout": 8,
    "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12,
}
DATE = re.compile(
    r"\b(\d{1,2})(?:er)?\s+(janvier|fevrier|mars|avril|mai|juin|"
    r"juillet|aout|septembre|octobre|novembre|decembre)\s+(20\d{2})\b"
)
GENRE = re.compile(
    r"(?<![a-z])(?:metal|hardcore|punk|stoner|sludge|doom|thrash|"
    r"grind|deathcore|metalcore|post[- ]punk|hard[- ]rock|"
    r"rock psych[eé]d[eé]lique|grunge|noise rock)(?![a-z])"
)
CANCEL = re.compile(
    r"\b(?:annule|annulee|reporte|reportee|deplace|deplacee|"
    r"cancelled|canceled|postponed|cancel|report)\b"
)


def fold(text):
    return unicodedata.normalize(
        "NFKD", unescape(str(text)).casefold()
    ).encode("ascii", "ignore").decode("ascii")


def official_slug(url):
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname != HOST or
            parsed.query or parsed.fragment or parsed.port or
            parsed.username or parsed.password):
        return None
    match = PATH.fullmatch(parsed.path)
    return match[1] if match and match[1] not in RESERVED else None


class _Parse(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.parts = []
        self.heading_parts = []
        self.heading_end = None
        self.in_h1 = False
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in ("head", "script", "style", "nav", "footer"):
            self.hidden += 1
        if tag == "a":
            for name, value in attrs:
                if name.lower() == "href" and value:
                    self.links.append(value)
        if tag == "h1" and not self.hidden and self.heading_end is None:
            self.in_h1 = True

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "h1" and self.in_h1:
            self.in_h1 = False
            self.heading_end = len(self.parts)
        if tag in ("head", "script", "style", "nav", "footer") and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if self.hidden:
            return
        value = " ".join(data.split())
        if value:
            self.parts.append(value)
            if self.in_h1:
                self.heading_parts.append(value)


def detail_urls(html, listing_url):
    parsed = urlsplit(listing_url)
    if (parsed.scheme != "https" or parsed.hostname != HOST or
            parsed.path.rstrip("/") not in ("/agenda", "/agenda/liste",
                                          "/agenda/liste/page/2")):
        raise ValueError("Official Black Lab agenda required")
    parser = _Parse()
    parser.feed(html)
    return sorted({
        u for link in parser.links
        if (u := urljoin(listing_url, link)) and official_slug(u)
    })


def detail_candidate(html, url, source, today):
    slug = official_slug(url)
    if slug is None:
        raise ValueError("Not an official individual event")
    if re.match(r"^(?:reporte|reportee|annule|annulee|cancelled|canceled|postponed|deplace)-", slug):
        raise ValueError("Historic postponed/cancelled event slug: manual review required")
    if source.get("name") != "The Black Lab" or source.get("city") != "Wasquehal":
        raise ValueError("Unexpected concert venue")
    day = dt.date.fromisoformat(today)
    p = _Parse()
    p.feed(html)
    if p.heading_end is None or not p.heading_parts:
        raise ValueError("No first-party event title")
    title = " ".join(p.heading_parts).strip()
    after = p.parts[p.heading_end:]
    if not 3 <= len(title) <= 190 or not after:
        raise ValueError("No individual event content")
    # Usually the event date is the first paragraph below <h1>; we allow
    # a few fragmented text nodes, but never accept a biography's date.
    intro = fold(" ".join(after[:4]))
    matches = DATE.findall(intro)
    if len(matches) != 1:
        raise ValueError("Official individual event year is missing or ambiguous")
    date_label = matches[0]
    try:
        when = dt.date(
            int(date_label[2]), MONTHS[date_label[1]], int(date_label[0]))
    except ValueError:
        raise ValueError("Invalid first-party concert date") from None
    if not day <= when <= day + dt.timedelta(days=365):
        raise ValueError("Out-of-range concert")
    if CANCEL.search(fold(title + " " + " ".join(after[:3]))):
        raise ValueError("Cancelled or postponed event")
    # Official event page descriptions carry musical tags, unlike calendar
    # cards. A genre term in the early description is a REVIEW LEAD, not
    # conclusive proof for automatic publication.
    introduction = fold(" ".join(after[1:16]))[:2800]
    matched = GENRE.search(introduction)
    if not matched:
        raise ValueError("No relevant musical genre in event description")
    if re.search(r"\b(?:dj set|tribe|techno party)\b", fold(title)):
        raise ValueError("DJ party or non-gig program")
    lead = re.split(r"\s+\+\s+", title, maxsplit=1)[0].strip()
    return {
        "candidateId": f"blacklab:{when.isoformat()}:{slug}",
        "date": when.isoformat(), "name": title, "leadArtist": lead,
        "venue": "The Black Lab", "city": "Wasquehal", "department": "59",
        "classification": [matched.group(0)],
        "genreEvidence": "official_event_description_review",
        "genreToConfirm": True,
        "source": "agenda_officiel_blacklab_detail_review",
        "sourcePage": source["url"], "sourceUrl": url,
        "sourceConfidence": (
            "Fiche officielle Black Lab avec année et date explicites, "
            "programmation nommée et indice de genre dans la description. "
            "L'heure d'accueil de la salle n'est pas une heure de début."),
        "officialDetailFound": True, "localTime": None,
        "publicationAllowed": False, "reviewRequired": True,
        "geoReviewRequired": True,
    }
