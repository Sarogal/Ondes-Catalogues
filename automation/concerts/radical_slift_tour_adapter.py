#!/usr/bin/env python3
"""Pistes de tournée SLIFT depuis Radical Production, sans approbation.

Uniquement l'onglet Dates à venir et des communes françaises explicitement
identifiées. Pas de supposition sur première partie, adresse, pays, GPS,
heure, genre ni publication. Une modification de forme de la page échoue fermé.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import re
import unicodedata
from html.parser import HTMLParser

ARTIST_ID = "slift"
SOURCE_URL = "https://radical-production.fr/artistes/slift/"
MONTHS = {
    "janv": 1, "janvier": 1, "fevr": 2, "fevrier": 2,
    "mars": 3, "avr": 4, "avril": 4, "mai": 5, "juin": 6,
    "juil": 7, "juillet": 7, "aout": 8, "sept": 9,
    "oct": 10, "nov": 11, "dec": 12,
}
# Pays absent des lignes de tournée : seules ces villes françaises
# géographiquement vérifiées sont admissibles en tant que pistes.
FRENCH_CITIES = {
    "toulouse", "la rochelle", "nantes", "rennes", "paris",
    "lyon", "strasbourg", "lille", "biarritz", "le mans",
    "cherbourg", "le havre", "amiens",
}
DATE = re.compile(r"^(\d{1,2})\s+([\wÀ-ÿ]+)\.?\s+(20\d{2})$", re.I)
FOREIGN_COUNTRY = re.compile(r"\((?:[A-Za-z]{2,3})\)")
EXCLUDE_PLACE = re.compile(r"\b(?:festival|fest|open.air)\b", re.I)
SKIP_VENUE = {"reserver", "complet", "annule", "reporte", "billetterie"}


def norm(value):
    value = unicodedata.normalize("NFKD", str(value or "").casefold())
    value = value.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", value)).strip()


class VisibleTokens(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tokens = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden:
            for line in data.splitlines():
                text = " ".join(line.split())
                if text:
                    self.tokens.append(text)


def parse_date(value):
    m = DATE.fullmatch(str(value).strip())
    if not m:
        return None
    day, month, year = m.groups()
    month_num = MONTHS.get(norm(month))
    if not month_num:
        return None
    try:
        return dt.date(int(year), month_num, int(day))
    except ValueError:
        return None


def upcoming(html, today):
    p = VisibleTokens()
    p.feed(html)
    words = p.tokens
    if "slift" not in {norm(w) for w in words[:100]}:
        return []
    concerts = next((i for i, w in enumerate(words)
                     if norm(w) == "concerts"), None)
    start = next((i for i, w in enumerate(words)
                  if norm(w) == "dates a venir" and concerts is not None and i > concerts), None)
    if start is None:
        return []
    stop = next((i for i in range(start + 1, len(words))
                 if norm(words[i]) == "dates passees"), len(words))
    candidates, seen = [], set()
    for i in range(start + 1, stop):
        matched = None
        # 1 à 3 fragments de HTML adjacents pour une date française complète.
        for parts in (1, 2, 3):
            if i + parts > stop:
                continue
            date = parse_date(" ".join(words[i:i + parts]))
            if date:
                matched = (date, i + parts)
                break
        if not matched:
            continue
        date, after = matched
        if date < today:
            continue
        # Le site affiche immédiatement ville puis salle. Un pays étranger
        # ou une ville inconnue reste en attente; aucun raisonnement déductif.
        if after + 1 >= stop:
            continue
        city = words[after].strip()
        venue = re.sub(r"(?i)\s+r[eé]server\s*$", "", words[after + 1]).strip()
        if (FOREIGN_COUNTRY.search(city)
                or norm(city) not in FRENCH_CITIES
                or not 2 <= len(venue) <= 100
                or norm(venue) in SKIP_VENUE
                or EXCLUDE_PLACE.search(venue)
                or parse_date(venue)):
            continue
        key = (date.isoformat(), norm(city), norm(venue))
        if key not in seen:
            seen.add(key)
            candidates.append((date.isoformat(), city, venue))
    return candidates[:80]


def candidates(html, source, artist, catalogue, today):
    if (source.get("artistId") != ARTIST_ID
            or source.get("url") != SOURCE_URL
            or source.get("adapter") != "radical_slift_official_tour"
            or source.get("sourceRole") != "promoter_official"
            or norm(artist) != "slift"):
        raise ValueError("Source SLIFT non officielle ou non autorisée")
    known = {
        (norm(v["name"]), norm(v["city"])): v["id"]
        for v in catalogue.get("venues", [])
        if isinstance(v, dict) and v.get("id") and v.get("name") and v.get("city")
    }
    result = []
    for date, city, venue in upcoming(html, today):
        venue_id = known.get((norm(venue), norm(city)))
        raw = "|".join((ARTIST_ID, date, norm(city), norm(venue)))
        result.append({
            "candidateId": "artist-tour:" + hashlib.sha256(raw.encode()).hexdigest()[:24],
            "source": "promoter_official_tour",
            "sourceRole": "promoter_official",
            "artistId": ARTIST_ID,
            "sourceUrl": SOURCE_URL, "sourcePage": SOURCE_URL,
            "date": date, "name": artist, "leadArtist": artist,
            "city": city, "venue": venue, "venueIdIfKnown": venue_id,
            "newVenueToReview": venue_id is None,
            "venueAddressToVerify": True, "coordinatesToVerify": True,
            "countryToVerify": True, "countryVerifiedFromOfficialListing": False,
            "genreToConfirm": True, "lineupToConfirm": True,
            "classification": [],
            "sourceConfidence": "date et salle de l'agence officielle ; contrôle indépendant du pays, des artistes et horaires requis",
            "publicationAllowed": False, "reviewRequired": True,
        })
    return result
