#!/usr/bin/env python3
"""Prévisualisation NON DESTRUCTIVE de la migration des favoris Grosses Ondes.

Cet outil ne modifie jamais les données du téléphone ou les préférences V64.
Ne jamais commiter de véritables favoris utilisateur, ni de traces de lecture.
Exemple sur exports volontaires et LOCAUX :
  python tools/radio_catalog_favorites_preview.py \
    --aliases staging/radio-catalog/v1/legacy-aliases-20261115.json \
    --favorites /tmp/favorites.json --output /tmp/favorites-preview.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def build_lookup(alias_document):
    rows = alias_document.get("aliases") if isinstance(alias_document, dict) else alias_document
    if not isinstance(rows, list):
        raise ValueError("aliases must be a list of {legacy_id, go_station_id}")
    lookup = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"invalid alias row {index}")
        legacy = row.get("legacy_id")
        goid = row.get("go_station_id")
        if not isinstance(legacy, str) or not legacy or not isinstance(goid, str) or not goid:
            raise ValueError(f"invalid alias mapping {index}")
        old = lookup.setdefault(legacy, goid)
        if old != goid:
            raise ValueError(f"alias collision for {legacy}: {old} / {goid}")
    return lookup


def preview_favorites(favorite_ids, lookup, statuses=None):
    if not isinstance(favorite_ids, list):
        raise ValueError("favorites must be a JSON array")
    if not isinstance(lookup, dict):
        raise ValueError("lookup must be dict")
    statuses = statuses or {}
    known_goids = set(lookup.values())
    projected = []
    unresolved = []
    duplicates = []
    seen_goid = set()
    seen_legacy = set()
    quarantined = []
    retired = []
    for legacy in favorite_ids:
        if not isinstance(legacy, str) or not legacy:
            raise ValueError("empty or non-string legacy favorite")
        if legacy in seen_legacy:
            duplicates.append(legacy)
        seen_legacy.add(legacy)
        goid = lookup.get(legacy)
        if goid is None and legacy in known_goids:
            goid = legacy
        if goid is None:
            if legacy not in unresolved:
                unresolved.append(legacy)
            continue
        if goid not in seen_goid:
            seen_goid.add(goid)
            projected.append(goid)
            if statuses.get(goid) == "quarantined":
                quarantined.append(goid)
            elif statuses.get(goid) == "retired":
                retired.append(goid)
    return {
        "legacy_favorites_unchanged": list(favorite_ids),
        "go_station_ids_preview": projected,
        "unresolved_legacy_ids_kept": unresolved,
        "duplicate_input_legacy_ids": duplicates,
        "quarantined_still_favorited": quarantined,
        "retired_still_favorited": retired,
        "safe_to_delete_old_favorites": False,
        "note": "Preview only. Write new GO favorites to a NEW key; never overwrite the V64 key.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--aliases", required=True, type=Path)
    parser.add_argument("--favorites", required=True, type=Path)
    parser.add_argument("--catalog", type=Path, help="Optionnel : ajouter statuts des radios aux résultats")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("refusing to overwrite preview output")
    aliases = json.loads(args.aliases.read_text(encoding="utf-8"))
    favorites = json.loads(args.favorites.read_text(encoding="utf-8"))
    statuses = {}
    if args.catalog:
        doc = json.loads(args.catalog.read_text(encoding="utf-8"))
        for station in doc.get("stations", []):
            statuses[station["go_station_id"]] = station.get("status", {}).get("state")
        for tomb in doc.get("tombstones", []):
            statuses[tomb["go_station_id"]] = "retired"
    report = preview_favorites(favorites, build_lookup(aliases), statuses)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Preview: {len(report['go_station_ids_preview'])} GO favorites, {len(report['unresolved_legacy_ids_kept'])} unresolved (kept).")


if __name__ == "__main__":
    main()
