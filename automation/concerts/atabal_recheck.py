"""Strict live first-party recheck for the initial Atabal automated pilot.

Only Peter Hook & The Light (8 April 2027) is authorized here. The general
Atabal discovery adapter remains READ-ONLY for all other events. No artist,
support act, start time, cancellation or genre is inferred from recommendations.
"""
from __future__ import annotations

import datetime as dt
from html.parser import HTMLParser
import re
import unicodedata
from urllib.parse import urlsplit

VENUE = "atabal-biarritz"
HOST = "www.atabal-biarritz.fr"
URL = ("https://www.atabal-biarritz.fr/agenda/concerts/"
       "peter-hook-the-light-a-joy-division-celebration-jeudi-08-avril-2027/")
EVENT_ID = "go-c-20270408-biarritz-peter-hook-and-the-light"
ARTIST_ID = "peter-hook-and-the-light"
ARTIST = "PETER HOOK & THE LIGHT"
DATE = "2027-04-08"
GENRE = "Post Punk"
UNSAFE = re.compile(r"\b(?:annule|annulee|reporte|reportee|cancelled|"
                    r"postponed|1ere partie|premiere partie|support act|"
                    r"special guest|artiste invite|guest|a confirmer|tba|festival)\b")


def norm(value):
    value = unicodedata.normalize("NFKD", str(value or "").casefold())
    return " ".join(re.findall(r"[a-z0-9]+",
                               value.encode("ascii", "ignore").decode("ascii")))


class FirstEventArticle(HTMLParser):
    """Read visible text in one event article, excluding recommendations."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.started = False
        self.done = False
        self.depth = 0
        self.hidden = 0
        self.tokens = []
        self.h1 = []
        self.h5 = []
        self.capture = None
        self.buffer = []
        self.h1_position = None

    def handle_starttag(self, tag, attrs):
        if self.done:
            return
        if tag == "article":
            if not self.started:
                self.started = True
            self.depth += 1
        if tag in ("script", "style", "noscript", "svg"):
            self.hidden += 1
        if not self.started or self.hidden:
            return
        if tag in ("h1", "h4", "h5"):
            self.capture = tag
            self.buffer = []
            if tag == "h1":
                self.h1_position = len(self.tokens)

    def handle_endtag(self, tag):
        # Closing scripts in <head> must release the hidden-text guard even
        # before the first article has begun.
        if tag in ("script", "style", "noscript", "svg") and self.hidden:
            self.hidden -= 1
            return
        if not self.started or self.done:
            return
        if self.capture == tag:
            text = " ".join(" ".join(self.buffer).split())
            if tag == "h1":
                self.h1.append(text)
            if tag == "h5":
                self.h5.append(text)
            if tag == "h4" and norm(text).startswith("vous devriez aimer"):
                self.done = True
            self.capture = None
            self.buffer = []
        if tag == "article":
            self.depth -= 1
            if self.depth == 0:
                self.done = True

    def handle_data(self, data):
        if not self.started or self.done or self.hidden:
            return
        text = " ".join(str(data).split())
        if not text:
            return
        self.tokens.append(text)
        if self.capture:
            self.buffer.append(text)


def verify(candidate, html_text, catalogue, today):
    if (candidate.get("source") != "agenda_officiel_atabal_detail"
            or candidate.get("reviewBucket") != "genre_tag_review"
            or candidate.get("possibleExistingConcert") is not False
            or candidate.get("reviewRequired") is not True
            or candidate.get("publicationAllowed") is not False
            or candidate.get("officialDetailFound") is not True):
        raise ValueError("Candidat Atabal non admissible ou doublon possible")
    if (candidate.get("sourceUrl") != URL
            or candidate.get("date") != DATE
            or norm(candidate.get("name")) != norm(ARTIST)
            or candidate.get("classification") != [GENRE]
            or norm(candidate.get("city")) != "biarritz"
            or norm(candidate.get("venue")) != "atabal"
            or candidate.get("venueCatalogueId") != VENUE):
        raise ValueError("Affiche Atabal non incluse dans le pilote indépendant")
    u = urlsplit(candidate["sourceUrl"])
    if (u.scheme != "https" or u.hostname != HOST or u.username
            or u.password or u.port or u.query or u.fragment):
        raise ValueError("Fiche Atabal HTTPS nominative exigée")
    if dt.date.fromisoformat(DATE) < today:
        raise ValueError("Concert passé")
    p = FirstEventArticle()
    p.feed(html_text)
    if p.h1 != [ARTIST] or p.h1_position is None:
        raise ValueError("Titre officiel Atabal inattendu ou plusieurs artistes")
    # A current first-party date must be visible in the event's header,
    # not inside its biography, recommendations, or old metadata.
    header = norm(" ".join(p.tokens[:p.h1_position]))
    if not re.search(r"\b0?8 avril 2027\b", header):
        raise ValueError("Date première main absente ou modifiée")
    if p.h5 != ["POST PUNK"]:
        raise ValueError("Genre explicite POST PUNK absent ou incohérent")
    before_recs = norm(" ".join(p.tokens))
    if UNSAFE.search(before_recs):
        raise ValueError("Programmation annulee, modifiée, invitée ou festival")
    if "a joy division celebration" not in before_recs:
        raise ValueError("Sous-titre nominatif officiel absent")
    venue = next((x for x in catalogue["venues"] if x.get("id") == VENUE), None)
    if not venue or norm(venue.get("city")) != "biarritz":
        raise ValueError("Salle Atabal non reconnue par le catalogue")
    known = [a for a in catalogue["artists"] if a.get("id") == ARTIST_ID]
    if (len(known) != 1
            or norm(known[0].get("name")) != "peter hook and the light"
            or any(a.get("id") == ARTIST_ID and a is not known[0]
                   for a in catalogue["artists"])):
        raise ValueError("Identité Peter Hook & The Light non validée")
    if any(e.get("id") == EVENT_ID or
           (e.get("date") == DATE and e.get("venueId") == VENUE and
            ARTIST_ID in e.get("artistIds", []))
           for e in catalogue["events"]):
        raise ValueError("Concert Atabal déjà référencé")
    return {
        "reviewDecision": "approved",
        "reviewedBy": "automated-official-recheck",
        "reviewedAt": today.isoformat(),
        "officialEvidence": [{
            "url": URL, "proofType": "official-organizer-or-venue",
            "checkedAt": today.isoformat(),
            "checkedFields": ["artists", "date", "venue", "genre"],
            "officialArtistNames": [ARTIST],
            "notes": "Fiche individuelle Atabal revérifiée : groupe déjà connu, date et genre visibles. Horaire 19H30 non qualifié."
        }],
        "event": {
            "id": EVENT_ID, "title": ARTIST, "date": DATE, "time": None,
            "artistIds": [ARTIST_ID], "venueId": VENUE, "genres": [GENRE],
            "status": "confirmed", "officialUrl": URL,
            "sourceType": "salle", "organizer": "Atabal"
        },
        "newArtists": []
    }
