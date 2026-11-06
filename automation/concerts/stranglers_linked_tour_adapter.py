#!/usr/bin/env python3
"""Officially linked The Stranglers France 2026 campaign: discovery only.

The band's 2026 tour announcement links to https://tix.to/TheStranglers_France26.
This supplies a separate technical intake if the band site is unreachable,
not independent proof for concert publication.
"""
from __future__ import annotations

import datetime as dt
import hashlib
from html.parser import HTMLParser
import re

import discover
import livenation_tour_adapter

URL = "https://tix.to/TheStranglers_France26"
HEADER = "THE STRANGLERS - France 2026"
ITEM = re.compile(r"(?<!\d)(\d{2})\s+(Nov|Dec)\s+(.+?)\s+(?:Billets|Tickets)\b",
                  re.I | re.S)

# Venue names, dates and location labels are exactly those published on the
# official ticket campaign. Any changed row blocks this entire batch.
SHOWS = (
    ("2026-11-20", "SUPERFORME - L'OASIS", "Le Mans (72)", "Le Mans"),
    ("2026-11-21", "CAP CAVAL", "Penmarc'h (29)", "Penmarc'h"),
    ("2026-11-23", "LA CARRIÈRE", "Saint-Herblain (44)", "Saint-Herblain"),
    ("2026-11-24", "ROCHER DE PALMER", "Cenon (33)", "Cenon"),
    ("2026-11-26", "LE BIKINI", "Toulouse (31)", "Toulouse"),
    ("2026-11-27", "ZINGA ZANGA", "Béziers (34)", "Béziers"),
    ("2026-11-28", "6 MIC", "Aix-En-Provence (13)", "Aix-en-Provence"),
    ("2026-11-30", "LE TRANSBORDEUR", "Lyon-Villeurbanne (69)", "Villeurbanne"),
    ("2026-12-01", "ESPACE CROUZY", "Boisseuil (87)", "Boisseuil"),
    ("2026-12-03", "LE FORUM", "Vauréal (95)", "Vauréal"),
    ("2026-12-04", "Le Zéphyr", "HEM (59)", "Hem"),
)


class Visible(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocked = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "noscript", "style", "svg"):
            self.blocked += 1

    def handle_endtag(self, tag):
        if tag in ("script", "noscript", "style", "svg") and self.blocked:
            self.blocked -= 1

    def handle_data(self, value):
        if not self.blocked:
            text = " ".join(value.split())
            if text:
                self.parts.append(text)


def official_shows(body, today):
    p = Visible()
    p.feed(body)
    text = " ".join(p.parts)
    if (HEADER not in text or "Upcoming shows" not in text
            or text.index(HEADER) > text.index("Upcoming shows")):
        return []
    rows = ITEM.findall(text)
    if len(rows) != len(SHOWS):
        return []
    results = []
    for observed, expected in zip(rows, SHOWS):
        day, month, details = observed
        date, venue, place, city = expected
        try:
            actual = dt.date(2026, 11 if month.lower() == "nov" else 12, int(day))
        except ValueError:
            return []
        if (actual.isoformat() != date
                or discover.norm(details) != discover.norm(venue + " " + place)):
            return []
        if actual >= today:
            results.append((date, venue, place, city))
    return results


def candidates(body, source, artist, catalogue, today):
    if (source.get("artistId") != "the-stranglers"
            or source.get("url") != URL
            or source.get("sourceRole") != "artist_official"
            or discover.norm(artist) != "thestranglers"):
        raise ValueError("Source de tournée Stranglers non autorisée")
    venues = {(discover.norm(v.get("name")),
               livenation_tour_adapter.normalized_city(v.get("city"))): v["id"]
              for v in catalogue.get("venues", [])
              if isinstance(v, dict) and v.get("id")
              and v.get("name") and v.get("city")}
    output = []
    for date, venue, location, city in official_shows(body, today):
        # The city supplied by the campaign is a PROMOTIONAL city label,
        # not an approved venue location or a source of GPS coordinates.
        key = "|".join(("the-stranglers", date, discover.norm(city),
                        discover.norm(venue)))
        mapped = venues.get((discover.norm(venue),
                             livenation_tour_adapter.normalized_city(city)))
        output.append({
            "candidateId": "artist-tour:" + hashlib.sha256(key.encode()).hexdigest()[:24],
            "artistId": "the-stranglers",
            "source": "artist_official_tour_listing",
            "sourceRole": "artist_official",
            "sourceUrl": URL, "sourcePage": URL,
            "name": artist, "leadArtist": artist,
            "date": date, "venue": venue, "city": city,
            "reportedLocation": location,
            "venueIdIfKnown": mapped, "newVenueToReview": mapped is None,
            "countryToVerify": True, "venueAddressToVerify": True,
            "coordinatesToVerify": True, "genreToConfirm": True,
            "lineupToConfirm": True, "classification": [],
            "sourceConfidence": "Campagne billetterie liée par le site officiel "
                                "du groupe; date et ville indicatives; validation "
                                "indépendante de la salle obligatoire",
            "publicationAllowed": False, "reviewRequired": True,
        })
    return output
