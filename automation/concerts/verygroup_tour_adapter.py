#!/usr/bin/env python3
"""Découverte prudente des tournées Verygroup (Mass Hysteria / Psykup).

Une ligne de calendrier est seulement une piste privée. Refus des dates
incomplètes, étrangères explicites, festivals et autres artistes.
Aucun horaire, support, pays, GPS ou approbation n'est déduit de la page.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import re
import unicodedata
from html.parser import HTMLParser

ARTISTS = {
    "mass-hysteria": ("Mass Hysteria", "https://verygroup.fr/verycords/artists/mass-hysteria/"),
    "psykup": ("Psykup", "https://verygroup.fr/veryshow/artists/psykup/"),
}
MONTHS = {
    "janv": 1, "janvier": 1, "fevr": 2, "fevrier": 2, "mars": 3,
    "avr": 4, "avril": 4, "mai": 5, "juin": 6, "juil": 7,
    "juillet": 7, "aout": 8, "sept": 9, "septembre": 9,
    "oct": 10, "octobre": 10, "nov": 11, "novembre": 11,
    "dec": 12, "decembre": 12,
}
# Une commune française sans code de département ne peut être admise
# qu'après identification explicite. Étendre cette liste après preuve.
VERIFIED_FRENCH_CITIES = {
    "angoulins sur mer", "morlaix", "vaureal", "strasbourg",
    "lons le saunier", "montpellier", "toulon", "chateaurenard",
    "rennes", "caen", "savigny le temple", "bethune",
    "vitry le francois", "annecy", "toulouse",
}
DAY_NAME = re.compile(r"^(?:lun|mar|mer|jeu|ven|sam|dim)\.?\s*(\d{1,2})$", re.I)
DAY_WORD = re.compile(r"^(?:lun|mar|mer|jeu|ven|sam|dim)\.?$", re.I)
MONTH_YEAR = re.compile(r"^([\wÀ-ÿ]+)\.?\s+(20\d{2})$", re.I)
CITY_DEPT = re.compile(r"^(.+?)\s*\((\d{2}|2A|2B|97[1-6])\)$", re.I)
EXCLUDED_VENUE = re.compile(r"\b(?:festival|fest|open.air)\b", re.I)
CTA = {"reserver", "complet", "annule", "reporte", "billetterie", "tickets"}


def norm(value):
    txt = unicodedata.normalize("NFKD", str(value or "").casefold())
    txt = txt.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", txt)).strip()


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

    def handle_data(self, value):
        if not self.hidden:
            for segment in value.splitlines():
                text = " ".join(segment.split())
                if text:
                    self.tokens.append(text)


def parse_date_at(words, index):
    """Jour et mois/année dans 2 à 4 tokens HTML consécutifs."""
    if index >= len(words):
        return None
    match = DAY_NAME.fullmatch(words[index])
    if match:
        day, offset = int(match.group(1)), 1
    elif DAY_WORD.fullmatch(words[index]) and index + 1 < len(words) and re.fullmatch(r"\d{1,2}", words[index + 1]):
        day, offset = int(words[index + 1]), 2
    else:
        return None
    if index + offset >= len(words):
        return None
    month_match = MONTH_YEAR.fullmatch(words[index + offset])
    if month_match:
        month_text, year = month_match.groups()
        offset += 1
    elif index + offset + 1 < len(words):
        month_text = words[index + offset].rstrip(".")
        year = words[index + offset + 1]
        if not re.fullmatch(r"20\d{2}", year):
            return None
        offset += 2
    else:
        return None
    month = MONTHS.get(norm(month_text))
    if not month:
        return None
    try:
        return dt.date(int(year), month, day), index + offset
    except ValueError:
        return None


def city_name(raw):
    raw = " ".join(raw.split()).strip()
    match = CITY_DEPT.fullmatch(raw)
    if match:
        city = match.group(1).strip()
        # Les numéros français d'outre-mer peuvent avoir trois chiffres.
        if 2 <= len(city) <= 85:
            return city
        return None
    # Refuser explicitement (BE), (NL), etc., sans inférer un pays.
    if re.search(r"\([A-Za-z]{2,3}\)", raw):
        return None
    return raw if norm(raw) in VERIFIED_FRENCH_CITIES else None


def listings(html, artist, today):
    parser = VisibleTokens()
    parser.feed(html)
    words = parser.tokens
    target = norm(artist)
    if target not in {norm(x) for x in words[:100]}:
        return []
    start = next((i for i, item in enumerate(words)
                  if norm(item) == "en tournee"), None)
    if start is None:
        return []
    stop = next((i for i in range(start + 1, len(words))
                 if norm(words[i]) in ("videos", "dates passees", "actualites")),
                len(words))
    rows, seen = [], set()
    for i in range(start + 1, stop):
        parsed = parse_date_at(words, i)
        if not parsed:
            continue
        date, after = parsed
        if date < today:
            continue
        # N'accepter que le couple ville/salle suivant la date, dans ce bloc.
        # Éviter d'absorber la date suivante en cas de lieu manquant.
        next_date = next((j for j in range(after, min(stop, after + 8))
                          if parse_date_at(words, j)), min(stop, after + 8))
        for j in range(after, next_date - 1):
            city = city_name(words[j])
            if not city:
                continue
            venue = re.sub(r"(?i)\s+r[eé]server\s*$", "", words[j + 1]).strip()
            if (not 2 <= len(venue) <= 100 or norm(venue) in CTA
                    or norm(venue) == target or EXCLUDED_VENUE.search(venue)
                    or parse_date_at(words, j + 1)):
                continue
            key = (date.isoformat(), norm(city), norm(venue))
            if key not in seen:
                seen.add(key)
                rows.append((date.isoformat(), city, venue))
            break
    return rows[:80]


def candidates(html, source, artist, catalogue, today):
    aid = source.get("artistId")
    if (aid not in ARTISTS
            or source.get("url") != ARTISTS[aid][1]
            or norm(artist) != norm(ARTISTS[aid][0])
            or source.get("adapter") != "verygroup_official_tour"
            or source.get("sourceRole") != "promoter_official"):
        raise ValueError("Source Verygroup non autorisée")
    venues = {
        (norm(v["name"]), norm(v["city"])): v["id"]
        for v in catalogue.get("venues", [])
        if isinstance(v, dict) and v.get("id") and v.get("name") and v.get("city")
    }
    result = []
    for date, city, venue in listings(html, artist, today):
        known_id = venues.get((norm(venue), norm(city)))
        raw = "|".join((aid, date, norm(city), norm(venue)))
        result.append({
            "candidateId": "artist-tour:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24],
            "source": "promoter_official_tour",
            "sourceRole": "promoter_official",
            "artistId": aid,
            "sourceUrl": source["url"],
            "sourcePage": source["url"],
            "date": date, "name": artist, "leadArtist": artist,
            "city": city, "venue": venue,
            "venueIdIfKnown": known_id, "newVenueToReview": known_id is None,
            "venueAddressToVerify": True, "coordinatesToVerify": True,
            "countryToVerify": True, "countryVerifiedFromOfficialListing": False,
            "genreToConfirm": True, "lineupToConfirm": True,
            "classification": [],
            "sourceConfidence": "date et salle sur la fiche du tourneur ; confirmation indépendante requise",
            "publicationAllowed": False, "reviewRequired": True,
        })
    return result
