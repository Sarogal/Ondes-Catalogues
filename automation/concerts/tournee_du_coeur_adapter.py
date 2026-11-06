#!/usr/bin/env python3
"""Découverte prudente depuis l'agenda officiel « La Tournée du Cœur III ».

Aucune attribution automatique des trois artistes du plateau, d'horaire
musical, de GPS ou de pays. Les dates sans lieu sont toujours rejetées.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import re
from html.parser import HTMLParser

import discover
import livenation_tour_adapter

URL = "https://tourneeducoeur.ragetour.com/"
DATE = re.compile(r"^(\d{2})/(\d{2})/(20\d{2})$")
PLACE = re.compile(
    r"^([A-Za-zÀ-ÿ][^()\n]{1,90}?)\s*"
    r"\((0[1-9]|[1-8]\d|9[0-5]|2A|2B|97[1-6])\)\s*"
    r"[-–—]\s*(.{2,110})$", re.I
)
# Aucun festival ne doit entrer automatiquement dans le calendrier Concerts.
FESTIVAL = re.compile(
    r"\bfestival\b|\bfest(?:if|ival)?\b|rock d[’']hiver|"
    r"les feux de l[’']été", re.I
)


class VisibleTokens(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.items = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if self.hidden:
            return
        for part in data.splitlines():
            value = " ".join(part.split())
            if value:
                self.items.append(value)


def parse_date(token):
    match = DATE.fullmatch(str(token).strip())
    if not match:
        return None
    day, month, year = map(int, match.groups())
    try:
        return dt.date(year, month, day)
    except ValueError:
        return None


def official_entries(page, today):
    parser = VisibleTokens()
    parser.feed(page)
    items = parser.items
    # Échec fermé en absence d'un programme de tournée daté et structuré.
    if sum(parse_date(t) is not None for t in items) < 2:
        return []
    seen, rows = set(), []
    for i, token in enumerate(items):
        day = parse_date(token)
        if day is None or day < today:
            continue
        # La salle doit suivre immédiatement la date (pas de rapprochement
        # entre plusieurs événements ou depuis un autre bloc).
        if i + 1 >= len(items):
            continue
        matched = PLACE.fullmatch(items[i + 1])
        if not matched:
            continue
        city, department, venue = matched.groups()
        city, venue = city.strip(), venue.strip()
        if (FESTIVAL.search(venue) or
                not 2 <= len(city) <= 90 or
                not 2 <= len(venue) <= 110 or
                parse_date(venue) is not None):
            continue
        key = (day.isoformat(), discover.norm(city), discover.norm(venue))
        if key not in seen:
            seen.add(key)
            rows.append((day.isoformat(), city, venue, department))
    return rows[:100]


def candidates(page, source, artist, catalogue, today):
    if (source.get("artistId") != "cachemire"
            or source.get("sourceRole") != "promoter_official"
            or source.get("adapter") != "tournee_du_coeur_official_2027"
            or source.get("url") != URL):
        raise ValueError("Source non reconnue pour La Tournée du Cœur")
    known = {
        (discover.norm(v.get("name")),
         livenation_tour_adapter.normalized_city(v.get("city"))): v.get("id")
        for v in catalogue.get("venues", [])
        if isinstance(v, dict) and v.get("id") and v.get("name") and v.get("city")
    }
    results = []
    for day, city, venue, dep in official_entries(page, today):
        venue_id = known.get((discover.norm(venue),
                              livenation_tour_adapter.normalized_city(city)))
        key = "|".join(("cachemire", day, discover.norm(city), discover.norm(venue)))
        results.append({
            "candidateId": "artist-tour:" + hashlib.sha256(
                key.encode("utf-8")).hexdigest()[:24],
            "source": "promoter_official_tour",
            "sourceRole": "promoter_official",
            "artistId": "cachemire", "leadArtist": artist, "name": artist,
            "sourceUrl": URL, "sourcePage": URL, "date": day,
            "city": city, "venue": venue, "reportedDepartment": dep,
            "venueIdIfKnown": venue_id,
            "newVenueToReview": venue_id is None,
            "countryToVerify": True, "cityToVerify": True,
            "venueAddressToVerify": True, "coordinatesToVerify": True,
            "genreToConfirm": True, "lineupToConfirm": True,
            "classification": [],
            "sourceConfidence":
                "agenda du tourneur officiel; pays, commune précise, "
                "plateau, salle et informations pratiques à recouper",
            "publicationAllowed": False, "reviewRequired": True,
        })
    return results
