"""Offline, fail-closed validation of the permanent family-places catalogue.

These are permanent places, NOT sessions. Do not generate dated outings
from opening hours, a season period or an exhibition range.
"""
from datetime import date
import json
import math
from pathlib import Path
import re
from urllib.parse import urlparse
import unicodedata

CATEGORIES = {
    "centre-eveil-artistique",
    "ludotheque",
    "musee-enfants",
    "mediatheque-jeunesse",
    "espace-culturel-enfants",
    "espace-sensoriel",
    "theatre-jeune-public",
}
REQUIRED = {
    "id", "name", "kind", "category", "category_label",
    "city", "department", "region", "postal_code", "address",
    "lat", "lng", "geo_precision", "age_min", "age_max",
    "admission", "activities", "reservation_note",
    "official_url", "geo_source_url", "reviewed_at",
    "is_publicly_accessible",
}
FORBIDDEN = {"date_start", "date_end", "time", "timings", "sessions",
             "firstdate_begin", "lastdate_begin", "startDate", "endDate"}


def norm(s):
    normalized = unicodedata.normalize("NFKD", str(s or "").lower())
    return " ".join(re.sub(r"[^a-z0-9]+", " ", "".join(
        c for c in normalized if not unicodedata.combining(c))).split())


def hostname(url):
    if not isinstance(url, str):
        raise ValueError("URL source non textuelle")
    p = urlparse(url)
    if (p.scheme != "https" or not p.hostname or p.username or p.password
            or p.fragment or p.hostname in {"localhost", "127.0.0.1"}):
        raise ValueError("URL source non sûre")
    return p.hostname.lower()


def validate(doc):
    if not isinstance(doc, dict) or set(doc) != {"version", "updated_at", "places"}:
        raise ValueError("Schéma de lieux non conforme")
    if doc["version"] != 1 or not isinstance(doc["places"], list):
        raise ValueError("Version ou tableau de lieux inconnu")
    if len(doc["places"]) > 5000:
        raise ValueError("Catalogue de lieux trop volumineux")
    try:
        stamp = date.fromisoformat(doc["updated_at"])
    except (TypeError, ValueError):
        raise ValueError("Date de catalogue incorrecte")
    ids, seen = set(), set()
    for p in doc["places"]:
        if not isinstance(p, dict) or set(p) != REQUIRED or set(p) & FORBIDDEN:
            raise ValueError("Champs de lieu incorrects")
        if (not isinstance(p["id"], str) or
                not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", p["id"]) or
                p["id"] in ids):
            raise ValueError("ID de lieu incorrect ou en doublon")
        ids.add(p["id"])
        if p["kind"] != "lieu-permanent" or p["category"] not in CATEGORIES:
            raise ValueError("Type ou catégorie hors nomenclature")
        for key in ("name", "city", "department", "region", "postal_code",
                    "address", "category_label", "admission",
                    "reservation_note"):
            if not isinstance(p[key], str) or not p[key].strip():
                raise ValueError("Champ de lieu vide : " + key)
        if p["is_publicly_accessible"] is not True:
            raise ValueError("Lieu non accessible au public")
        if not re.fullmatch(r"\d{5}", p["postal_code"]):
            raise ValueError("Code postal invalide")
        if not norm(p["city"]) in norm(p["address"]):
            raise ValueError("Adresse et ville incompatibles")
        # Explicitly unknown ages are permitted as a pair of JSON nulls,
        # never inferred as 0-18. Existing numeric records remain unchanged.
        age_min, age_max = p["age_min"], p["age_max"]
        if (age_min is None) != (age_max is None):
            raise ValueError("Age inconnu partiel")
        if age_min is not None:
            if type(age_min) not in (int, float) or type(age_max) not in (int, float):
                raise ValueError("Age invalide")
            if not 0 <= age_min <= age_max <= 18:
                raise ValueError("Age hors plage")
        if (type(p["lat"]) not in (int, float) or type(p["lng"]) not in (int, float)
                or not math.isfinite(p["lat"]) or not math.isfinite(p["lng"])
                or not -90 <= p["lat"] <= 90 or not -180 <= p["lng"] <= 180
                or p["geo_precision"] != "lieu"):
            raise ValueError("GPS du lieu non documenté")
        if (not isinstance(p["activities"], list) or
                not 1 <= len(p["activities"]) <= 12 or
                not all(isinstance(v, str) and v.strip() for v in p["activities"])):
            raise ValueError("Activités invalides")
        if hostname(p["official_url"]) == hostname(p["geo_source_url"]):
            raise ValueError("La source géographique doit être indépendante")
        if (not p["geo_source_url"].startswith("https://mapcarta.com/fr/")
                and not p["geo_source_url"].startswith("https://www.openstreetmap.org/")
                and not p["geo_source_url"].startswith("https://www.tofromfrance.com/")):
            raise ValueError("Provenance GPS non autorisée")
        try:
            verified = date.fromisoformat(p["reviewed_at"])
        except (ValueError, TypeError):
            raise ValueError("Date de revue invalide")
        if verified > stamp or (stamp - verified).days > 365:
            raise ValueError("Vérification de lieu périmée")
        sig = (norm(p["name"]), norm(p["city"]), norm(p["address"]))
        if sig in seen:
            raise ValueError("Lieu permanent déjà répertorié")
        seen.add(sig)
    return len(ids)


def assert_append_only(old, new):
    """Keep old listings byte-identical; corrections require a dedicated review."""
    if not isinstance(old, dict) or not isinstance(new, dict):
        raise ValueError("Catalogues de lieux malformés")
    validate(old)
    validate(new)
    earlier = {p["id"]: p for p in old["places"]}
    newer = {p["id"]: p for p in new["places"]}
    if any(key not in newer or newer[key] != val for key, val in earlier.items()):
        raise ValueError("Lieu existant supprimé ou modifié : revue séparée exigée")
    if new["updated_at"] < old["updated_at"]:
        raise ValueError("Mise à jour des lieux rétrodatée")


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("file", type=Path)
    parser.add_argument("--previous", type=Path)
    args = parser.parse_args()
    current = json.loads(args.file.read_text(encoding="utf-8"))
    n = validate(current)
    if args.previous:
        previous = json.loads(args.previous.read_text(encoding="utf-8"))
        assert_append_only(previous, current)
    print(f"Catalogue des lieux permanents vérifié : {n} lieu(x). Aucune séance créée.")


if __name__ == "__main__":
    main()
