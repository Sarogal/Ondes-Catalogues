"""Strict independent recheck of La Laiterie named first-party concert bills.

Only a second retrieval of the EXACT official detail page may sign a date:
one to four canonical EXISTING artists, no undisclosed support or guest, a single
official event date and an explicit relevant genre. Never infer door times.
"""
from __future__ import annotations

import datetime as dt
import re

import laiterie_adapter as source
import triage

SOURCE = "agenda_officiel_laiterie_detail_review"
VENUE_ID = "la-laiterie-strasbourg"
STRUCTURE = "artefact-single-artist-header-and-artist-section"
MULTI_STRUCTURE = "artefact-multi-artist-header-and-sections"
UNKNOWN = re.compile(
    r"(?<![a-z0-9])(?:guests?|invites?|special guests?|first part|premiere partie|1ere partie|1re partie|"
    r"support|featuring|feat|ft|tba|a confirmer|festival|dj set|tribute|"
    r"annule|report[eé]|postponed|cancelled)(?![a-z0-9])", re.I
)
ALLOWED_GENRES = (
    ("post punk", "Post Punk"),
    ("black metal", "Black Metal"),
    ("death metal", "Death Metal"),
    ("hard rock", "Hard Rock"),
    ("stoner", "Stoner Rock"),
    ("sludge", "Sludge"),
    ("doom", "Doom Metal"),
    ("thrash", "Thrash Metal"),
    ("metal", "Metal"),
    ("punk", "Punk"),
    ("grunge", "Grunge"),
    ("shoegaze", "Shoegaze"),
    ("noise rock", "Noise Rock"),
    ("math rock", "Math Rock"),
    ("post rock", "Post Rock"),
)


def canonical_words(name):
    # Only exact canonical band identity is accepted, with the typographic
    # conjunction "&" equivalent to the written word "and" in artist names.
    return triage.words(re.sub(r"\s*&\s*", " and ", str(name or "")))


def explicit_genre(tag):
    label = triage.words(tag)
    for key, canonical in ALLOWED_GENRES:
        if re.search(r"(?<!\w)" + re.escape(key) + r"(?!\w)", label):
            return canonical
    raise ValueError("Genre rock/punk/metal explicite absent de la fiche")


def official_artist_sections(html):
    """Read only the Artistes section, not biography or recommendations."""
    doc = source._Extract()
    doc.feed(html)
    headings = [(kind, title) for kind, title, _ in doc.headings]
    markers = [i for i, (kind, title) in enumerate(headings)
               if kind == "h2" and triage.words(title) == "artistes"]
    if len(markers) != 1:
        raise ValueError("Section officielle des artistes introuvable ou ambiguë")
    begin = markers[0] + 1
    end = next((i for i in range(begin, len(headings))
                if headings[i][0] == "h2"
                and triage.words(headings[i][1]) in (
                    "on vous recommande", "nos recommandations", "a decouvrir",
                )), len(headings))
    lineup = [t for k, t in headings[begin:end] if k == "h2" and t.strip()]
    normalized = [canonical_words(name) for name in lineup]
    if (not 1 <= len(lineup) <= 4
            or len(set(normalized)) != len(lineup)
            or any(not 3 <= len(name) <= 100
                   or UNKNOWN.search(triage.words(raw))
                   for name, raw in zip(normalized, lineup))):
        raise ValueError("Programmation officielle incomplète, ambiguë ou non nominative")
    return lineup


def official_single_artist_section(html):
    """Keep the existing single-artist contract available."""
    names = official_artist_sections(html)
    if len(names) != 1:
        raise ValueError("Plusieurs artistes ou programmation incomplète")
    return names[0]



def verify(candidate, html, catalogue, today):
    if not isinstance(today, dt.date) or not isinstance(candidate, dict):
        raise ValueError("Relecture invalide")
    if (candidate.get("source") != SOURCE
            or candidate.get("reviewBucket") != "genre_tag_review"
            or candidate.get("possibleExistingConcert") is not False
            or candidate.get("publicationAllowed") is not False
            or candidate.get("reviewRequired") is not True
            or candidate.get("officialDetailFound") is not True
            or candidate.get("sourcePage") != source.AGENDA
            or candidate.get("venue") != "La Laiterie"
            or triage.words(candidate.get("city")) != "strasbourg"
            or str(candidate.get("department")) != "67"):
        raise ValueError("Candidat non éligible ou provenance ambiguë")
    url = candidate.get("sourceUrl")
    if not isinstance(url, str) or source.valid_detail(url) is None:
        raise ValueError("URL nominative La Laiterie invalide")
    if not isinstance(html, str) or not 100 <= len(html) <= 500_000:
        raise ValueError("Détail officiel absent ou trop volumineux")
    official_source = {
        "name": "La Laiterie", "city": "Strasbourg",
        "department": "67", "url": source.AGENDA,
    }
    fresh = source.details(html, url, official_source, today.isoformat())
    for key in ("source", "sourceUrl", "sourcePage", "name", "leadArtist",
                "date", "classification", "venue", "city", "department"):
        if fresh.get(key) != candidate.get(key):
            raise ValueError("Découverte et fiche officielle divergentes : " + key)
    if fresh["date"] <= today.isoformat() or fresh.get("localTime") is not None:
        raise ValueError("Date passée ou horaire non fiable")
    title = fresh["name"]
    if UNKNOWN.search(triage.words(title)):
        raise ValueError("Invité, première partie ou statut non identifié")
    # Only split explicit event-header "+" separators, never band-name "&".
    parts = [name.strip() for name in re.split(r"\s+\+\s+", title)]
    normalized = [canonical_words(name) for name in parts]
    if (not 1 <= len(parts) <= 4 or any(len(name) < 3 for name in normalized)
            or len(set(normalized)) != len(parts)
            or normalized[0] != canonical_words(fresh["leadArtist"])):
        raise ValueError("Affiche officielle incomplète ou artistes ambigus")
    # All names must be repeated in the event's own Artistes H2s, in order.
    sections = official_artist_sections(html)
    if (len(sections) != len(parts)
            or any(canonical_words(a) != canonical_words(b)
                   for a, b in zip(parts, sections))):
        raise ValueError("Programmation nominative non corroborée dans la fiche")
    if not isinstance(catalogue, dict) or any(
        not isinstance(catalogue.get(x), list)
        for x in ("venues", "events", "artists")
    ):
        raise ValueError("Catalogue incomplet")
    performers = []
    for name in parts:
        matches = [a for a in catalogue["artists"]
                   if canonical_words(a.get("name")) == canonical_words(name)
                   and isinstance(a.get("id"), str)]
        if len(matches) != 1:
            raise ValueError("Un artiste canonique déjà connu est obligatoire")
        performers.append(matches[0])
    venues = [v for v in catalogue["venues"] if v.get("id") == VENUE_ID]
    if (len(venues) != 1 or triage.words(venues[0].get("city")) != "strasbourg"
            or not all(venues[0].get(x) is not None
                       for x in ("latitude", "longitude"))):
        raise ValueError("Salle et géolocalisation officielles ambiguës")
    genre = explicit_genre(fresh["classification"][0])
    ids = [a["id"] for a in performers]
    if (len(set(ids)) != len(ids)
            or any(not re.fullmatch(r"[a-z0-9-]{3,100}", artist_id)
                   for artist_id in ids)
            or any(e.get("officialUrl") == url or
                   (e.get("date") == fresh["date"]
                    and e.get("venueId") == VENUE_ID
                    and set(ids) & set(e.get("artistIds") or []))
                   for e in catalogue["events"])):
        raise ValueError("Identité artistique invalide ou concert déjà connu")
    event_id = "go-c-" + fresh["date"].replace("-", "") + "-strasbourg-" + ids[0]
    if len(event_id) > 150 or any(e.get("id") == event_id for e in catalogue["events"]):
        raise ValueError("Collision d'identifiant")
    names = [a["name"] for a in performers]
    bill_title = " + ".join(names)
    return {
        "reviewDecision": "approved",
        "reviewedBy": "automated-official-recheck",
        "reviewedAt": today.isoformat(),
        "officialEvidence": [{
            "url": url,
            "proofType": "official-organizer-or-venue",
            "checkedAt": today.isoformat(),
            "checkedFields": ["artists", "date", "venue", "genre"],
            "officialArtistNames": names,
            "sourceStructure": STRUCTURE if len(ids) == 1 else MULTI_STRUCTURE,
        }],
        "event": {
            "id": event_id, "title": bill_title,
            "date": fresh["date"], "time": None,
            "artistIds": ids, "venueId": VENUE_ID,
            "genres": [genre], "status": "confirmed",
            "officialUrl": url, "sourceType": "salle",
            "organizer": "La Laiterie",
        },
        "newArtists": [],
    }
