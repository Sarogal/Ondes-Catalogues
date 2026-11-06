#!/usr/bin/env python3
"""Official The Stranglers French 2026 tour: 11 read-only private leads.

Never infer an opening band, start time, GPS, genre or venue identity.
The official announcement has Nov/Dec 2026 in its title/intro, not in
each row; thus exact venue/city pairs are pinned for this particular tour.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import re
from html.parser import HTMLParser

import discover
import livenation_tour_adapter

OFFICIAL = "https://thestranglers.co.uk/the-stranglers-announce-french-tour-2026/"
DATE = re.compile(r"^(\d{2})\s+(Nov|Dec)\s+[–—-]\s*(.+)$", re.I)
SOLD = re.compile(r"(?:\s*[–—-]?\s*SOLD\s+OUT!?\s*)+$", re.I)
# Exact source spelling retained, including "Le Carrière": venue names are
# only reconciled against the catalogue after separate independent review.
TOUR = (
    ("2026-11-20", "LE MANS", "L’Oasis", "Le Mans"),
    ("2026-11-21", "PENMARC’H", "Cap Caval", "Penmarc’h"),
    ("2026-11-23", "SAINT-HERBLAIN (NANTES)", "Le Carrière", "Saint-Herblain"),
    ("2026-11-24", "CENON (BORDEAUX)", "Rocher De Palmer", "Cenon"),
    ("2026-11-26", "RAMONVILLE SAINT-AGNE (TOULOUSE)", "Le Bikini", "Ramonville-Saint-Agne"),
    ("2026-11-27", "BEZIERS", "Zinga Zanga", "Béziers"),
    ("2026-11-28", "AIX-EN-PROVENCE", "6mic", "Aix-en-Provence"),
    ("2026-11-30", "VILLEURBANNE (LYON)", "Le Transbordeur", "Villeurbanne"),
    ("2026-12-01", "BOISSEUIL", "Espace Crouzy", "Boisseuil"),
    ("2026-12-03", "VAUREAL", "Le Forum", "Vauréal"),
    ("2026-12-04", "HEM", "Le Zephyr", "Hem"),
)


class Tokens(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.title = False
        self.paragraph = False
        self.heading = []
        self.parts = []
        self.lines = []

    def flush(self):
        value = " ".join(" ".join(self.parts).split())
        if value:
            self.lines.append(value)
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "svg"):
            self.hidden += 1
        elif not self.hidden:
            if tag == "h1":
                self.title = True
            if tag == "p":
                self.paragraph = True
            if tag == "br" and self.paragraph:
                self.flush()

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg") and self.hidden:
            self.hidden -= 1
        elif not self.hidden:
            if tag == "h1":
                self.title = False
            if tag == "p" and self.paragraph:
                self.flush()
                self.paragraph = False

    def handle_data(self, data):
        if not self.hidden:
            if self.title:
                self.heading.append(data)
            if self.paragraph:
                self.parts.append(data)


def official_shows(body, today):
    doc = Tokens()
    doc.feed(body)
    heading = " ".join(" ".join(doc.heading).split())
    intro = " ".join(doc.lines)
    if (heading != "The Stranglers announce French tour 2026!"
            or not re.search(r"return to France.{0,160}November and December 2026",
                             intro, re.I)):
        return []
    recognized = []
    for line in doc.lines:
        match = DATE.fullmatch(line)
        if match is None:
            continue
        number, month, rest = match.groups()
        text = SOLD.sub("", rest).strip()
        try:
            observed = dt.date(2026, 11 if month.lower() == "nov" else 12, int(number))
        except ValueError:
            return []
        matches = [row for row in TOUR if row[0] == observed.isoformat()
                   and discover.norm(text) == discover.norm(row[1] + " " + row[2])]
        if len(matches) != 1:
            return []
        recognized.append(matches[0])
    if len(recognized) != 11 or len(set(recognized)) != 11:
        return []  # Page changed, so never silently archive a partial tour.
    return [row for row in recognized if row[0] >= today.isoformat()]


def candidates(body, source, artist, catalogue, today):
    if (source.get("artistId") != "the-stranglers"
            or source.get("sourceRole") != "artist_official"
            or source.get("url") != OFFICIAL
            or discover.norm(artist) != "thestranglers"):
        raise ValueError("Source The Stranglers inattendue")
    known = {(discover.norm(v.get("name")),
              livenation_tour_adapter.normalized_city(v.get("city"))): v.get("id")
             for v in catalogue.get("venues", [])
             if isinstance(v, dict) and v.get("name") and v.get("city")}
    result = []
    for date, city_source, venue, city in official_shows(body, today):
        key = "|".join((source["artistId"], date, discover.norm(city),
                        discover.norm(venue)))
        venue_id = known.get((discover.norm(venue),
                              livenation_tour_adapter.normalized_city(city)))
        result.append({
            "candidateId": "artist-tour:" + hashlib.sha256(key.encode()).hexdigest()[:24],
            "artistId": "the-stranglers",
            "source": "artist_official_tour_listing",
            "sourceRole": "artist_official",
            "sourceUrl": OFFICIAL, "sourcePage": OFFICIAL,
            "name": artist, "leadArtist": artist,
            "date": date, "city": city, "venue": venue,
            "reportedCity": city_source,
            "venueIdIfKnown": venue_id, "newVenueToReview": venue_id is None,
            "countryToVerify": True, "venueAddressToVerify": True,
            "coordinatesToVerify": True, "genreToConfirm": True,
            "lineupToConfirm": True, "classification": [],
            "sourceConfidence": "Tournée officielle France 2026 : date et ville; "
                                "salle, accompagnateurs et horaire à recouper",
            "publicationAllowed": False, "reviewRequired": True,
        })
    return result
