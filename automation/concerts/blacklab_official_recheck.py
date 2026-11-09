"""Strict first-party recheck for *single known artist* Black Lab concert pages.

This is a narrow, reusable first-party verification pattern: the discovery
candidate never grants approval. A second read of the canonical official
event page must restate the same date, sole *canonical* artist, genre, venue,
and active status. Multi-artist bills and new artists remain held for a
separately corroborated lineup verifier.
"""
from __future__ import annotations

import datetime as dt
import re

import blacklab_adapter as adapter
import triage

SOURCE = "agenda_officiel_blacklab_detail_review"
VENUE_ID = "the-black-lab-wasquehal"
CITY = "wasquehal"
SOURCE_URL = adapter.AGENDA
DANGEROUS_TITLE = re.compile(
    r"\b(?:festival|tribute|hommage|cover|dj|guest|invite|surprise|"
    r"annule|reporte|reportee|postponed|cancelled)\b", re.IGNORECASE
)


def verify(candidate, page, catalogue, today):
    if not isinstance(today, dt.date):
        raise ValueError("Date de contrôle invalide")
    if not isinstance(candidate, dict):
        raise ValueError("Candidat absent")
    if (candidate.get("source") != SOURCE
            or candidate.get("reviewBucket") != "genre_tag_review"
            or candidate.get("possibleExistingConcert") is not False
            or candidate.get("publicationAllowed") is not False
            or candidate.get("reviewRequired") is not True
            or candidate.get("officialDetailFound") is not True):
        raise ValueError("Candidat non éligible à la vérification officielle")
    if (triage.words(candidate.get("venue")) != "the black lab"
            or triage.words(candidate.get("city")) != CITY
            or str(candidate.get("department")) != "59"
            or candidate.get("sourcePage") != SOURCE_URL):
        raise ValueError("Identité de la salle et agenda source incompatibles")
    official_url = candidate.get("sourceUrl")
    if not isinstance(official_url, str) or adapter.official_slug(official_url) is None:
        raise ValueError("URL individuelle officielle Black Lab requise")
    if not isinstance(page, str) or len(page) > 500_000:
        raise ValueError("Fiche officielle illisible")
    official_source = {
        "name": "The Black Lab", "city": "Wasquehal",
        "department": "59", "url": SOURCE_URL,
    }
    fresh = adapter.detail_candidate(
        page, official_url, official_source, today.isoformat()
    )
    for key in ("sourceUrl", "date", "source", "name", "classification",
                "venue", "city", "department"):
        if fresh.get(key) != candidate.get(key):
            raise ValueError("Donnée officielle modifiée ou non identique: " + key)
    if fresh.get("date") <= today.isoformat():
        raise ValueError("Concert non futur")
    if not fresh.get("classification") or fresh.get("localTime") is not None:
        raise ValueError("Preuve de genre ou d'horaire incertaine")
    if not isinstance(catalogue, dict) or not all(
        isinstance(catalogue.get(key), list)
        for key in ("artists", "venues", "events")
    ):
        raise ValueError("Catalogue non conforme")

    # Only a title describing one EXACT existing canonical artist is admitted.
    title = fresh["name"]
    if any(token in title for token in (" + ", " & ", " / ", " feat.", " ft. ", " w/ ")):
        raise ValueError("Affiche multi-artistes: revue nominative nécessaire")
    if DANGEROUS_TITLE.search(triage.words(title)):
        raise ValueError("Titre de spectacle, cover, festival ou statut ambigu")
    matches = [a for a in catalogue["artists"]
               if triage.words(a.get("name")) == triage.words(title)]
    if len(matches) != 1 or not matches[0].get("id"):
        raise ValueError("Un seul artiste déjà identifié et canonique requis")
    performer = matches[0]

    # Discovery parser excludes cancellation/changed date in the masthead.
    # Recheck the substantial event detail as well, not adjacent listings.
    doc = adapter._Parse()
    doc.feed(page)
    detail = adapter.fold(" ".join(doc.parts[doc.heading_end or 0:
                                             (doc.heading_end or 0) + 65]))
    if adapter.CANCEL.search(detail):
        raise ValueError("Annonce de report, déplacement ou annulation")
    venues = [v for v in catalogue["venues"] if v.get("id") == VENUE_ID]
    if len(venues) != 1 or triage.words(venues[0].get("city")) != CITY:
        raise ValueError("Salle géolocalisée inconnue ou ambiguë")
    if not all(venues[0].get(k) is not None for k in ("latitude", "longitude")):
        raise ValueError("Géolocalisation de la salle non vérifiée")
    aid = performer["id"]
    if any(e.get("officialUrl") == official_url or
           (e.get("date") == fresh["date"] and
            e.get("venueId") == VENUE_ID and
            aid in e.get("artistIds", []))
           for e in catalogue["events"]):
        raise ValueError("Concert déjà publié ou même artiste et salle/date")
    event_id = ("go-c-" + fresh["date"].replace("-", "") +
                "-wasquehal-" + aid)
    if len(event_id) > 150 or any(e.get("id") == event_id
                                  for e in catalogue["events"]):
        raise ValueError("Collision d'identifiant")
    return {
        "reviewDecision": "approved",
        "reviewedBy": "automated-official-recheck",
        "reviewedAt": today.isoformat(),
        "officialEvidence": [{
            "url": official_url,
            "proofType": "official-venue-detail",
            "checkedAt": today.isoformat(),
            "checkedFields": ["artists", "date", "venue", "genre"],
            "officialArtistNames": [performer["name"]],
            "sourceStructure": "official-event-single-known-artist-recheck",
            "notes": "Fiche officielle relue; artiste canonique connu, date, salle et genre concordants; heure inconnue.",
        }],
        "event": {
            "id": event_id, "title": performer["name"], "date": fresh["date"],
            "time": None, "artistIds": [aid], "venueId": VENUE_ID,
            "genres": fresh["classification"], "status": "confirmed",
            "officialUrl": official_url, "sourceType": "salle",
            "organizer": "The Black Lab",
        },
        "newArtists": [],
    }
