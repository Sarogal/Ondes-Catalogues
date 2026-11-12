#!/usr/bin/env python3
"""Conservative second-read verifier for individual Bateau Ivre concerts.

The existing discovery adapter is NOT publication evidence. Recheck a fresh
first-party event page and require exact, separately displayed musician
headings for unknown artists. Never turn a support placeholder into an artist.
Door/billet times are never promoted to the musical starting time.
"""
from __future__ import annotations

import datetime as dt
from html.parser import HTMLParser
import re

import bateau_ivre_adapter as adapter

SOURCE = "bateau_ivre_official_detail_review"
VENUE = "le-bateau-ivre-tours"
STRUCTURE = "bateau-ivre-first-party-named-artist-sections"
UNKNOWN = frozenset({
    "guest", "guests", "special guest", "special guests", "invite",
    "invite surprise", "premiere partie", "1ere partie", "1re partie",
    "support", "a confirmer", "tba", "surprise",
})
BAD_NAMES = re.compile(
    r"\b(?:festival|annule|annulation|reporte|reportee|"
    r"postponed|cancelled|tribute|hommage|cover)\b"
)
ALLOWED_GENRES = {
    "rock", "punk", "metal", "grunge", "shoegaze", "stoner", "sludge",
    "doom", "post rock", "post punk", "hardcore", "noise rock",
    "garage rock", "hard rock", "ska punk",
}


def normalized(name):
    return " ".join(re.findall(r"[a-z0-9]+", adapter.fold(name)))


class EventSections(HTMLParser):
    """Only the single official article, never WordPress related-event links."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_article = False
        self.count = 0
        self.status_ok = False
        self.collect = None
        self.buffer = []
        self.h1 = []
        self.named_sections = []
        self.intro_parts = []
        self.in_biography_sections = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "article":
            self.count += 1
            self.in_article = self.count == 1
            self.status_ok = self.status_ok or (
                "status-publish" in attrs.get("class", "").split() and
                "events" in attrs.get("class", "").split()
            )
        if not self.in_article or self.count != 1:
            return
        if tag == "h2" and "wp-block-heading" in attrs.get("class", "").split():
            self.in_biography_sections = True
        if self.collect and tag == "br":
            self.buffer.append(" ")
        elif self.collect is None and tag in ("h1", "h2"):
            self.collect = (tag, attrs.get("class", "").split())
            self.buffer = []

    def handle_data(self, data):
        if self.in_article and not self.in_biography_sections:
            self.intro_parts.append(data)
        if self.in_article and self.collect is not None:
            self.buffer.append(data)

    def handle_endtag(self, tag):
        if self.in_article and self.collect and tag == self.collect[0]:
            label, classes = self.collect
            name = " ".join(" ".join(self.buffer).split())
            if name:
                if label == "h1":
                    self.h1.append(name)
                elif set(classes) & {"wp-block-heading", "wp-block-post-title"}:
                    self.named_sections.append(name)
            self.collect = None
            self.buffer = []
        if tag == "article" and self.in_article:
            self.in_article = False


def exact_names(fresh, page):
    doc = EventSections()
    doc.feed(page)
    if (doc.count != 1 or not doc.status_ok or len(doc.h1) not in (1, 2)
            or len({normalized(x) for x in doc.h1}) != 1):
        raise ValueError("Bateau Ivre : un événement officiel publié et unique exigé")
    title = fresh.get("name", "")
    names = [x.strip() for x in re.split(r"\s+\+\s+", title)]
    if not 1 <= len(names) <= 4:
        raise ValueError("Bateau Ivre : plateau non délimité avec certitude")
    known = [normalized(x) for x in names]
    if (any(len(n) < 3 or n in UNKNOWN or BAD_NAMES.search(n)
            for n in known) or len(set(known)) != len(known)):
        raise ValueError("Bateau Ivre : noms d'artistes ambigus")
    # Original header may name only the headliner, while the official H2
    # subtitle and body artist sections document the supporting artists.
    if normalized(doc.h1[0]) not in (known[0], normalized(title)):
        raise ValueError("Bateau Ivre : tête d'affiche non concordante")
    sections = {normalized(x.lstrip("+ ").strip()) for x in doc.named_sections}
    # The genre must be described before individual artist biographies,
    # not in adjacent recommendations or a later unrelated act section.
    intro = adapter.fold(" ".join(doc.intro_parts))[:7000]
    if not adapter.GENRE.search(intro):
        raise ValueError("Bateau Ivre : genre pertinent absent de l'affiche")
    for support in known[1:]:
        if support not in sections:
            raise ValueError("Bateau Ivre : première partie non corroborée dans sa section")
    return names, sections


def verify(candidate, page, catalogue, today):
    if not isinstance(today, dt.date) or not isinstance(candidate, dict):
        raise ValueError("Bateau Ivre : entrée de vérification invalide")
    if (candidate.get("source") != SOURCE
            or candidate.get("reviewBucket") != "genre_tag_review"
            or candidate.get("possibleExistingConcert") is not False
            or candidate.get("reviewRequired") is not True
            or candidate.get("publicationAllowed") is not False
            or candidate.get("officialDetailFound") is not True):
        raise ValueError("Bateau Ivre : candidat non qualifié ou doublon")
    if (candidate.get("venue") != "Le Bateau Ivre"
            or candidate.get("city") != "Tours"
            or str(candidate.get("department")) != "37"
            or candidate.get("sourcePage") not in
                (adapter.CURRENT, adapter.ARCHIVE)):
        raise ValueError("Bateau Ivre : identité du lieu non confirmée")
    url = candidate.get("sourceUrl", "")
    if not isinstance(url, str) or adapter.normalize_detail(url) != url:
        raise ValueError("Bateau Ivre : URL individuelle officielle exigée")
    if not isinstance(page, str) or not 50 <= len(page) <= 500_000:
        raise ValueError("Bateau Ivre : page officielle absente ou illisible")
    for field in ("artists", "venues", "events"):
        if not isinstance(catalogue.get(field), list):
            raise ValueError("Bateau Ivre : catalogue inattendu")

    original = {"name": "Le Bateau Ivre", "city": "Tours",
                "department": "37", "url": candidate["sourcePage"]}
    fresh = adapter.candidate(page, url, original, today.isoformat())
    for key in ("sourceUrl", "source", "date", "name", "venue", "city",
                "department", "classification", "firstPartyNamedSupport"):
        if fresh.get(key) != candidate.get(key):
            raise ValueError("Bateau Ivre : changement officiel détecté: " + key)
    if dt.date.fromisoformat(fresh["date"]) <= today:
        raise ValueError("Bateau Ivre : date passée")
    genres = [normalized(x) for x in fresh["classification"]]
    if len(genres) != 1 or genres[0] not in ALLOWED_GENRES:
        raise ValueError("Bateau Ivre : genre insuffisamment explicite")
    names, sections = exact_names(fresh, page)
    matches = [v for v in catalogue["venues"] if v.get("id") == VENUE]
    if len(matches) != 1 or adapter.fold(matches[0].get("city")) != "tours":
        raise ValueError("Bateau Ivre : salle publique inexistante")
    if not all(matches[0].get(k) is not None for k in ("latitude", "longitude")):
        raise ValueError("Bateau Ivre : coordonnées non certifiées")

    existing = {}
    aliases = set()
    reserved = set()
    for artist in catalogue["artists"]:
        reserved.add(artist["id"])
        existing.setdefault(normalized(artist.get("name")), []).append(artist)
        aliases.update(normalized(x) for x in (artist.get("aliases") or [])
                       if isinstance(x, str))
    ids, new = [], []
    for name in names:
        key = normalized(name)
        found = existing.get(key, [])
        if len(found) > 1:
            raise ValueError("Bateau Ivre : identité d'artiste ambiguë")
        if found:
            ident = found[0]["id"]
        else:
            # A new identity needs its OWN explicit event article heading:
            # a description mentioning a band is not evidence for adding it.
            if key not in sections:
                raise ValueError("Bateau Ivre : artiste nouveau sans section nominative")
            if key in aliases:
                raise ValueError("Bateau Ivre : artiste déjà connu sous un alias")
            ident = key.replace(" ", "-")[:90].strip("-")
            if len(ident) < 3 or ident in reserved:
                raise ValueError("Bateau Ivre : nouvel identifiant en collision")
            new.append({"id": ident, "name": name})
            reserved.add(ident)
        ids.append(ident)
    if len(new) > 3 or len(set(ids)) != len(ids):
        raise ValueError("Bateau Ivre : trop de nouveaux artistes ou identités répétées")
    for e in catalogue["events"]:
        if (e.get("officialUrl") == url or
                (e.get("date") == fresh["date"] and e.get("venueId") == VENUE
                 and set(e.get("artistIds", [])) & set(ids))):
            raise ValueError("Bateau Ivre : concert déjà référencé")
    event_id = "go-c-" + fresh["date"].replace("-", "") + "-tours-" + ids[0]
    if len(event_id) > 150 or any(e.get("id") == event_id
                                    for e in catalogue["events"]):
        raise ValueError("Bateau Ivre : identifiant déjà enregistré")

    return {
        "reviewDecision": "approved",
        "reviewedBy": "automated-official-recheck",
        "reviewedAt": today.isoformat(),
        "officialEvidence": [{
            "url": url, "proofType": "official-organizer-or-venue",
            "checkedAt": today.isoformat(),
            "checkedFields": ["artists", "date", "venue", "genre"],
            "sourceStructure": STRUCTURE,
            "sourcePage": candidate["sourcePage"],
            "officialArtistNames": names,
            "verifiedNewArtists": [x["name"] for x in new],
            "notes": "Relecture d'une fiche individuelle du Bateau Ivre ; artistes nommés en en-tête et sections, date, salle, genre, début musical non établi.",
        }],
        "event": {
            "id": event_id, "title": " + ".join(names),
            "date": fresh["date"], "time": None, "artistIds": ids,
            "venueId": VENUE, "genres": fresh["classification"],
            "status": "confirmed", "officialUrl": url,
            "sourceType": "salle", "organizer": "Le Bateau Ivre",
        },
        "newArtists": new,
    }
