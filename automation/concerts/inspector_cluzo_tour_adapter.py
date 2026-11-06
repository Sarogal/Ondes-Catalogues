#!/usr/bin/env python3
"""Calendrier officiel The Inspector Cluzo, uniquement concerts FR datés.

La page présente simultanément des lignes desktop et mobile : ne lire que les
lignes HTML complètes, puis dédoublonner. Festival ou pays non-FR = pas de
nouveau concert. Aucun horaire ou plateau n'est déduit du titre de la tournée.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import html
import re
from html.parser import HTMLParser

import discover
import livenation_tour_adapter

DATE = re.compile(r"^\d{2}-\d{2}-20\d{2}$")
FR = re.compile(r"^FR\s*-\s*(\S.{1,90})$", re.I)
FEST = re.compile(r"(?i)\bfestival\b|\bfest\b|hellfest|bebop|mots zik sous les pins|au pont du rock")


class Rows(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.cells = None
        self.cell = None
        self.blocked = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.blocked += 1
        if self.blocked:
            return
        if tag == "tr":
            self.cells = []
        if tag == "td" and self.cells is not None:
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None and not self.blocked:
            self.cell.append(html.unescape(data))

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self.blocked:
            self.blocked -= 1
            return
        if self.blocked:
            return
        if tag == "td" and self.cells is not None and self.cell is not None:
            self.cells.append(" ".join(" ".join(self.cell).split()))
            self.cell = None
        if tag == "tr" and self.cells is not None:
            self.rows.append(self.cells)
            self.cells = None


def future_fr_shows(body: str, day: dt.date):
    parser = Rows()
    parser.feed(body)
    found = set()
    shows = []
    skipped_festival = 0
    for cells in parser.rows:
        # Desktop : 4 colonnes, les duplications mobile : une seule.
        if len(cells) < 3 or not DATE.fullmatch(cells[0]):
            continue
        try:
            date = dt.datetime.strptime(cells[0], "%d-%m-%Y").date()
        except ValueError:
            continue
        if date < day:
            continue
        fr = FR.fullmatch(cells[1])
        if not fr:
            continue
        city, venue = fr.group(1).strip(), cells[2].strip()
        if not city or len(city) > 90 or len(venue) < 3 or len(venue) > 140:
            continue
        if FEST.search(venue):
            skipped_festival += 1
            continue
        key = (date.isoformat(), discover.norm(city), discover.norm(venue))
        if key not in found:
            found.add(key)
            shows.append((date.isoformat(), city, venue))
    return shows[:100], skipped_festival


def candidates(body, source, artist, catalogue, day):
    if source.get("artistId") != "the-inspector-cluzo" or source.get("sourceRole") != "artist_official":
        raise ValueError("Adaptateur réservé au site officiel de The Inspector Cluzo")
    known = {(discover.norm(v.get("name")), livenation_tour_adapter.normalized_city(v.get("city"))): v.get("id")
             for v in catalogue.get("venues", [])
             if isinstance(v, dict) and v.get("name") and v.get("city")}
    entries, festivals = future_fr_shows(body, day)
    results = []
    for date, city, venue in entries:
        key = "|".join((source["artistId"], date, discover.norm(city),
                        discover.norm(venue)))
        candidate_id = "artist-tour:" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
        known_id = known.get((discover.norm(venue), livenation_tour_adapter.normalized_city(city)))
        results.append({
            "candidateId": candidate_id,
            "artistId": source["artistId"],
            "source": "artist_official_tour_listing",
            "sourceRole": "artist_official",
            "sourceUrl": source["url"], "sourcePage": source["url"],
            "date": date, "name": artist, "leadArtist": artist,
            "venue": venue, "city": city,
            "countryCodeFromOfficial": "FR",
            "venueIdIfKnown": known_id, "newVenueToReview": known_id is None,
            "venueAddressToVerify": True, "coordinatesToVerify": True,
            "genreToConfirm": True, "lineupToConfirm": True,
            "classification": [],
            "sourceConfidence": "ville FR, date, lieu sur agenda officiel; plateau et salle à revérifier",
            "publicationAllowed": False, "reviewRequired": True,
        })
    return results, festivals
