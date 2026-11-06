#!/usr/bin/env python3
"""Extraction prudente des dates françaises de la tournée officielle de Marillion.

Cette page établit uniquement des pistes privées, sans adresse, première partie,
heure de scène ou statut de billetterie publié automatiquement.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import re
from html.parser import HTMLParser

import discover
import livenation_tour_adapter

MONTHS = {name: i for i, name in enumerate(
    ("January", "February", "March", "April", "May", "June",
     "July", "August", "September", "October", "November", "December"), 1)}
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
            "Saturday", "Sunday")
DATE = re.compile(
    r"^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday) "
    r"(\d{1,2}) "
    r"(January|February|March|April|May|June|July|August|September|October|November|December) "
    r"(20\d\d)$", re.IGNORECASE)


class VisibleTokens(HTMLParser):
    """Conserver les frontières <br> et textes, jamais le JS ou les styles."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tokens = []
        self.ignored = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript"}:
            self.ignored += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript"} and self.ignored:
            self.ignored -= 1

    def handle_data(self, text):
        if self.ignored:
            return
        for line in text.splitlines():
            value = re.sub(r"\s+", " ", line).strip()
            if value:
                self.tokens.append(value)


def parse_weekday_date(value):
    match = DATE.fullmatch(value)
    if not match:
        return None
    weekday, day, month, year = match.groups()
    try:
        answer = dt.date(int(year), MONTHS[month.capitalize()], int(day))
    except (ValueError, KeyError):
        return None
    # Une erreur de jour de semaine signale une source altérée.
    return answer if answer.weekday() == next(
        i for i, name in enumerate(WEEKDAYS) if name.casefold() == weekday.casefold()
    ) else None


def french_dates(page, today):
    parser = VisibleTokens()
    parser.feed(page)
    tokens = parser.tokens
    # Pas d'attribution de données d'une page générique à l'artiste surveillé.
    if not (any("TOUR DATES" in token.upper() for token in tokens[:100])
            and any("MARILLION SHOWS" in token.upper() for token in tokens)):
        return []
    output, seen = [], set()
    for i, token in enumerate(tokens):
        date = parse_weekday_date(token)
        if date is None or date < today:
            continue
        # Structure observée: date complète, puis salle, ville et pays.
        # N'accepte pas Monaco, les pays voisins ou une salle non identifiée.
        details = tokens[i + 1:i + 4]
        if len(details) != 3:
            continue
        venue, city, country = details
        if country.casefold() != "france":
            continue
        if not (2 <= len(venue) <= 120 and 2 <= len(city) <= 90):
            continue
        if any(parse_weekday_date(x) for x in details):
            continue
        if any(re.search(r"(?i)tickets?|sold out|on sale|marillion shows", x)
               for x in (venue, city)):
            continue
        key = (date.isoformat(), discover.norm(venue),
               livenation_tour_adapter.normalized_city(city))
        if key not in seen:
            seen.add(key)
            output.append((date.isoformat(), venue, city))
    return output[:80]


def candidates(page, source, artist, catalogue, day):
    if (source.get("artistId") != "marillion"
            or source.get("sourceRole") != "artist_official"
            or source.get("adapter") != "marillion_official_tour"):
        raise ValueError("Adaptateur réservé aux tournées officielles de Marillion")
    known = {
        (discover.norm(v["name"]), livenation_tour_adapter.normalized_city(v["city"])): v["id"]
        for v in catalogue.get("venues", [])
        if isinstance(v, dict) and v.get("id") and v.get("name") and v.get("city")
    }
    rows = []
    for when, venue, city in french_dates(page, day):
        key = "|".join((source["artistId"], when,
                        discover.norm(city), discover.norm(venue)))
        venue_id = known.get((
            discover.norm(venue), livenation_tour_adapter.normalized_city(city)))
        rows.append({
            "candidateId": "artist-tour:" + hashlib.sha256(
                key.encode("utf-8")).hexdigest()[:24],
            "source": "artist_official_tour_listing",
            "artistId": source["artistId"], "sourceRole": source["sourceRole"],
            "sourceUrl": source["url"], "sourcePage": source["url"],
            "date": when, "name": artist, "leadArtist": artist,
            "city": city, "venue": venue, "venueIdIfKnown": venue_id,
            "newVenueToReview": venue_id is None,
            "countryVerifiedFromOfficialListing": True,
            "venueAddressToVerify": True, "coordinatesToVerify": True,
            "genreToConfirm": True, "lineupToConfirm": True,
            "classification": [],
            "sourceConfidence":
                "jour de semaine, date, salle, ville et France indiqués sur tournée officielle",
            "publicationAllowed": False, "reviewRequired": True,
        })
    return rows
