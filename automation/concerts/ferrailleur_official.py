#!/usr/bin/env python3
"""Strict individual-event verifier for Le Ferrailleur, Nantes.

First-party detail HTML must corroborate the exact date, all artists,
genres and the stated beginning time. New/ambiguous artists remain in review.
The public cloud must also carry the source-pinned precise venue position.
This module does NOT change the private approvals file by itself.
"""
from __future__ import annotations

import datetime as dt
from html.parser import HTMLParser
import re
from urllib.parse import urlsplit

from official_recheck import norm, slug, artist_names, BANNED

VENUE_ID = "le-ferrailleur-nantes"
HOSTS = {"leferrailleur.fr", "www.leferrailleur.fr"}
MONTHS = dict(zip(
    ("janvier", "fevrier", "mars", "avril", "mai", "juin", "juillet",
     "aout", "septembre", "octobre", "novembre", "decembre"),
    range(1, 13)
))
# Automatic first-party discovery may register at most two new named acts
# per concert. More complex bills stay pending for manual curation.
MAX_NEW_ARTISTS = 2
GENRE_HINTS = re.compile(
    r"(?<![a-z0-9])(metal|punk|hardcore|grind|doom|sludge|stoner|"
    r"hard rock|heavy rock)(?![a-z0-9])"
)
UNSAFE_NAMES = re.compile(
    r"(?<![a-z0-9])(dj set|afterparty|guest|invite|surprise|tba|"
    r"open mic|artiste|groupe)(?![a-z0-9])"
)

DATE = re.compile(
    r"^(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)\s+"
    r"(\d{1,2})\s+([a-z]+)\s+(20\d{2})$"
)


class Details(HTMLParser):
    """Paragraphs before and after the booking link are different evidence."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.before = []
        self.after = []
        self.in_p = 0
        self.parts = []
        self.reservation = False
        self.date_seen = False
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.hidden += 1
        if self.hidden:
            return
        if tag == "p" and self.in_p == 0:
            self.in_p = 1
            self.parts = []
        elif self.in_p and tag not in ("br", "hr", "img", "input", "meta", "link"):
            self.in_p += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self.hidden = max(self.hidden-1, 0)
            return
        if self.in_p:
            self.in_p -= 1
            if self.in_p == 0:
                value = " ".join(" ".join(self.parts).split())
                if value:
                    (self.after if self.reservation else self.before).append(value)
                    if DATE.fullmatch(norm(value)):
                        self.date_seen = True
                self.parts = []

    def handle_data(self, data):
        if self.hidden:
            return
        if self.in_p:
            self.parts.append(data)
        elif self.date_seen and norm(data) == "reservation":
            self.reservation = True



class VisibleNodes(HTMLParser):
    """Read public visible text nodes, excluding scripts and CSS."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "svg"):
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg"):
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden and data.strip():
            self.parts.append(" ".join(data.split()))


def extract(page):
    parser = VisibleNodes()
    parser.feed(page)
    nodes = parser.parts
    dates = [(i, DATE.fullmatch(norm(s)))
             for i, s in enumerate(nodes) if DATE.fullmatch(norm(s))]
    if len(dates) != 1:
        raise ValueError("Une date officielle unique doit figurer dans la fiche")
    date_at, match = dates[0]
    d, month, y = match.groups()
    if month not in MONTHS:
        raise ValueError("Mois officiel inconnu")
    date_iso = dt.date(int(y), MONTHS[month], int(d)).isoformat()
    # The official page identifies artist/genre nodes between the event date
    # and the booking/share/start-time section. Booking may be absent for a
    # sold-out show; never depend on its presence.
    boundary = next((i for i in range(date_at+1, len(nodes))
                     if norm(nodes[i]) in ("reservation", "partagez")
                     or norm(nodes[i]).startswith("horaires debut")), None)
    if boundary is None or boundary - date_at > 35:
        raise ValueError("En-tête officiel du concert non isolé")
    lineup = [s for s in nodes[date_at+1:boundary] if norm(s)]
    if not 2 <= len(lineup) <= 25:
        raise ValueError("Artistes ou genres absents de l'en-tête officiel")

    clock = []
    for i in range(boundary, len(nodes)):
        s = nodes[i]
        if norm(s).startswith("horaires debut"):
            m = re.search(r"\b((?:[01]\d|2[0-3]):[0-5]\d)\b", s)
            if not m and i+1 < len(nodes):
                m = re.fullmatch(r"((?:[01]\d|2[0-3]):[0-5]\d)", nodes[i+1].strip())
            if m:
                clock.append(m.group(1))
    if len(clock) != 1:
        raise ValueError("Heure de début officielle absente ou ambiguë")
    return {"date": date_iso, "lineupTokens": lineup, "time": clock[0]}


def verify(candidate, page, catalogue, today):
    if candidate.get("source") != "agenda_officiel_ferrailleur_genre":
        raise ValueError("Une source de la salle Le Ferrailleur est requise")
    if candidate.get("reviewBucket") != "genre_tag_review" or candidate.get("possibleExistingConcert"):
        raise ValueError("Candidat incertain ou doublon potentiel")
    if candidate.get("publicationAllowed") is not False or candidate.get("reviewRequired") is not True:
        raise ValueError("Piste de découverte non isolée")
    if candidate.get("venue") != "Le Ferrailleur" or norm(candidate.get("city")) != "nantes":
        raise ValueError("Salle inconnue ou ville incohérente")
    if candidate.get("officialDetailFound") is not True:
        raise ValueError("Lien de fiche individuelle non vérifié dans l'agenda")
    link = candidate.get("sourceUrl") or ""
    parsed = urlsplit(link)
    if (parsed.scheme != "https" or parsed.hostname not in HOSTS or
        parsed.username or parsed.password or parsed.query or parsed.fragment or
        not re.fullmatch(r"/evenement/[^/?#]+/\d+/?", parsed.path)):
        raise ValueError("URL de fiche individuelle officielle invalide")
    detail = extract(page)
    if detail["date"] != candidate.get("date") or dt.date.fromisoformat(detail["date"]) <= today:
        raise ValueError("La date officielle ne concorde pas ou est passée")
    if detail["time"] != candidate.get("localTime"):
        raise ValueError("Horaire officiel divergent")
    title = candidate.get("name") or ""
    parts = artist_names(title)
    if BANNED.search(norm(title)):
        raise ValueError("Affiche incomplète ou de type festival")
    tokens = detail["lineupTokens"]
    labels = candidate.get("classification") or []
    if not labels or len(labels) > 10:
        raise ValueError("Genre non documenté")
    allowed = {norm(x) for x in labels}
    used = 0
    genre_found = set()
    for i, name in enumerate(parts):
        if used >= len(tokens) or norm(tokens[used]) != norm(name):
            raise ValueError("Nom d'artiste différent de la fiche officielle")
        used += 1
        next_artist = norm(parts[i+1]) if i+1 < len(parts) else None
        genres = []
        while used < len(tokens) and (not next_artist or norm(tokens[used]) != next_artist):
            # One HTML node may contain one or several comma-separated genres.
            for token in tokens[used].split(","):
                genre = norm(token)
                if genre:
                    genres.append(genre)
            used += 1
        if not genres or any(label not in allowed for label in genres):
            raise ValueError("Genre de l'artiste absent de la preuve officielle")
        genre_found.update(g for g in labels if norm(g) in genres)
    if used != len(tokens):
        raise ValueError("Artiste supplémentaire non corroboré")

    if not genre_found or not any(GENRE_HINTS.search(norm(g)) for g in genre_found):
        raise ValueError("Aucun genre métal ou punk explicitement confirmé")

    venue = next((v for v in catalogue["venues"] if v["id"] == VENUE_ID), None)
    if not venue or venue.get("city") != "Nantes":
        raise ValueError("Lieu absent du catalogue")
    if (venue.get("address") != "Quai des Antilles" or
        venue.get("postalCode") != "44200" or
        venue.get("latitude") != 47.20058 or
        venue.get("longitude") != -1.57365 or
        "OpenStreetMap" not in venue.get("geoSource", "")):
        raise ValueError("Position réelle du Ferrailleur non encore certifiée sur la carte")
    known = {}
    aliases = set()
    reserved_ids = set()
    for a in catalogue["artists"]:
        known.setdefault(norm(a["name"]), []).append(a["id"])
        reserved_ids.add(a["id"])
        for alias in (a.get("aliases") or []):
            if isinstance(alias, str) and alias.strip():
                aliases.add(norm(alias))
    ids, fresh = [], []
    for name in parts:
        key = norm(name)
        matches = known.get(key, [])
        if len(matches) > 1 or (not matches and key in aliases):
            raise ValueError("Identité ou alias d'artiste ambigu : " + name)
        if len(matches) == 1:
            aid = matches[0]
        else:
            aid = slug(name)
            if (not 3 <= len(aid) <= 100 or aid in reserved_ids or
                    UNSAFE_NAMES.search(key) or not re.search(r"[a-z]", aid)):
                raise ValueError("Nouvel artiste ambigu ou identifiant déjà utilisé : " + name)
            fresh.append({"id": aid, "name": name})
            reserved_ids.add(aid)
        ids.append(aid)
    if len(fresh) > MAX_NEW_ARTISTS:
        raise ValueError("Trop de nouveaux artistes pour une approbation automatique")
    if len(set(ids)) != len(ids):
        raise ValueError("Artistes dupliqués dans l'affiche")

    for e in catalogue["events"]:
        if e["date"] == detail["date"] and e["venueId"] == VENUE_ID and (
            set(e["artistIds"]) & set(ids)
        ):
            raise ValueError("Concert déjà publié pour cette date et cette salle")
    event_id = "go-c-" + detail["date"].replace("-", "") + "-nantes-" + slug(parts[0])
    if any(e["id"] == event_id for e in catalogue["events"]):
        raise ValueError("ID concert déjà utilisé")

    return {
        "reviewDecision": "approved",
        "reviewedBy": "automated-official-recheck",
        "reviewedAt": today.isoformat(),
        "officialEvidence": [{
            "url": link, "proofType": "official-organizer-or-venue",
            "checkedAt": today.isoformat(),
            "checkedFields": ["artists", "date", "venue", "genre"],
            "officialArtistNames": parts,
            "verifiedNewArtists": [a["name"] for a in fresh],
            "notes": "Fiche officielle individuelle Le Ferrailleur; artistes, date, heure, genre et position de salle revérifiés."
        }],
        "event": {
            "id": event_id, "title": title, "date": detail["date"],
            "time": detail["time"], "artistIds": ids, "venueId": VENUE_ID,
            "genres": sorted(genre_found), "status": "confirmed",
            "officialUrl": link, "sourceType": "salle", "organizer": "Le Ferrailleur"
        },
        "newArtists": fresh
    }
