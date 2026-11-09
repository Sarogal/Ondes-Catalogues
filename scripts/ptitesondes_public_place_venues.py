"""Réutilisation strictement géographique des lieux permanents déjà publiés.

Aucun événement n'est homologué par ce module. Le JSON lieux est validé
indépendamment puis utilisé comme registre de points de bâtiments. Un match
exige ville et nom exacts (alias explicitement revu), jamais une similarité.
La preuve officielle de CHAQUE séance reste exigée par proof_text.py.
"""
import json
from pathlib import Path

from proof import norm
from ptitesondes_places import validate as validate_places

PUBLIC_PLACES = Path(__file__).resolve().parents[1] / "docs/ptitesondes/lieux.json"

# Uniquement les différences d'intitulé examinées entre les deux catalogues.
# Ne pas retirer arbitrairement les suffixes : "espace jeunesse" peut désigner
# une autre adresse dans une commune.
REVIEWED_ALIASES = {
    "marseille-bibliotheque-alcazar": ("Bibliothèque de l'Alcazar",),
}


def approved_public_venues(catalogue_path=PUBLIC_PLACES):
    """Fail closed on unknown schema, stale review, missing or corrupted file."""
    try:
        raw = Path(catalogue_path).read_bytes()
        if len(raw) > 1_000_000:
            return []
        doc = json.loads(raw)
        validate_places(doc)
    except (OSError, ValueError, TypeError, UnicodeError):
        return []
    return [{
        "city": item["city"],
        "aliases": [item["name"], *REVIEWED_ALIASES.get(item["id"], ())],
        "lat": item["lat"],
        "lng": item["lng"],
        "official": item["official_url"],
        "geo_source": item["geo_source_url"],
        "public_place_id": item["id"],
    } for item in doc["places"]]


def lookup_public_venue(city, venue, catalogue_path=PUBLIC_PLACES):
    """Find one and only one official building; no inferred town-center GPS."""
    if not isinstance(city, str) or not city.strip():
        return None
    if not isinstance(venue, str) or not venue.strip():
        return None
    matches = [
        item for item in approved_public_venues(catalogue_path)
        if norm(item["city"]) == norm(city)
        and norm(venue) in {norm(alias) for alias in item["aliases"]}
    ]
    return matches[0] if len(matches) == 1 else None
