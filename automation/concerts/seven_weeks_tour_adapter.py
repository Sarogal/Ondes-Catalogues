#!/usr/bin/env python3
"""Découverte limitée des dates complètes du calendrier officiel de 7WEEKS.

Ne fabrique jamais de première partie, d'heure ou de pays de concert. Les
fiches de tournée sont uniquement des pistes, jamais des approbations.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import html
import re
from html.parser import HTMLParser

import discover
import livenation_tour_adapter
import triage

DATE = re.compile(r"(?<!\d)(\d{2})/(\d{2})/(20\d{2}|\d{2})(?!\d)")
# Le site français utilise JOUR/MOIS/ANNÉE (pas le site anglais mois/jour).
FULL_DATE = re.compile(r"^\s*(\d{2})/(\d{2})/(\d{2})\s*$")
PLACE = re.compile(r"^\s*(.{2,85}?)\s+[–—]\s+(.{2,110}?)\s*$")


class TextTokens(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tokens: list[str] = []
        self.blocked = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript"}:
            self.blocked += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript"} and self.blocked:
            self.blocked -= 1

    def handle_data(self, value):
        if self.blocked:
            return
        for chunk in html.unescape(value).splitlines():
            chunk = re.sub(r"\s+", " ", chunk).strip()
            if chunk:
                self.tokens.append(chunk)


def parse_date(token: str) -> dt.date | None:
    match = FULL_DATE.fullmatch(token)
    if match is None:
        return None
    d, m, y = map(int, match.groups())
    try:
        return dt.date(2000 + y, m, d)
    except ValueError:
        return None


def official_tour_entries(page: str, day: dt.date):
    """Couples date/lieu strictement voisins, pas d'association inter-section."""
    parser = TextTokens()
    parser.feed(page)
    tokens = parser.tokens
    # Le corps doit vraiment être la page TOUR officielle et non un billet RSS.
    if not any(token.upper() == "TOUR" for token in tokens[:70]):
        return []
    collected, seen = [], set()
    for i, token in enumerate(tokens):
        date = parse_date(token)
        if date is None or date < day:
            continue
        # La structure officielle est « date » immédiatement suivie du lieu.
        # Tolérer au plus deux étiquettes intercalées, pas une autre date.
        next_parts = tokens[i + 1:i + 4]
        valid_place = None
        for part in next_parts:
            if DATE.search(part):
                break
            match = PLACE.fullmatch(part)
            if match:
                city, venue = (field.strip() for field in match.groups())
                if (re.search(r"\d{4}", city) or re.search(r"\d{4}", venue)
                        or city.casefold() in {"billets", "tickets"}
                        or venue.casefold() in {"billets", "tickets"}):
                    break
                valid_place = (city, venue)
                break
        if valid_place is None:
            continue
        city, venue = valid_place
        key = (date.isoformat(), discover.norm(city), discover.norm(venue))
        if key not in seen:
            seen.add(key)
            collected.append((date.isoformat(), city, venue))
    return collected[:100]


def candidates(page, source, artist, catalogue, day):
    if (source.get("sourceRole") != "artist_official" or
            source.get("artistId") != "7weeks"):
        raise ValueError("Adaptateur 7WEEKS réservé à sa source officielle")
    known = {(discover.norm(v.get("name")), livenation_tour_adapter.normalized_city(v.get("city"))): v.get("id")
             for v in catalogue.get("venues", [])
             if isinstance(v, dict) and v.get("name") and v.get("city")}
    results = []
    for date, city, venue in official_tour_entries(page, day):
        event_key = "|".join((source["artistId"], date, discover.norm(city),
                              discover.norm(venue)))
        cid = "artist-tour:" + hashlib.sha256(event_key.encode("utf-8")).hexdigest()[:24]
        venue_id = known.get((discover.norm(venue), livenation_tour_adapter.normalized_city(city)))
        results.append({
            "candidateId": cid, "artistId": source["artistId"],
            "source": "artist_official_tour_listing",
            "sourceRole": "artist_official", "sourceUrl": source["url"],
            "sourcePage": source["url"],
            "date": date, "name": artist, "leadArtist": artist,
            "venue": venue, "city": city,
            "venueIdIfKnown": venue_id, "newVenueToReview": venue_id is None,
            "countryToVerify": True, "venueAddressToVerify": True,
            "coordinatesToVerify": True, "genreToConfirm": True,
            "lineupToConfirm": True,
            "classification": [],
            "sourceConfidence": "date complète et lieu sur tournée officielle; pays, genre et plateau à revérifier",
            "publicationAllowed": False, "reviewRequired": True,
        })
    return results
