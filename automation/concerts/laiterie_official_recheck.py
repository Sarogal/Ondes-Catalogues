"""Strict independent recheck of La Laiterie named first-party concert bills.

Only a second retrieval of the EXACT official detail page may sign a date:
one to four confirmed named artists; an explicitly unannounced guest may be omitted
from the public artist list. The official date, genre and venue remain mandatory. A single
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
PARTIAL_STRUCTURE = "artefact-confirmed-artists-with-unannounced-support"
UNKNOWN = re.compile(
    r"(?<![a-z0-9])(?:guests?|invites?|special guests?|first part|premiere partie|1ere partie|1re partie|"
    r"support|featuring|feat|ft|tba|a confirmer|festival|dj set|tribute|"
    r"annule|report[eé]|postponed|cancelled|surprise)(?![a-z0-9])", re.I
)

# Only whole, well-defined placeholders may be omitted, never a new/unknown
# proper artist name. Do not turn cancellation, "festival" or a sold-out
# status into an "unknown guest".
UNANNOUNCED_LABELS = frozenset({
    "guest", "special guest", "invite", "invite surprise", "artiste surprise",
    "premiere partie", "1ere partie", "1re partie", "support", "a confirmer", "tba",
})


def unannounced_label(value):
    label = triage.words(value)
    return label if label in UNANNOUNCED_LABELS else None

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


def official_artist_sections(html, allow_unannounced=False):
    """Read the exact official Artistes block, excluding recommendations."""
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
    placeholders = [i for i, n in enumerate(lineup) if unannounced_label(n)]
    if (not 1 <= len(lineup) <= 5
            or len(set(normalized)) != len(lineup)
            or any(not 3 <= len(name) <= 100 for name in normalized)
            or (placeholders and
                (not allow_unannounced or placeholders != [len(lineup) - 1]))
            or any(UNKNOWN.search(triage.words(raw))
                   for i, raw in enumerate(lineup) if i not in placeholders)
            or len(lineup) - len(placeholders) > 4):
        raise ValueError("Programmation officielle incomplète, ambiguë ou non nominative")
    return lineup


def official_single_artist_section(html):
    """Keep the historic one-artist verifier/test contract intact."""
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
    # A single trailing explicit placeholder is permitted; it is NEVER
    # represented as an artist or inferred from the official URL/biography.
    parts = [name.strip() for name in re.split(r"\s+\+\s+", title)]
    placeholders = [i for i, name in enumerate(parts) if unannounced_label(name)]
    if placeholders and (placeholders != [len(parts) - 1] or len(parts) < 2):
        raise ValueError("Invité non nommé à une position ambiguë")
    guest = parts[-1] if placeholders else None
    named_parts = parts[:-1] if guest else parts
    normalized = [canonical_words(name) for name in named_parts]
    if (not 1 <= len(named_parts) <= 4
            or any(len(name) < 3 or UNKNOWN.search(triage.words(raw))
                   for name, raw in zip(normalized, named_parts))
            or len(set(normalized)) != len(named_parts)
            or normalized[0] != canonical_words(fresh["leadArtist"])):
        raise ValueError("Artistes confirmés incomplets ou ambigus")
    sections = official_artist_sections(html, allow_unannounced=bool(guest))
    # The official event section must independently repeat all real artists.
    # It may repeat the announced placeholder once at the very end.
    named_sections = sections[:-1] if guest and unannounced_label(sections[-1]) else sections
    if (len(named_sections) != len(named_parts)
            or any(canonical_words(a) != canonical_words(b)
                   for a, b in zip(named_parts, named_sections))
            or (guest and unannounced_label(sections[-1])
                and unannounced_label(sections[-1]) != unannounced_label(guest))):
        raise ValueError("Programmation nominative non corroborée dans la fiche")
    if not isinstance(catalogue, dict) or any(
        not isinstance(catalogue.get(x), list)
        for x in ("venues", "events", "artists")
    ):
        raise ValueError("Catalogue incomplet")
    performers, added = [], []
    reserved = {a.get("id") for a in catalogue["artists"]}
    aliases = {canonical_words(alias)
               for a in catalogue["artists"]
               for alias in (a.get("aliases") or []) if isinstance(alias, str)}
    for name in named_parts:
        matches = [a for a in catalogue["artists"]
                   if canonical_words(a.get("name")) == canonical_words(name)
                   and isinstance(a.get("id"), str)]
        if len(matches) > 1:
            raise ValueError("Identité canonique ambiguë")
        if matches:
            performers.append(matches[0])
        elif guest and not added:
            # A new lead is accepted only when the first-party event header
            # AND Artistes section independently identify its proper name.
            artist_id = canonical_words(name).replace(" ", "-")
            if (not re.fullmatch(r"[a-z0-9-]{3,100}", artist_id)
                    or artist_id in reserved
                    or canonical_words(name) in aliases):
                raise ValueError("Artiste nouveau ou alias ambigu")
            added.append({"id": artist_id, "name": name})
            reserved.add(artist_id)
            performers.append(added[-1])
        else:
            raise ValueError("Un artiste canonique déjà connu est obligatoire")
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
    proof = {
        "url": url,
        "proofType": "official-organizer-or-venue",
        "checkedAt": today.isoformat(),
        "checkedFields": ["artists", "date", "venue", "genre"],
        "officialArtistNames": names,
        "sourceStructure": (PARTIAL_STRUCTURE if guest else
                            STRUCTURE if len(ids) == 1 else MULTI_STRUCTURE),
    }
    if guest:
        proof["unannouncedSupportLabel"] = unannounced_label(guest)
        proof["verifiedNewArtists"] = [a["name"] for a in added]
    return {
        "reviewDecision": "approved",
        "reviewedBy": "automated-official-recheck",
        "reviewedAt": today.isoformat(),
        "officialEvidence": [proof],
        "event": {
            "id": event_id, "title": bill_title,
            "date": fresh["date"], "time": None,
            "artistIds": ids, "venueId": VENUE_ID,
            "genres": [genre], "status": "confirmed",
            "officialUrl": url, "sourceType": "salle",
            "organizer": "La Laiterie",
        },
        "newArtists": added,
    }
