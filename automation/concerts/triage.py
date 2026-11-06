"""Tri des propositions de concerts : diagnostics, jamais publication.

Une heuristique, un artiste connu, ou un ICS ne sont pas une preuve de concert métal.
"""
from __future__ import annotations

from collections import Counter
import re
import unicodedata

POSITIVE_GENRES = (
    "metal", "metalcore", "deathcore", "hardcore", "punk", "thrash",
    "grindcore", "black metal", "death metal", "doom metal",
    "post metal", "stoner rock", "stoner", "sludge", "hard rock", "heavy metal",
    # Explicit subgenres only: generic 'Rock' remains unverified, including
    # broad venue category menus. This list affects REVIEW priority, never approval.
    "heavy rock", "garage rock", "post rock", "noise rock", "electro rock",
    "psych rock", "psychedelic rock", "math rock", "shoegaze", "grunge",
)
NONCONCERT = re.compile(
    r"\b(atelier|conference|formation|reunion|masterclass|webinaire|blind test|"
    r"cours|portes ouvertes|writing camp|stage de|structuration de l artiste|"
    r"communiquer son projet|wikipaloma|comedie|spectacle jeune public)\b",
    re.I,
)
FESTIVAL_WORD = re.compile(r"\b(festival|fest|open air)\b", re.I)


def words(value):
    value = unicodedata.normalize("NFKD", str(value or "").casefold())
    value = value.encode("ascii", errors="ignore").decode("ascii")
    return " ".join(re.findall(r"[a-z0-9]+", value))


def genre_evidence(candidate):
    """Uniquement une classification explicite associée à l'événement.

    Ne pas considérer comme preuve les genres présents dans la description
    générale d'une salle (métal, punk, etc.).
    """
    labels = candidate.get("classification") or []
    if isinstance(labels, str):
        labels = [labels]
    text = " | ".join(words(x) for x in labels)
    if any(re.search(r"(?<!\w)" + re.escape(genre) + r"(?!\w)", text)
           for genre in POSITIVE_GENRES):
        return "tag_genre_source"
    # Generic Rock needs a named official event card, never a venue menu
    # or artist biography. This is only a REVIEW priority, not approval.
    if (candidate.get("genreEvidenceScope") in (
                "official_event_card", "official_artist_in_event_detail")
            and candidate.get("officialDetailFound") is True
            and any(words(x) == "rock" for x in labels)):
        return "official_event_rock_tag"
    return None


def catalogue_index(catalogue):
    artists = {str(a.get("id")): a.get("name", "") for a in catalogue.get("artists", [])}
    venues = {str(v.get("id")): v for v in catalogue.get("venues", [])}
    index = {}
    for event in catalogue.get("events", []):
        venue = venues.get(str(event.get("venueId")), {})
        key = (event.get("date"), words(venue.get("city")))
        entry = {
            "eventId": event.get("id"),
            "title": words(event.get("title")),
            "artists": [words(artists.get(str(a), "")) for a in event.get("artistIds", [])],
            "artistIds": list(event.get("artistIds", [])),
            "venueId": event.get("venueId"),
        }
        index.setdefault(key, []).append(entry)
        # Index par salle : les tournées peuvent annoncer Toulouse pour
        # Le Bikini, dont la commune cadastrale est Ramonville-Saint-Agne.
        # N'autorise ni fusion ni publication : c'est un diagnostic privé.
        if event.get("venueId"):
            index.setdefault((event.get("date"), "venue-id:" + str(event["venueId"])), []).append(entry)
    return index


def exact_catalogue_matches(candidate, index):
    """Identité exacte (date + ID de salle connu + ID d'artiste officiel).

    Pas de fuzzy matching, pas d'inférence sur un nom de salle ou une ville.
    """
    day = candidate.get("date")
    venue_id = candidate.get("venueIdIfKnown")
    artist_id = candidate.get("artistId")
    if not all(isinstance(x, str) and x for x in (day, venue_id, artist_id)):
        return []
    return sorted({
        item["eventId"]
        for item in index.get((day, "venue-id:" + venue_id), [])
        if artist_id in item["artistIds"] and item.get("eventId")
    })


def possible_duplicates(candidate, index):
    date = candidate.get("date")
    city = words(candidate.get("city"))
    name = words(candidate.get("name"))
    artist = words(candidate.get("leadArtist"))
    if not date or not city:
        return []
    matches = exact_catalogue_matches(candidate, index)
    for event in index.get((date, city), []):
        headline = event["title"]
        if name and headline and name == headline:
            matches.append(event["eventId"])
            continue
        # Nom d'artiste complet dans la programmation, pas seulement mot générique.
        # La salle doit être dans la même commune ET la date identique.
        for existing_artist in event["artists"]:
            if (len(existing_artist) >= 4 and
                (existing_artist == artist or
                 re.search(r"(?<!\w)" + re.escape(existing_artist) + r"(?!\w)", name))):
                matches.append(event["eventId"])
                break
    return sorted(set(m for m in matches if m))


def triage(candidate, catalogue=None, index=None):
    """Une proposition ne devient jamais publiable via cette fonction."""
    row = dict(candidate)
    index = index if index is not None else catalogue_index(catalogue or {})
    name = words(row.get("name"))
    duplicates = possible_duplicates(row, index)
    exact_matches = exact_catalogue_matches(row, index)
    row["catalogueMatches"] = duplicates
    # Un rapprochement exact peut être écarté de la shortlist de *nouveaux*
    # concerts, mais il reste dans le registre privé et ne change aucune
    # décision de l'éditeur. Les annulations gardent toujours la priorité.
    row["catalogueMatchEvidence"] = (
        "exact-date-venue-id-artist-id" if exact_matches else None
    )
    row["possibleExistingConcert"] = bool(duplicates) or bool(row.get("possibleExistingConcert"))
    row["publicationAllowed"] = False
    row["reviewRequired"] = True
    row["genreEvidence"] = genre_evidence(row)

    if row.get("cancellationNotice") or row.get("source") == "ics_cancellation_notice":
        bucket, reason = "cancellation_watch", "Annulation ou report signalé ; vérifier une fiche existante"
    elif not row.get("date"):
        bucket, reason = "undated_lead", "Annonce sans date de concert ; pas d'ajout possible"
    elif NONCONCERT.search(name):
        bucket, reason = "excluded_nonconcert", "Atelier, réunion ou contenu non-concert"
    elif FESTIVAL_WORD.search(name) or row.get("festivalContext"):
        bucket, reason = "festival_overlap_review", "Événement à recouper avec la carte Festivals"
    elif exact_matches:
        bucket, reason = "already_catalogued", "Même date, même salle identifiée et même artiste déjà publiés ; contrôle sans nouvelle fiche"
    elif row["possibleExistingConcert"]:
        bucket, reason = "possible_duplicate", "Date, ville et programmation déjà présentes ou similaires"
    elif row["genreEvidence"]:
        bucket, reason = "genre_tag_review", "Genre officiel de la fiche ou sous-genre identifié ; revue obligatoire"
    else:
        bucket, reason = "genre_unknown", "Genre non établi, ne pas classer automatiquement comme métal"
    row["reviewBucket"] = bucket
    row["reviewReason"] = reason
    return row


def classify(candidates, catalogue):
    idx = catalogue_index(catalogue)
    classified = [triage(item, index=idx) for item in candidates]
    counts = dict(Counter(x["reviewBucket"] for x in classified))
    # Des alertes de priorité vont en premier; les annonces sans date restent à part.
    priorities = {
        "cancellation_watch": 0,
        "possible_duplicate": 1,
        "already_catalogued": 7,
        "genre_tag_review": 2,
        "festival_overlap_review": 3,
        "genre_unknown": 4,
        "undated_lead": 5,
        "excluded_nonconcert": 6,
    }
    ordered = sorted(classified, key=lambda x: (
        priorities.get(x["reviewBucket"], 9), x.get("date") or "9999-12-31",
        words(x.get("city")), words(x.get("name"))
    ))
    shortlist = [
        x for x in ordered if x["reviewBucket"] in
        ("genre_tag_review", "possible_duplicate", "festival_overlap_review", "cancellation_watch")
    ]
    return ordered, shortlist, counts
