#!/usr/bin/env python3
"""Pistes privées Howlin' Jaws depuis l'agence officielle Radical Production.

Échec fermé : uniquement dates complètes dans le bloc "Dates à venir",
villes françaises nommément vérifiées, lieu explicite et artiste de la page.
Aucune géolocalisation, support de tournée ou horaire publiable par cet outil.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import re
import unicodedata
from html.parser import HTMLParser

import discover
import livenation_tour_adapter

MONTHS = {
    "janv": 1, "fevr": 2, "mars": 3, "avr": 4, "mai": 5,
    "juin": 6, "juil": 7, "aout": 8, "sept": 9, "oct": 10,
    "nov": 11, "dec": 12,
}
# La page de l'agence ne précise pas le pays pour chaque ville de France.
# Villes recensées et vérifiées indépendamment. Les autres sont mises en
# attente jusqu'à extension humaine documentée, pas inférées du contexte.
KNOWN_FRENCH_CITIES = {
    "roubaix", "paris", "lyon", "nantes", "brest", "rennes", "angers",
    "penmarc h", "saint etienne", "aix en provence", "strasbourg", "nancy",
}
DAY = re.compile(r"^(\d{1,2})\s+([\wÀ-ÿ]+)\.?\s+(20\d{2})$", re.I)
EXCLUDED_PLACE = re.compile(r"\b(?:festival|fest|open air)\b", re.I)


def norm(value):
    s = unicodedata.normalize("NFKD", str(value or "").casefold())
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ",
        s.encode("ascii", "ignore").decode())).strip()


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
        if not self.hidden:
            value = " ".join(data.split())
            if value:
                self.items.append(value)



def page_shape(html):
    """Diagnostic borné du HTML reçu en CI, sans publier son contenu."""
    parser = VisibleTokens()
    parser.feed(html)
    tokens = parser.items
    normalized = [norm(x) for x in tokens]
    return {
        "htmlChars": len(html),
        "visibleTokens": len(tokens),
        "artistTitleFound": "howlin jaws" in normalized[:35],
        "concertsHeadingFound": "concerts" in normalized,
        "upcomingHeadingFound": "dates a venir" in normalized,
        "pastHeadingFound": "dates passees" in normalized,
        "completeDateTokens": sum(parse_date(x) is not None for x in tokens),
    }


def parse_date(label):
    m = DAY.fullmatch(str(label).strip())
    if not m:
        return None
    dd, mo, yy = m.groups()
    month = MONTHS.get(norm(mo))
    if month is None:
        return None
    try:
        return dt.date(int(yy), month, int(dd))
    except ValueError:
        return None


def french_listings(html, today):
    parser = VisibleTokens()
    parser.feed(html)
    words = parser.items
    # Un article ou une page générique du producteur ne peut devenir source
    # du groupe par simple reprise du nom dans un titre.
    if not any(norm(t) == "howlin jaws" for t in words[:35]):
        return []
    start = next((i for i,t in enumerate(words)
                  if norm(t) == "dates a venir"), None)
    if start is None or not any(norm(t) == "concerts" for t in words[:start]):
        return []
    stop = next((i for i in range(start+1,len(words))
                 if norm(words[i]) == "dates passees"), len(words))
    items = words[start+1:stop]
    result, seen = [], set()
    for i in range(len(items)):
        # Le HTML réel de Radical sépare parfois le jour, le mois et
        # l'année en plusieurs noeuds. Réassembler au plus trois fragments
        # *consécutifs*, puis exiger une date complète valide. Ne jamais
        # inférer une année ou traverser une date incomplète.
        matched = None
        for parts in (1, 2, 3):
            if i + parts + 1 >= len(items):
                continue
            day = parse_date(" ".join(items[i:i+parts]))
            if day is not None:
                matched = (day, parts)
                break
        if matched is None:
            continue
        day, parts = matched
        if day < today:
            continue
        city, venue = items[i+parts:i+parts+2]
        # Certains rendus de la page concatènent le lien CTA au nom de la
        # salle sous forme de texte « Marché Gare Réserver ». Le CTA ne fait
        # jamais partie du nom de la salle.
        venue = re.sub(r"(?i)\s+r[eé]server\s*$", "", venue).strip()
        if norm(city) not in KNOWN_FRENCH_CITIES:
            continue
        if (not 2 <= len(venue) <= 100 or not 2 <= len(city) <= 90
                or EXCLUDED_PLACE.search(venue)
                or parse_date(venue) is not None
                or norm(venue) in ("reserver", "complet", "annule", "reporte")):
            continue
        key = (day.isoformat(), norm(city), norm(venue))
        if key not in seen:
            seen.add(key)
            result.append((day.isoformat(), city, venue))
    return result[:80]


def candidates(html, source, artist, catalogue, today):
    if (source.get("artistId") != "howlin-jaws"
            or source.get("sourceRole") != "promoter_official"
            or source.get("adapter") != "howlin_jaws_radical_tour"):
        raise ValueError("Adaptateur réservé à Radical Production / Howlin' Jaws")
    known = {
        (discover.norm(v["name"]), livenation_tour_adapter.normalized_city(v["city"])): v["id"]
        for v in catalogue.get("venues", [])
        if isinstance(v,dict) and v.get("id") and v.get("name") and v.get("city")
    }
    result = []
    for day, city, venue in french_listings(html, today):
        venue_id = known.get(
            (discover.norm(venue), livenation_tour_adapter.normalized_city(city)))
        key = "|".join(("howlin-jaws",day,discover.norm(city),discover.norm(venue)))
        result.append({
            "candidateId": "artist-tour:" + hashlib.sha256(
                key.encode("utf-8")).hexdigest()[:24],
            "source": "promoter_official_tour",
            "sourceRole": "promoter_official",
            "artistId": "howlin-jaws",
            "sourceUrl": source["url"],
            "sourcePage": source["url"],
            "date": day, "name": artist, "leadArtist": artist,
            "city": city, "venue": venue, "venueIdIfKnown": venue_id,
            "newVenueToReview": venue_id is None,
            "venueAddressToVerify": True, "coordinatesToVerify": True,
            "countryToVerify": True,
            "countryVerifiedFromOfficialListing": False,
            "genreToConfirm": True, "lineupToConfirm": True,
            "classification": [],
            "sourceConfidence":
                "date complète, salle et ville sur l'agenda de l'agence officielle; pays, genres et groupes invités à confirmer",
            "publicationAllowed": False,
            "reviewRequired": True,
        })
    return result
