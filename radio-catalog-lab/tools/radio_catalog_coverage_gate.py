#!/usr/bin/env python3
"""Blocage de publication si la migration oublie un UUID historique admis.

Lecture seule, aucune admission, aucune suppression, aucun réseau.
Le filtre d'admission Dart sert de seuil de couverture, PAS d'autorité éditoriale.
En plus, l'index des favoris historiques peut être exigé intégralement.

 python tools/radio_catalog_coverage_gate.py \
   --admission lib/data/radio_browser_admission.dart \
   --catalog staging/radio-catalog/v1/bootstrap-stations-20261115.json \
   --historical-aliases staging/radio-catalog/v1/legacy-aliases-20261115.json
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

UUID_RE = re.compile(r"'([a-fA-F0-9]{8}-(?:[a-fA-F0-9]{4}-){3}[a-fA-F0-9]{12})'")


def dart_uuid_set(source: str, variable: str) -> set[str]:
    if not isinstance(source, str) or not re.fullmatch(r"[a-zA-Z_]\w*", variable):
        raise ValueError("invalid Dart input")
    expression = re.search(r"\b" + re.escape(variable) + r"\s*=\s*<String>\s*\{(?P<body>.*?)\}\s*;", source, re.S)
    if not expression:
        raise ValueError(f"missing Dart UUID set {variable}; refuse to assume empty")
    # Remove both line and block comments before reading literals; comments aren't IDs.
    body = re.sub(r"/\*.*?\*/|//[^\n]*", "", expression.group("body"), flags=re.S)
    return {match.lower() for match in UUID_RE.findall(body)}


def station_alias_owners(catalog: dict) -> tuple[dict[str, str], list[str]]:
    if not isinstance(catalog, dict):
        raise ValueError("invalid catalog")
    owners = {}
    collisions = []
    for station in catalog.get("stations", []) + catalog.get("tombstones", []):
        if not isinstance(station, dict):
            raise ValueError("invalid station record")
        owner = station.get("go_station_id")
        for alias in station.get("legacy_aliases", []):
            if not isinstance(alias, str) or not alias:
                raise ValueError("empty or invalid historical alias")
            previous = owners.setdefault(alias.lower(), owner)
            if previous != owner:
                collisions.append(alias)
    return owners, collisions


def coverage_report(source: str, catalog: dict, baseline: dict | None = None) -> dict:
    allowed = dart_uuid_set(source, "allowedStationIds")
    rejected = dart_uuid_set(source, "editoriallyRejectedStationIds")
    admissible = allowed - rejected
    owners, collisions = station_alias_owners(catalog)
    baseline_aliases = set()
    if baseline is not None:
        rows = baseline.get("aliases")
        if not isinstance(rows, list):
            raise ValueError("invalid historical alias index")
        baseline_aliases = {
            row["legacy_id"].lower() for row in rows
            if isinstance(row, dict) and isinstance(row.get("legacy_id"), str)
        }
        if len(baseline_aliases) != len(rows):
            raise ValueError("duplicate/invalid historical alias index")
    missing_admissible = sorted(admissible - owners.keys())
    missing_baseline = sorted(baseline_aliases - owners.keys())
    ok = not missing_admissible and not missing_baseline and not collisions
    return {
        "status": "PASS_COVERAGE_ONLY_NOT_EDITORIAL_APPROVAL" if ok else "BLOCK_RELEASE_MISSING_LEGACY_IDENTITIES",
        "admission_allowed_count": len(allowed),
        "admission_editorially_rejected_count": len(rejected),
        "admission_admissible_count": len(admissible),
        "catalog_preserved_alias_count": len(owners),
        "historical_baseline_alias_count": len(baseline_aliases),
        "missing_admissible_uuid_count": len(missing_admissible),
        "missing_admissible_uuids": missing_admissible,
        "missing_historical_alias_count": len(missing_baseline),
        "missing_historical_aliases": missing_baseline,
        "alias_collisions": sorted(set(collisions)),
        "ready_to_publish": False,
        "coverage_gate_passed": ok,
        "note": "A passing coverage gate is not a publication authorization. Qualification, streams, safety, logo SHA and human review are separate.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--admission", required=True, type=Path)
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--historical-aliases", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.out and args.out.exists():
        parser.error("refusing to overwrite an existing coverage report")
    report = coverage_report(
        args.admission.read_text(encoding="utf-8"),
        json.loads(args.catalog.read_text(encoding="utf-8")),
        json.loads(args.historical_aliases.read_text(encoding="utf-8")) if args.historical_aliases else None,
    )
    if args.out:
        args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                            encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "missing_admissible": report["missing_admissible_uuid_count"],
        "missing_historical_aliases": report["missing_historical_alias_count"],
        "collisions": len(report["alias_collisions"]),
    }))
    if not report["coverage_gate_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
