#!/usr/bin/env python3
"""Importer une référence RadioStation V64 en CANDIDATS du catalogue central.

Lecture locale uniquement, sans réseau ni déploiement, aucune admission.
Les IDs GO sont attribués explicitement et persistés dans le résultat.
Si un catalogue précédent est donné, ses fiches restent inchangées :
les différences détectées sont à arbitrer, jamais appliquées silencieusement.

Exemple:
  python tools/radio_catalog_bootstrap_import_v1.py \
    --source assets/catalog/bootstrap_catalog.json \
    --as-of 2026-11-15T09:00:00Z \
    --output /tmp/catalog_staging.json --report /tmp/catalog_import_report.json
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from radio_catalog_guard import safe_url, validate_catalog

ID_PATTERN = re.compile(r"^go-station-(\d{6,})$")


def strval(value):
    return value.strip() if isinstance(value, str) else ""


def aliases_for(legacy):
    aliases = [strval(legacy.get("id"))]
    for variant in legacy.get("streamVariants") or []:
        if isinstance(variant, dict):
            aliases.append(strval(variant.get("stationId")))
    return sorted(set(x for x in aliases if x))


def normalize_country(value):
    country = strval(value).upper()
    return country if len(country) == 2 and country.isalpha() else None


def to_positive_int(value):
    try:
        parsed = int(value)
        return parsed if parsed > 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def legacy_streams(legacy):
    raw = [{
        "url": legacy.get("streamUrl"),
        "codec": legacy.get("codec"),
        "bitrate": legacy.get("bitrate")
    }]
    raw.extend(
        {"url": row.get("streamUrl"), "codec": row.get("codec"),
         "bitrate": row.get("bitrate")}
        for row in legacy.get("streamVariants", [])
        if isinstance(row, dict)
    )
    result = []
    seen = set()
    for row in raw:
        url = strval(row.get("url"))
        if not url or url in seen:
            continue
        if not safe_url(url):
            raise ValueError("source contains an invalid/unsafe stream URL")
        seen.add(url)
        result.append({
            "stream_id": f"legacy-stream-{len(result)+1:03d}",
            "url": url,
            "priority": len(result),
            "protocol": url.split(":", 1)[0].lower(),
            "codec": strval(row.get("codec"))[:40] or None,
            "bitrate_kbps": to_positive_int(row.get("bitrate")),
            "state": "candidate",
            "last_checked_at": None,
            "previous_urls": [],
        })
    return result


def import_legacy(legacy_root, *, as_of, previous=None):
    source = legacy_root.get("stations") if isinstance(legacy_root, dict) else legacy_root
    if not isinstance(source, list) or not source:
        raise ValueError("source must contain a non-empty stations array")
    previous_records = {}
    existing_alias_owner = {}
    if previous is not None:
        for item in previous.get("stations", []) + previous.get("tombstones", []):
            goid = item.get("go_station_id")
            if not isinstance(goid, str) or goid in previous_records:
                raise ValueError("previous catalog has invalid or duplicate IDs")
            previous_records[goid] = item
            for alias in item.get("legacy_aliases", []):
                owner = existing_alias_owner.setdefault(alias, goid)
                if owner != goid:
                    raise ValueError(f"previous catalog has alias conflict: {alias}")
        errors = validate_catalog(previous, mode="staging")
        if errors:
            raise ValueError("previous catalog invalid: " + "; ".join(errors[:3]))
    next_number = max(
        (int(match.group(1)) for goid in previous_records
         if (match := ID_PATTERN.fullmatch(goid))),
        default=0
    )
    created = []
    retained = []
    unchanged = 0
    unmatched_aliases = 0
    warnings = []
    for original in sorted(source, key=lambda s: strval(s.get("id")) if isinstance(s, dict) else ""):
        if not isinstance(original, dict):
            raise ValueError("source contains a non-object station")
        aliases = aliases_for(original)
        if not aliases:
            raise ValueError("legacy station without ID or variants")
        owners = {existing_alias_owner[alias] for alias in aliases if alias in existing_alias_owner}
        if len(owners) > 1:
            raise ValueError(f"legacy station maps to multiple permanent GO IDs: {aliases}")
        if owners:
            goid = next(iter(owners))
            if goid not in previous_records:
                raise ValueError(f"duplicate alias between distinct source stations: {aliases}")
            unchanged += 1
            known_aliases = set(previous_records[goid].get("legacy_aliases", []))
            extra_aliases = sorted(set(aliases) - known_aliases)
            if extra_aliases:
                warnings.append({"go_station_id": goid, "unreviewed_alias_candidates": extra_aliases})
            continue
        next_number += 1
        goid = f"go-station-{next_number:06d}"
        primary_id = strval(original.get("id"))
        ids = [primary_id] + [x for x in aliases if x != primary_id] if primary_id else aliases
        streams = legacy_streams(original)
        if not streams:
            raise ValueError(f"legacy station {primary_id} has no usable streams")
        homepage = strval(original.get("homepage"))
        record = {
            "go_station_id": goid,
            "display_name": strval(original.get("name")) or "Radio sans nom (à qualifier)",
            "country_code": normalize_country(original.get("countryCode")),
            "genres": [strval(original.get("genre")) or "Metal"],
            "homepage": homepage if homepage and safe_url(homepage) else None,
            "radio_browser_uuids": [{"uuid": x, "state": "current"} for x in ids],
            "legacy_aliases": aliases,
            "status": {"state": "active", "reason_code": "legacy_bootstrap_unverified", "changed_at": as_of},
            "streams": streams,
            # Aucune empreinte de contenu pour ces images historiques :
            # ne surtout pas publier un logo non qualifié avec un hash inventé.
            "logo": None,
            "editorial": {"admission_state": "legacy_preserved", "reviewed_at": None, "evidence_refs": []},
        }
        created.append(record)
        for alias in aliases:
            existing_alias_owner[alias] = goid
        if not homepage or not safe_url(homepage):
            warnings.append({"go_station_id": goid, "invalid_or_empty_homepage": True})
        if strval(original.get("logoUrl")):
            unmatched_aliases += 1
    if previous:
        # Ne jamais reclasser/modifier automatiquement une entrée déjà connue.
        retained = previous.get("stations", [])
        tombstones = previous.get("tombstones", [])
        sequence = previous["release_sequence"] + 1
    else:
        tombstones = []
        sequence = 1
    result = {
        "schema_version": 1,
        "catalog_id": "grosses-ondes-radio",
        "release_sequence": sequence,
        "generated_at": as_of,
        "stations": sorted([*retained, *created], key=lambda r: r["go_station_id"]),
        "tombstones": tombstones,
    }
    errors = validate_catalog(result, mode="staging", previous=previous)
    if errors:
        raise ValueError("staging result is invalid: " + "; ".join(errors[:8]))
    report = {
        "source_kind": "historical_bootstrap_candidate_import",
        "source_station_count": len(source),
        "new_unreviewed_stations": len(created),
        "unchanged_existing_stations": unchanged,
        "catalog_total_stations": len(result["stations"]),
        "unique_historical_aliases": len(existing_alias_owner),
        "source_records_with_legacy_logo_url": unmatched_aliases,
        "unreviewed_candidate_streams": sum(len(s["streams"]) for s in created),
        "warnings": warnings,
        "publish_ready": False,
        "note": "Staging only. No stream verification, editorial approval, image SHA or deployment.",
    }
    return result, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--as-of", type=str, default=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    for path in (args.output, args.report):
        if path.exists():
            parser.error(f"refusing to overwrite existing file: {path}")
    root = json.loads(args.source.read_text(encoding="utf-8"))
    previous = json.loads(args.previous.read_text(encoding="utf-8")) if args.previous else None
    result, report = import_legacy(root, as_of=args.as_of, previous=previous)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"STAGING ONLY: {report['catalog_total_stations']} stations, {report['unique_historical_aliases']} aliases; no publication.")


if __name__ == "__main__":
    main()
