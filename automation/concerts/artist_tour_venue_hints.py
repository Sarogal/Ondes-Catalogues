#!/usr/bin/env python3
"""Rapprochements *documentés* de salles détectées par tournées.

Les noms des espaces, communes promotionnelles et salles principales ne sont
jamais fusionnés par simple heuristique. Les corrections explicites ajoutent
des annotations de revue au candidat et ne constituent PAS une approbation.
"""
from __future__ import annotations

import json
from pathlib import Path

import discover
import livenation_tour_adapter

ROOT = Path(__file__).resolve().parent
DEFAULT_HINTS = ROOT / "artist-tour-venue-hints.json"
SCHEMA = "grossesondes.concert.artist_tour_venue_hints.v1"


def key(artist_id, city, venue):
    return (str(artist_id or ""), livenation_tour_adapter.normalized_city(city),
            discover.norm(venue))


def validate_hints(document, catalogue):
    if not isinstance(document, dict) or document.get("schema") != SCHEMA:
        raise ValueError("Schéma de rapprochements de salles invalide")
    hints = document.get("hints")
    if not isinstance(hints, list):
        raise ValueError("Rapprochements manquants")
    artist_ids = {x.get("id") for x in catalogue.get("artists", []) if isinstance(x, dict)}
    venues = {x.get("id"): x for x in catalogue.get("venues", []) if isinstance(x, dict)}
    mapped = {}
    for row in hints:
        if not isinstance(row, dict):
            raise ValueError("Rapprochement de salle invalide")
        if row.get("artistId") not in artist_ids:
            raise ValueError("Artiste inconnu dans un rapprochement")
        if not all(isinstance(row.get(field), str) and row[field].strip()
                   for field in ("reportedCity", "reportedVenue", "canonicalCity",
                                 "officialEvidenceUrl")):
            raise ValueError("Lieu, ville canonique ou preuve absents")
        if not row["officialEvidenceUrl"].startswith("https://"):
            raise ValueError("La preuve d'alias doit être une URL HTTPS")
        known = row.get("canonicalVenueId")
        if known is not None:
            if known not in venues:
                raise ValueError("Identifiant de salle canonique inconnu")
            if (livenation_tour_adapter.normalized_city(venues[known].get("city"))
                    != livenation_tour_adapter.normalized_city(row["canonicalCity"])):
                raise ValueError("Contradiction entre identifiant et commune de la salle")
        if row.get("roomWithinVenue") is True and known is None:
            raise ValueError("Une sous-salle requiert une salle parent vérifiée")
        index = key(row["artistId"], row["reportedCity"], row["reportedVenue"])
        if not all(index) or index in mapped:
            raise ValueError("Rapprochement vide ou dupliqué")
        mapped[index] = row
    return mapped


def annotate(candidates, catalogue, document):
    """Préserve l'ID et le libellé issu de la source pour l'audit Git."""
    hints = validate_hints(document, catalogue)
    output, hits = [], []
    for candidate in candidates:
        row = dict(candidate)
        hint = hints.get(key(row.get("artistId"), row.get("city"), row.get("venue")))
        if hint:
            canonical_id = hint.get("canonicalVenueId")
            if (row.get("venueIdIfKnown") not in (None, canonical_id)
                    and canonical_id is not None):
                raise ValueError("Alias contradictoire avec la salle déjà reconnue")
            if canonical_id:
                row["venueIdIfKnown"] = canonical_id
                row["newVenueToReview"] = False
            different = (livenation_tour_adapter.normalized_city(row.get("city"))
                         != livenation_tour_adapter.normalized_city(hint["canonicalCity"]))
            row["venueReconciliation"] = {
                "sourceVenue": row.get("venue"),
                "sourceCity": row.get("city"),
                "canonicalVenueId": canonical_id,
                "canonicalCity": hint["canonicalCity"],
                "roomWithinVenue": bool(hint.get("roomWithinVenue")),
                "cityCorrectionRequired": different,
                "officialEvidenceUrl": hint["officialEvidenceUrl"],
                "status": "review_only",
            }
            # Ne pas réécrire la ville d'origine : sa traçabilité est nécessaire.
            row["venueAddressToVerify"] = True
            row["coordinatesToVerify"] = True
            row["publicationAllowed"] = False
            row["reviewRequired"] = True
            hits.append(row["candidateId"])
        output.append(row)
    return output, hits


def load(path=DEFAULT_HINTS):
    return json.loads(Path(path).read_text(encoding="utf-8"))
