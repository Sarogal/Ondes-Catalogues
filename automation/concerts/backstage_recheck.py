"""Fail-closed first-party detail verifier for Backstage By The Mill, Paris.

This module does not trust discovery genre labels or generic calendar cards.
It re-fetches an individual HTTPS event detail and checks the visible, local
event header: named bill, ISO-equivalent date, genre and named venue/address.
Only a previously known venue can be used; no start time is inferred.
"""
from __future__ import annotations

import datetime as dt
from html.parser import HTMLParser
import re
import unicodedata
from urllib.parse import urlsplit

VENUE_ID = "backstage-by-the-mill-paris"
HOST = "www.backstage-btm.com"
PATH = re.compile(r"/agenda/[a-z0-9-]{3,100}/")
DATE = re.compile(r"(?<!\d)(\d{2})/(\d{2})/(20\d{2})(?!\d)")
ALLOWED_GENRES = {
    "groove metal": "Groove Metal",
    "black metal": "Black Metal",
    "death metal": "Death Metal",
    "melodic death metal": "Melodic Death Metal",
    "metalcore": "Metalcore",
    "industrial metal": "Industrial Metal",
    "progressive metal": "Progressive Metal",
    "heavy metal": "Heavy Metal",
    "thrash metal": "Thrash Metal",
    "hardcore": "Hardcore",
    "post hardcore": "Post Hardcore",
    "post metal": "Post Metal",
    "doom metal": "Doom Metal",
    "stoner rock": "Stoner Rock",
    "punk rock": "Punk Rock",
    "punk": "Punk",
    "metal": "Metal",
    "hard rock": "Hard Rock",
}
UNSAFE = re.compile(r"\b(?:guest|guests|tba|a confirmer|festival|annule|"
                    r"annulee|reporte|reportee|postponed|cancelled)\b")


def norm(value):
    value = unicodedata.normalize("NFKD", str(value or "").casefold())
    return " ".join(re.findall(r"[a-z0-9]+",
                               value.encode("ascii", "ignore").decode("ascii")))


def slug(value):
    return norm(value).replace(" ", "-")[:72].strip("-")


class VisibleHeader(HTMLParser):
    """Visible text and h1 positions only; scripts/JSON-LD never count as proof."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tokens = []
        self.headings = []
        self.hidden = 0
        self.h1 = None
        self.h1_start = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "svg"):
            self.hidden += 1
        if tag == "h1" and not self.hidden:
            if self.h1 is not None:
                raise ValueError("Titre H1 imbriqué")
            self.h1 = []
            self.h1_start = len(self.tokens)

    def handle_endtag(self, tag):
        if tag == "h1" and self.h1 is not None:
            title = " ".join(" ".join(self.h1).split())
            self.headings.append((title, self.h1_start))
            self.h1 = None
        if tag in ("script", "style", "noscript", "svg") and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if self.hidden:
            return
        text = " ".join(str(data).split())
        if not text:
            return
        self.tokens.append(text)
        if self.h1 is not None:
            self.h1.append(text)


def verify(candidate, html_text, catalogue, today):
    if (candidate.get("source") != "agenda_officiel_backstage_detail"
            or candidate.get("reviewBucket") != "genre_tag_review"
            or candidate.get("possibleExistingConcert") is not False
            or candidate.get("reviewRequired") is not True
            or candidate.get("publicationAllowed") is not False):
        raise ValueError("Candidat Backstage non admissible ou doublon potentiel")
    if (norm(candidate.get("venue")) != "backstage by the mill"
            or norm(candidate.get("city")) != "paris"):
        raise ValueError("Salle ou ville de découverte incohérente")
    url = candidate.get("sourceUrl") or ""
    u = urlsplit(url)
    if (u.scheme != "https" or u.hostname != HOST or not PATH.fullmatch(u.path)
            or u.username or u.password or u.port or u.query or u.fragment):
        raise ValueError("Fiche nominative HTTPS Backstage exigée")
    page = VisibleHeader()
    page.feed(html_text)
    if len(page.headings) != 1 or not page.headings[0][0]:
        raise ValueError("Un seul titre H1 officiel est requis")
    title, pos = page.headings[0]
    if norm(title) != norm(candidate.get("name")):
        raise ValueError("Titre officiel différent de la découverte")
    if UNSAFE.search(norm(title)):
        raise ValueError("Affiche partielle, annulée ou reportée")
    # No page-footer/recommendation/artist biography can supply the event
    # date, category or venue. All must occur immediately after the H1.
    header_tokens = page.tokens[pos+1:pos+24]
    header = " ".join(header_tokens)
    dates = DATE.findall(header)
    if len(dates) != 1:
        raise ValueError("Date d'événement ambiguë ou absente du bandeau officiel")
    dd, mm, yy = map(int, dates[0])
    date = dt.date(yy, mm, dd)
    if date < today or date.isoformat() != candidate.get("date"):
        raise ValueError("Date d'événement différente ou passée")
    genre = next((ALLOWED_GENRES[norm(x)] for x in header_tokens
                  if norm(x) in ALLOWED_GENRES), None)
    if not genre or norm(genre) not in {
            norm(x) for x in (candidate.get("classification") or [])}:
        raise ValueError("Genre non confirmé sur la fiche individuelle")
    place = norm(header)
    if (not ("osullivans by the mill" in place
             or "o sullivans by the mill" in place)
            or "clichy" not in place or "paris" not in place):
        raise ValueError("Lieu nominatif de la fiche officielle absent")
    if UNSAFE.search(norm(" ".join(header_tokens[:8]))):
        raise ValueError("Événement annulé, reporté ou à confirmer")
    names = [x.strip() for x in re.split(r"\s+\+\s+", title)]
    if not 1 <= len(names) <= 5 or any(len(norm(n)) < 3 for n in names):
        raise ValueError("Programmation non nominative")
    if len({norm(n) for n in names}) != len(names):
        raise ValueError("Artistes répétés dans la programmation")
    venue = next((v for v in catalogue["venues"] if v.get("id") == VENUE_ID), None)
    if not venue or norm(venue.get("city")) != "paris":
        raise ValueError("Salle non validée dans le catalogue")
    existing_names = {}
    all_aliases = set()
    for a in catalogue["artists"]:
        existing_names.setdefault(norm(a["name"]), []).append(a)
        all_aliases.update(norm(alias) for alias in a.get("aliases", [])
                           if isinstance(alias, str))
    artist_ids, new_artists = [], []
    for name in names:
        found = existing_names.get(norm(name), [])
        if len(found) > 1 or (not found and norm(name) in all_aliases):
            raise ValueError("Identité d'artiste ambiguë ou alias existant")
        aid = found[0]["id"] if found else slug(name)
        if not aid or (not found and any(a["id"] == aid for a in catalogue["artists"])):
            raise ValueError("Collision d'identifiant artiste")
        artist_ids.append(aid)
        if not found:
            new_artists.append({"id": aid, "name": name})
    if len(set(artist_ids)) != len(artist_ids):
        raise ValueError("Identifiants artistes répétés")
    if any(e.get("date") == date.isoformat() and e.get("venueId") == VENUE_ID
           and set(e.get("artistIds", [])) & set(artist_ids)
           for e in catalogue["events"]):
        raise ValueError("Concert déjà publié ce jour dans la salle")
    event_id = "go-c-" + date.strftime("%Y%m%d") + "-paris-" + slug(names[0])
    if any(e.get("id") == event_id for e in catalogue["events"]):
        raise ValueError("Identifiant de concert déjà publié")
    return {
        "reviewDecision": "approved", "reviewedBy": "automated-official-recheck",
        "reviewedAt": today.isoformat(),
        "officialEvidence": [{
            "url": url, "proofType": "official-organizer-or-venue",
            "checkedAt": today.isoformat(),
            "checkedFields": ["artists", "date", "venue", "genre"],
            "officialArtistNames": names,
            "notes": "Fiche nominative officielle revérifiée en lecture seule; aucune heure supposée."
        }],
        "event": {
            "id": event_id, "title": title, "date": date.isoformat(),
            "time": None, "artistIds": artist_ids, "venueId": VENUE_ID,
            "genres": [genre], "status": "confirmed", "officialUrl": url,
            "sourceType": "salle", "organizer": "Backstage By The Mill"
        },
        "newArtists": new_artists
    }
