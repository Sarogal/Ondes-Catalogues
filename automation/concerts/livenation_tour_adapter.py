"""Adaptateur prudent des fiches de tournée Live Nation France.

La page d'artiste sert exclusivement à découvrir des liens /event/... du même
hôte. Une fiche individuelle doit présenter une année complète, l'artiste,
une salle et une ville. Le pays demeure à vérifier et interdit toute publication.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import html
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import discover
import triage

MONTHS = {
    "janv": 1, "janvier": 1, "fevr": 2, "fevrier": 2,
    "mars": 3, "avr": 4, "avril": 4, "mai": 5, "juin": 6,
    "juil": 7, "juillet": 7, "aout": 8, "sept": 9, "septembre": 9,
    "oct": 10, "octobre": 10, "nov": 11, "novembre": 11,
    "dec": 12, "decembre": 12,
}

DATE = __import__("re").compile(
    r"\b(?:lun|mar|mer|jeu|ven|sam|dim)\.?[, ]*\s*"
    r"(?P<day>\d{1,2})\s+"
    r"(?P<month>janv|janvier|fevr|fevrier|mars|avr|avril|mai|juin|"
    r"juil|juillet|aout|sept|septembre|oct|octobre|nov|novembre|dec|decembre)"
    r"\.?\s+(?P<year>20\d{2})\b", __import__("re").I
)


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.links = []
        self._blocked = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ("script", "style", "noscript"):
            self._blocked += 1
        if tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self._blocked:
            self._blocked -= 1

    def handle_data(self, data):
        value = html.unescape(data).strip()
        if not self._blocked and value:
            self.parts.append(value)



def normalized_city(value):
    """Rapproche uniquement les abréviations françaises courantes de villes.

    Ne fusionne pas les noms de salles et ne fait aucune géolocalisation.
    """
    tokens = triage.words(value).split()
    aliases = {"st": "saint", "ste": "sainte"}
    return "".join(aliases.get(t, t) for t in tokens)


def date_from_text(value):
    norm = triage.words(value)
    match = DATE.search(norm)
    if match is None:
        return None
    month = MONTHS.get(match.group("month"))
    if month is None:
        return None
    try:
        return dt.date(int(match.group("year")), month, int(match.group("day")))
    except ValueError:
        return None


def event_links(html_page, url, prefix):
    """N'accepte que les fiches événement de l'artiste sur le même domaine."""
    if not isinstance(prefix, str) or not prefix.startswith("/event/"):
        raise ValueError("Préfixe des fiches officielles non conforme")
    parser = Page()
    parser.feed(html_page)
    found = set()
    for href in parser.links:
        link = urljoin(url, href).split("#")[0]
        if discover.same_host(link, url) and urlsplit(link).path.casefold().startswith(prefix.casefold()):
            found.add(link)
    return sorted(found)


def detail_candidate(html_page, detail_url, source, artist, catalogue, day):
    page = Page()
    page.feed(html_page)
    parts = page.parts[:200]
    text = " ".join(parts)
    date = date_from_text(text)
    if date is None or date < day:
        return None
    # Le titre annonce l'artiste surveillé. Une première partie ou une affiche
    # voisine sur la page ne peuvent pas être prises pour le groupe principal.
    target = triage.words(artist)
    header = " ".join(triage.words(x) for x in parts[:15])
    if not target or not __import__("re").search(
            r"(?<!\w)" + __import__("re").escape(target) + r"(?!\w)", header):
        return None

    # La fiche détail donne « Aeronef, » suivi de « Lille » dans une ligne
    # distincte. Aucun découpage arbitraire d'un nom de salle/ville.
    location = None
    for i, part in enumerate(parts[:45]):
        if not date_from_text(part):
            continue
        for j in range(i + 1, min(i + 13, len(parts) - 1)):
            raw = parts[j].strip()
            if not raw.endswith(","):
                continue
            venue = raw[:-1].strip()
            city = parts[j + 1].strip().strip(",")
            if (2 <= len(venue) <= 100 and 2 <= len(city) <= 60 and
                    not any(x in triage.words(venue) for x in ("billet", "tickets", "artiste")) and
                    not any(char.isdigit() for char in city)):
                location = (venue, city)
                break
        if location:
            break
    if location is None:
        # Variante HTML où lieu et ville partagent le même noeud.
        for i, part in enumerate(parts[:45]):
            if not date_from_text(part):
                continue
            for raw in parts[i + 1:i + 12]:
                if ", " in raw and len(raw) <= 140:
                    venue, city = raw.split(", ", 1)
                    if (2 <= len(venue) <= 100 and 2 <= len(city) <= 60
                            and not any(char.isdigit() for char in city)):
                        location = venue.strip(), city.strip()
                        break
            if location:
                break
    if location is None:
        return None
    venue, city = location
    if triage.words(city) in {triage.words(x) for x in source.get("excludedCities", [])}:
        return None
    # Ne pas inférer FR depuis le TLD du tourneur : cet agenda peut annoncer
    # des lieux en Belgique/Luxembourg. L'appartenance à la France reste à
    # contrôler et interdit de considérer cette piste comme confirmée.
    key = "|".join((source["artistId"], date.isoformat(),
                    discover.norm(city), discover.norm(venue)))
    cid = "artist-tour:" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
    mapped = {(
        discover.norm(v.get("name")), normalized_city(v.get("city"))): v.get("id")
        for v in catalogue.get("venues", [])
        if isinstance(v, dict) and v.get("name") and v.get("city")
    }.get((discover.norm(venue), normalized_city(city)))
    return {
        "candidateId": cid, "artistId": source["artistId"],
        "source": "promoter_official_tour_detail",
        "sourceRole": "promoter_official", "sourceUrl": detail_url,
        "sourcePage": source["url"], "eventDetailUrl": detail_url,
        "date": date.isoformat(), "name": artist, "leadArtist": artist,
        "venue": venue, "city": city,
        "venueIdIfKnown": mapped, "newVenueToReview": mapped is None,
        "venueAddressToVerify": True, "coordinatesToVerify": True,
        "countryToVerify": True,
        "classification": [], "genreToConfirm": True, "lineupToConfirm": True,
        "sourceConfidence": "fiche individuelle du tourneur ; pays, genre et plateau à confirmer",
        "publicationAllowed": False, "reviewRequired": True,
    }
