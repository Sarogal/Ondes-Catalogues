"""Independent Rockstore Montpellier proof: one previously known canonical band.

Discovery remains quarantined. A fresh exact first-party detail page must
match the original dated URL, sole named band, music tag, and venue. No artist,
venue, musical start time or support band may be inferred or created.
"""
from __future__ import annotations

import datetime as dt
import re

import rockstore_adapter as adapter
import triage

SOURCE = "agenda_officiel_rockstore_detail_review"
VENUE_ID = "rockstore-montpellier"
SOURCE_URL = adapter.AGENDA
PROOF_STRUCTURE = "rockstore-single-artist-official-heading-date-genre"
UNKNOWN = re.compile(
    r"(?<![a-z0-9])(?:guest|special guest|premiere partie|premieres parties|"
    r"support band|support act|opening act|invite|invites|tba|"
    r"a confirmer|festival|tribute|cover band|dj set|"
    r"annule|annulation|reporte|deplace|cancelled|postponed)"
    r"(?![a-z0-9])", re.I,
)
MULTI = re.compile(r"\s+(?:\+|/|&|feat\.?|ft\.?|with|w/|vs\.?)\s+", re.I)
GENRE_TAGS = (
    ("hard rock", "Hard Rock"),
    ("death metal", "Death Metal"),
    ("black metal", "Black Metal"),
    ("metalcore", "Metalcore"),
    ("deathcore", "Deathcore"),
    ("stoner", "Stoner Rock"),
    ("sludge", "Sludge"),
    ("thrash", "Thrash Metal"),
    ("doom", "Doom Metal"),
    ("punk", "Punk"),
    ("hardcore", "Hardcore"),
    ("grunge", "Grunge"),
    ("shoegaze", "Shoegaze"),
    ("post rock", "Post Rock"),
    ("noise rock", "Noise Rock"),
    ("garage rock", "Garage Rock"),
    ("rock alternatif", "Rock alternatif"),
    ("rock indus", "Rock indus"),
    ("metal", "Metal"),
)


def exact_genre_tag(value):
    label = triage.words(value)
    for official_word, accepted in GENRE_TAGS:
        if re.search(r"(?<!\w)" + re.escape(official_word) + r"(?!\w)", label):
            return accepted
    raise ValueError("Rockstore: genre de musique indépendant non documenté")


def verify(candidate, html_text, catalogue, today):
    if not isinstance(today, dt.date) or not isinstance(candidate, dict):
        raise ValueError("Rockstore: candidature/date invalide")
    if (candidate.get("source") != SOURCE
            or candidate.get("sourcePage") != SOURCE_URL
            or candidate.get("reviewBucket") != "genre_tag_review"
            or candidate.get("possibleExistingConcert") is not False
            or candidate.get("publicationAllowed") is not False
            or candidate.get("reviewRequired") is not True
            or candidate.get("officialDetailFound") is not True
            or candidate.get("genreToConfirm") is not True
            or triage.words(candidate.get("venue")) != "rockstore"
            or triage.words(candidate.get("city")) != "montpellier"
            or str(candidate.get("department")) != "34"):
        raise ValueError("Rockstore: candidat non fiable ou hors source")
    url = candidate.get("sourceUrl")
    if not isinstance(url, str) or adapter.detail_identity(url) is None:
        raise ValueError("Rockstore: lien officiel individuel invalide")
    if not isinstance(html_text, str) or not 100 <= len(html_text) <= 500_000:
        raise ValueError("Rockstore: detail officiel illisible")
    fresh = adapter.detail_candidate(
        html_text, url,
        {"name": "Rockstore", "city": "Montpellier",
         "department": "34", "url": SOURCE_URL},
        today.isoformat(),
    )
    for key in ("source", "sourcePage", "sourceUrl", "date", "name",
                "leadArtist", "venue", "city", "department", "classification"):
        if fresh.get(key) != candidate.get(key):
            raise ValueError("Rockstore: detail modifie depuis la decouverte : " + key)
    if fresh["date"] <= today.isoformat() or fresh.get("localTime") is not None:
        raise ValueError("Rockstore: date pas future ou heure presumee")
    title = fresh["name"].strip()
    if (MULTI.search(title) or UNKNOWN.search(triage.words(title))
            or not 3 <= len(title) <= 120):
        raise ValueError("Rockstore: plusieurs artistes ou affiche incomplete")
    parsed = adapter._Html()
    parsed.feed(html_text)
    # A secondary headliner may be named in the event body rather than H1.
    # Treat such pages as ambiguous, never as single-band approvals.
    nearby = triage.words(" ".join(
        parsed.visible[(parsed.heading_end or 0)+2:
                       (parsed.heading_end or 0)+42]))
    if UNKNOWN.search(nearby):
        raise ValueError("Rockstore: premiere partie ou statut ambigu dans l'annonce")
    if not isinstance(catalogue, dict) or not all(
        isinstance(catalogue.get(key), list)
        for key in ("artists", "venues", "events")
    ):
        raise ValueError("Rockstore: catalogue invalide")
    matches = [a for a in catalogue["artists"]
               if triage.words(a.get("name")) == triage.words(title)
               and isinstance(a.get("id"), str)]
    if len(matches) != 1:
        raise ValueError("Rockstore: artiste canonique deja connu requis")
    act = matches[0]
    venues = [v for v in catalogue["venues"] if v.get("id") == VENUE_ID]
    if (len(venues) != 1 or triage.words(venues[0].get("city")) != "montpellier"
            or not all(venues[0].get(k) is not None
                       for k in ("latitude", "longitude"))):
        raise ValueError("Rockstore: salle connue geolocalisee obligatoire")
    aid = act["id"]
    if not re.fullmatch(r"[a-z0-9-]{3,100}", aid):
        raise ValueError("Rockstore: identifiant artiste non canonique")
    if any(
        row.get("officialUrl") == url or
        (row.get("date") == fresh["date"] and
         row.get("venueId") == VENUE_ID and
         aid in row.get("artistIds", []))
        for row in catalogue["events"]
    ):
        raise ValueError("Rockstore: concert deja publie ou meme artiste/jour/salle")
    event_id = "go-c-" + fresh["date"].replace("-", "") + "-montpellier-" + aid
    if len(event_id) > 150 or any(
        row.get("id") == event_id for row in catalogue["events"]
    ):
        raise ValueError("Rockstore: conflit identifiant evenement")
    tag = exact_genre_tag(fresh["classification"][0])
    return {
        "reviewDecision": "approved",
        "reviewedBy": "automated-official-recheck",
        "reviewedAt": today.isoformat(),
        "officialEvidence": [{
            "url": url,
            "proofType": "official-organizer-or-venue",
            "checkedAt": today.isoformat(),
            "checkedFields": ["artists", "date", "venue", "genre"],
            "officialArtistNames": [act["name"]],
            "sourceStructure": PROOF_STRUCTURE,
        }],
        "event": {
            "id": event_id, "title": act["name"],
            "date": fresh["date"], "time": None,
            "artistIds": [aid], "venueId": VENUE_ID,
            "genres": [tag], "status": "confirmed",
            "officialUrl": url, "sourceType": "salle",
            "organizer": "Rockstore",
        },
        "newArtists": [],
    }
