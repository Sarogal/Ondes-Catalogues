#!/usr/bin/env python3
"""Compare des UUID Radio Browser à un bootstrap historique sans jamais fusionner.

Entrées: evidence JSON produit en lecture seule, bootstrap JSON, index des alias.
Sortie: recommandations NON EXECUTABLES à arbitrer humainement. Aucune requête réseau.

Exemple:
 python tools/radio_catalog_uuid_reconcile.py --evidence staging/radio-catalog/v1/admission-uuid-evidence-20261115.json --bootstrap assets/catalog/bootstrap_catalog.json --aliases staging/radio-catalog/v1/legacy-aliases-20261115.json --out /tmp/uuid-review.json
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit


def canonical_url(value: object, *, homepage: bool = False) -> str:
    """N'intervertit jamais les chemins ni les paramètres des flux audio."""
    if not isinstance(value, str) or not value.strip():
        return ""
    try:
        parts = urlsplit(value.strip())
        if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
            return ""
        if parts.username is not None or parts.password is not None:
            return ""
        port = parts.port
        host = parts.hostname.lower().rstrip(".")
        netloc = host + (f":{port}" if port is not None else "")
        path = parts.path.rstrip("/") if homepage else parts.path
        query = parts.query
        return parts.scheme.lower() + "://" + netloc + path + ("?" + query if query else "")
    except ValueError:
        return ""


def canonical_name(value: object) -> str:
    if not isinstance(value, str):
        return ""
    normalized = unicodedata.normalize("NFKD", value).casefold()
    return re.sub(r"\s+", " ", re.sub(r"[^\w]+", " ", normalized)).strip()


def evaluate(evidence: dict, bootstrap: dict, alias_index: dict) -> dict:
    if not isinstance(evidence, dict) or not isinstance(evidence.get("rows"), list):
        raise ValueError("invalid evidence report")
    stations = bootstrap.get("stations", [])
    if not isinstance(stations, list):
        raise ValueError("invalid bootstrap")
    mapping = {}
    for row in alias_index.get("aliases", []):
        legacy_id, go_id = row.get("legacy_id"), row.get("go_station_id")
        if not isinstance(legacy_id, str) or not isinstance(go_id, str):
            raise ValueError("invalid alias entry")
        if legacy_id in mapping and mapping[legacy_id] != go_id:
            raise ValueError("conflicting legacy alias mapping")
        mapping[legacy_id] = go_id

    def info(station: dict) -> dict:
        legacy_id = station.get("id")
        if legacy_id not in mapping:
            raise ValueError(f"bootstrap ID absent from alias index: {legacy_id}")
        return {"go_station_id": mapping[legacy_id], "name": station.get("name"),
                "legacy_station_id": legacy_id}

    rows = []
    classifications = {}
    seen = set()
    for incoming in evidence["rows"]:
        if not isinstance(incoming, dict):
            raise ValueError("invalid evidence row")
        uuid = incoming.get("uuid")
        if not isinstance(uuid, str) or uuid in seen or not uuid:
            raise ValueError("duplicate or missing UUID in evidence")
        seen.add(uuid)
        if not incoming.get("directory_found"):
            classification = "not_found_directory_recheck"
            matches = []
            names = []
            homes = []
        else:
            stream_keys = set()
            for u in (incoming.get("directory_stream_url"), incoming.get("directory_raw_stream_url")):
                key = canonical_url(u)
                if key:
                    stream_keys.add(key)
            label = canonical_name(incoming.get("directory_name"))
            homepage = canonical_url(incoming.get("directory_homepage"), homepage=True)
            matches = []
            names = []
            homes = []
            for station in stations:
                available = [station.get("streamUrl")]
                available.extend(v.get("streamUrl") for v in station.get("streamVariants", [])
                                 if isinstance(v, dict))
                audio = set(filter(None, (canonical_url(url) for url in available)))
                if audio.intersection(stream_keys):
                    matches.append(info(station))
                if label and canonical_name(station.get("name")) == label:
                    names.append(info(station))
                if homepage and canonical_url(station.get("homepage"), homepage=True) == homepage:
                    homes.append(info(station))
            if len(matches) > 1:
                classification = "ambiguous_shared_stream"
            elif len(matches) == 1:
                if any(n["go_station_id"] == matches[0]["go_station_id"] for n in names):
                    classification = "same_stream_and_name_review"
                else:
                    classification = "same_stream_different_name_review"
            elif names:
                classification = "same_name_only_review"
            elif homes:
                classification = "shared_homepage_only_no_merge"
            else:
                classification = "new_or_unlinked_candidate_review"
        classifications[classification] = classifications.get(classification, 0) + 1
        rows.append({
            "uuid": uuid,
            "directory_found": bool(incoming.get("directory_found")),
            "directory_name": incoming.get("directory_name") if incoming.get("directory_found") else None,
            "classification": classification,
            "exact_stream_matches": matches,
            "exact_name_matches": names,
            "shared_homepage_matches": homes,
            "approval": "HUMAN_REVIEW_REQUIRED",
            "auto_admit": False,
            "auto_merge": False,
            "delete_previous_alias": False,
        })
    return {
        "status": "REVIEW_ONLY_NON_PUBLISHABLE",
        "source_gap_file": evidence.get("source_gap_file"),
        "source_bootstrap_file": evidence.get("source_bootstrap_file"),
        "total_uuid_reviewed": len(rows),
        "classification_counts": dict(sorted(classifications.items())),
        "rows": rows,
        "guardrails": [
            "Nom + URL identiques = hypothèse forte, JAMAIS fusion automatique",
            "URL identique et nom différent = cas ambigu, pas d'alias automatiquement",
            "Même site officiel ne prouve pas qu'il s'agit du même canal",
            "UUID absent de l'API = garder dans la liste de contrôle, ne pas supprimer",
            "Aucune modification des GO IDs, favoris, logos, Android Auto ni du catalogue public",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--bootstrap", type=Path, required=True)
    parser.add_argument("--aliases", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("refusing to overwrite existing review")
    report = evaluate(
        json.loads(args.evidence.read_text(encoding="utf-8")),
        json.loads(args.bootstrap.read_text(encoding="utf-8")),
        json.loads(args.aliases.read_text(encoding="utf-8")),
    )
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    print(f"Review only: {report['total_uuid_reviewed']} UUID; no stations modified.")


if __name__ == "__main__":
    main()
