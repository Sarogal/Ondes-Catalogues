#!/usr/bin/env python3
"""Découverte privée des concerts Tagada Jones depuis son calendrier officiel.

Date, département et salle sont des indices de tournée, jamais une preuve de
pays, de GPS, d'horaire, de plateau ni une autorisation de publication.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import re
from html.parser import HTMLParser

import discover
import livenation_tour_adapter

DATE = re.compile(r"^(\d{2})\.(\d{2})\.(20\d{2})$")
HEADING = re.compile(r"^dates?\s+20\d{2}\s*[-–—]\s*20\d{2}$", re.I)
# Départements métropolitains et DOM explicitement indiqués. L'indicatif
# administratif reste une piste : le pays doit être vérifié séparément.
PLACE = re.compile(
    r"^([A-Za-zÀ-ÿ][^()\n\d|]{1,85}?)\s*"
    r"\((0[1-9]|[1-8]\d|9[0-5]|2A|2B|97[1-6])\)\s*"
    r"[-–—]\s*(.{2,100})$", re.I
)
FESTIVAL = re.compile(r"\bfestival\b|\bopen[\s-]?air\b|\b[\w-]*fest\b", re.I)
CTA = re.compile(r"\s+(?:tickets?|billetterie|r[eé]server|complet)\s*$", re.I)


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
        if self.hidden:
            return
        for line in data.splitlines():
            value = " ".join(line.split())
            if value:
                self.tokens.append(value)


def parse_date(text):
    match = DATE.fullmatch(str(text).strip())
    if not match:
        return None
    day, month, year = map(int, match.groups())
    try:
        return dt.date(year, month, day)
    except ValueError:
        return None


def official_tour_entries(page, today):
    """Requiert titre artiste, rubrique datée et couple ville/département/salle.

    Le couplage se fait dans une fenêtre de sept nœuds HTML, sans traverser
    une date suivante. Les festivals, pays non explicites et lieux ambigus
    ne sont jamais convertis en fiches publiables.
    """
    parser = VisibleTokens()
    parser.feed(page)
    tokens = parser.tokens
    heading = next((i for i, item in enumerate(tokens)
                    if HEADING.fullmatch(item)), None)
    if heading is None or not any(discover.norm(t) == discover.norm("Tagada Jones")
                                  for t in tokens[:heading]):
        return []
    results, seen = [], set()
    for i in range(heading + 1, len(tokens)):
        date = parse_date(tokens[i])
        if date is None or date < today:
            continue
        listing = None
        for start in range(i + 1, min(i + 8, len(tokens))):
            if parse_date(tokens[start]) is not None:
                break
            for width in (1, 2, 3):
                chunk = tokens[start:start + width]
                if len(chunk) < width or any(parse_date(t) for t in chunk):
                    break
                found = PLACE.fullmatch(" ".join(chunk))
                if found:
                    city, department, venue = found.groups()
                    venue = CTA.sub("", venue).strip()
                    if (FESTIVAL.search(venue) or
                            not 2 <= len(city.strip()) <= 85 or
                            not 2 <= len(venue) <= 90 or
                            DATE.search(venue)):
                        continue
                    listing = (date.isoformat(), city.strip(), venue, department)
                    break
            if listing:
                break
        if listing:
            key = (listing[0], discover.norm(listing[1]), discover.norm(listing[2]))
            if key not in seen:
                seen.add(key)
                results.append(listing)
    return results[:100]


def candidates(page, source, artist, catalogue, today):
    if (source.get("artistId") != "tagada-jones" or
            source.get("sourceRole") != "artist_official" or
            source.get("adapter") != "tagada_jones_official_tour" or
            source.get("url") != "https://www.tagadajones.com/new/"):
        raise ValueError("Adaptateur réservé à l'agenda officiel Tagada Jones")
    known = {(discover.norm(v.get("name")),
              livenation_tour_adapter.normalized_city(v.get("city"))): v.get("id")
             for v in catalogue.get("venues", [])
             if isinstance(v, dict) and v.get("id") and v.get("name") and v.get("city")}
    results = []
    for date, city, venue, department in official_tour_entries(page, today):
        venue_id = known.get((discover.norm(venue),
                              livenation_tour_adapter.normalized_city(city)))
        key = "|".join((source["artistId"], date, discover.norm(city),
                        discover.norm(venue)))
        results.append({
            "candidateId": "artist-tour:" + hashlib.sha256(
                key.encode("utf-8")).hexdigest()[:24],
            "source": "artist_official_tour_listing",
            "sourceRole": "artist_official",
            "sourceUrl": source["url"], "sourcePage": source["url"],
            "artistId": source["artistId"], "leadArtist": artist,
            "name": artist, "date": date, "city": city, "venue": venue,
            "reportedDepartment": department,
            "venueIdIfKnown": venue_id, "newVenueToReview": venue_id is None,
            "countryToVerify": True, "cityToVerify": True,
            "venueAddressToVerify": True, "coordinatesToVerify": True,
            "genreToConfirm": True, "lineupToConfirm": True,
            "classification": [],
            "sourceConfidence": "date, département et lieu sur calendrier officiel; commune exacte, pays, salle et plateau à recouper",
            "publicationAllowed": False, "reviewRequired": True,
        })
    return results
