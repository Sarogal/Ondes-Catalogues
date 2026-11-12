#!/usr/bin/env python3
"""Independent first-party Molotov event-detail verifier (no listing heuristics).

Only the genuine Le Molotov venue (not nearby Le Dodu) is supported. Dates,
full heading, explicitly named artists, and explicit genre must agree with
discovery and the public artist/venue registry. No automatic new identities.
"""
from __future__ import annotations

import datetime as dt
from html.parser import HTMLParser
import re
from urllib.parse import urlsplit

from official_recheck import norm, slug, GENRES, BANNED, artist_names

HOST = "lemolotov.com"
VENUE = "le-molotov-marseille"
MONTHS = {
    "jan": 1, "fev": 2, "mar": 3, "avr": 4, "mai": 5, "jun": 6,
    "jul": 7, "aou": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12
}
# Genre labels in the HTML must be explicit; broad venue descriptions are ignored.
ALLOWED = GENRES | {"alt metal", "melodic death metal", "modern metal",
                    "blackened hardcore", "post punk", "street punk",
                    "punk hxc", "grunge", "progressive metal", "groove metal",
                    "post hardcore"}



UNANNOUNCED_SUPPORT = frozenset({
    "guest", "guests", "special guest", "special guests", "invite",
    "invite surprise", "artiste surprise",
    "premiere partie", "1ere partie", "1re partie", "support",
    "a confirmer", "tba", "surprise",
})
PARTIAL_STRUCTURE = "molotov-first-party-bill-with-unannounced-support"


def confirmed_bill(title):
    """Keep only named artists, and omit an exact trailing guest placeholder."""
    # Only a + separator may introduce an unknown guest, never a text
    # fragment of a band's proper name. This is NOT a generic title cleaner.
    parts = [x.strip() for x in re.split(r"\s+\+\s+", title)]
    unknown = norm(parts[-1]) if len(parts) >= 2 else None
    if unknown in UNANNOUNCED_SUPPORT:
        named = parts[:-1]
        if (not 1 <= len(named) <= 4
                or len({norm(x) for x in named}) != len(named)
                or any(len(norm(x)) < 3 or BANNED.search(norm(x))
                       for x in named)):
            raise ValueError("Affiche principale invalide ou invitée ambiguë")
        # Canonical singular proof label keeps the publishing policy strict.
        return named, "guest" if unknown in {"guests", "special guests"} else unknown
    # Retain the established strict path for fully named official bills.
    return artist_names(title), None


class Headings(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.article = 0
        self.collect = None
        self.depth = 0
        self.text_parts = []
        self.div_ids = []
        self.scopes = []
        self.current_scope = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "article":
            self.article += 1
        if not self.article:
            return
        if tag == "div":
            self.div_ids.append(attrs.get("id"))
        if self.collect and tag in ("br", "hr", "img", "input"):
            self.text_parts.append(" ")
        elif self.collect:
            self.depth += 1
        elif tag in ("h1", "h2", "h3", "h4"):
            self.collect = tag
            self.depth = 1
            self.text_parts = []
            self.current_scope = (
                "entry-title" if tag == "h1" and
                "entry-title" in attrs.get("class", "").split()
                else "event-card" if tag == "h1" and
                "eveCardsolo" in self.div_ids and "eveName" in self.div_ids
                else None
            )

    def handle_endtag(self, tag):
        if self.collect:
            self.depth -= 1
            if self.depth == 0:
                self.rows.append((self.collect, " ".join(" ".join(self.text_parts).split())))
                self.scopes.append(self.current_scope)
                self.collect = None
                self.current_scope = None
                self.text_parts = []
        if tag == "div" and self.article and self.div_ids:
            self.div_ids.pop()
        if tag == "article":
            self.article = max(0, self.article - 1)

    def handle_data(self, data):
        if self.collect:
            self.text_parts.append(data)


def parse_detail(page):
    parser = Headings()
    parser.feed(page)
    rows = parser.rows
    title_at = [(n, text) for n, (tag, text) in enumerate(rows) if tag == "h1" and text]
    if len(title_at) == 1:
        pos, title = title_at[0]
    elif (len(title_at) == 2
          and parser.scopes[title_at[0][0]] == "entry-title"
          and parser.scopes[title_at[1][0]] == "event-card"
          and norm(title_at[0][1]) == norm(title_at[1][1])):
        # The live Molotov WordPress template repeats ONE identical title in
        # the article header and inside #eveCardsolo > #eveName.
        # Select the card title so the complete date/address precede it.
        pos, title = title_at[1]
    else:
        raise ValueError("Une seule affiche officielle détaillée est nécessaire")
    before = rows[:pos]
    # Require exactly one date and the venue and street address in detail
    days = [v for k, v in before if k == "h2" and re.fullmatch(r"\d{1,2}", v)]
    months = [norm(v) for k, v in before if k == "h3" and norm(v) in MONTHS]
    years = [v for k, v in before if k == "h3" and re.fullmatch(r"20\d\d", v)]
    if len(days) != 1 or len(months) != 1 or len(years) != 1:
        raise ValueError("Date complète absente ou ambiguë")
    date = dt.date(int(years[0]), MONTHS[months[0]], int(days[0])).isoformat()
    locations = [norm(v) for k, v in before if k == "h4"]
    if locations.count("le molotov") != 1 or not any("3 place paul cezanne" in x for x in locations):
        raise ValueError("Le lieu n'est pas précisément Le Molotov")
    after = rows[pos + 1:]
    if not after or after[0][0] != "h2":
        raise ValueError("Genres officiels absents")
    genre_labels = [x.strip() for x in after[0][1].split(",") if x.strip()]
    if not ({norm(g) for g in genre_labels} & ALLOWED):
        raise ValueError("Aucun genre métal ou punk explicite")
    return {"title": title, "date": date, "genres": genre_labels,
            "genreTags": {norm(g) for g in genre_labels}}


def verify(candidate, page, catalogue, today):
    if candidate.get("source") != "agenda_officiel_molotov_genre":
        raise ValueError("Source officielle Molotov requise")
    if candidate.get("reviewBucket") != "genre_tag_review" or candidate.get("possibleExistingConcert"):
        raise ValueError("Doublon ou piste nécessitant une vérification distincte")
    if candidate.get("publicationAllowed") is not False or candidate.get("reviewRequired") is not True:
        raise ValueError("Candidat non isolé par la veille")
    if candidate.get("venue") != "Le Molotov" or norm(candidate.get("city")) != "marseille":
        raise ValueError("Le lieu est différent de Le Molotov")
    url = candidate.get("sourceUrl") or ""
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != HOST or not re.fullmatch(r"/events/[^/]+/?", parsed.path):
        raise ValueError("Page événement individuelle officielle obligatoire")
    detail = parse_detail(page)
    if norm(detail["title"]) != norm(candidate.get("name")):
        raise ValueError("Affiche incohérente entre la veille et la page officielle")
    if detail["date"] != candidate.get("date") or dt.date.fromisoformat(detail["date"]) <= today:
        raise ValueError("Date modifiée, passée ou imminente")
    if not (detail["genreTags"] & {norm(g) for g in candidate.get("classification") or []}):
        raise ValueError("Genres contradictoires")
    parts, unannounced = confirmed_bill(detail["title"])
    artists_by_norm = {}
    for artist in catalogue.get("artists", []):
        artists_by_norm.setdefault(norm(artist["name"]), []).append(artist["id"])
    ids = []
    for name in parts:
        match = artists_by_norm.get(norm(name), [])
        if len(match) != 1:
            raise ValueError("Artiste absent ou ambigu dans le catalogue")
        ids.append(match[0])
    if len(set(ids)) != len(ids):
        raise ValueError("Identités d'artistes en collision")
    venues = {v["id"]: v for v in catalogue.get("venues", [])}
    if VENUE not in venues or norm(venues[VENUE].get("city")) != "marseille":
        raise ValueError("Salle absente ou incohérente du catalogue")
    for event in catalogue.get("events", []):
        if event.get("date") == detail["date"] and event.get("venueId") == VENUE:
            if set(event.get("artistIds", [])) & set(ids):
                raise ValueError("Concert déjà référencé sur la même scène et même date")
    event_id = "go-c-" + detail["date"].replace("-", "") + "-marseille-" + slug(parts[0])
    if any(e["id"] == event_id for e in catalogue.get("events", [])):
        raise ValueError("Identifiant d'événement déjà utilisé")
    proof = {
        "url": url, "proofType": "official-organizer-or-venue",
        "checkedAt": today.isoformat(),
        "checkedFields": ["artists", "date", "venue", "genre"],
        "notes": "Fiche individuelle officielle Molotov : titre, date, salle et genres vérifiés.",
    }
    if unannounced:
        proof.update({
            "officialArtistNames": [next(a["name"] for a in catalogue["artists"]
                                         if a["id"] == artist_id) for artist_id in ids],
            "sourceStructure": PARTIAL_STRUCTURE,
            "unannouncedSupportLabel": unannounced,
        })
    return {
        "reviewDecision": "approved", "reviewedBy": "automated-official-recheck",
        "reviewedAt": today.isoformat(),
        "officialEvidence": [proof],
        "event": {"id": event_id, "title": " + ".join(proof["officialArtistNames"]) if unannounced else detail["title"],
                  "date": detail["date"], "time": None,
                  "artistIds": ids, "venueId": VENUE,
                  "genres": detail["genres"], "status": "confirmed",
                  "officialUrl": url, "sourceType": "salle",
                  "organizer": "Le Molotov"},
        "newArtists": []
    }
