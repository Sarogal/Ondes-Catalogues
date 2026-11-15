#!/usr/bin/env python3
"""Audit en lecture seule du manifeste et d'un cache de logos Grosses Ondes.

Ne contacte aucun serveur et ne modifie ni le cache ni les préférences.
Exemples:
  python tools/radio_logo_cache_preflight.py --manifest assets/data/logo_manifest_v1.json --catalog assets/catalog/bootstrap_catalog.json
  python tools/radio_logo_cache_preflight.py --manifest assets/data/logo_manifest_v1.json --catalog export/catalog.json --cache-dir export/grosses_ondes_station_logos_v2 --signatures export/installed_signatures.json --output boot1.json
  python tools/radio_logo_cache_preflight.py --manifest assets/data/logo_manifest_v1.json --catalog export/catalog.json --cache-dir export/grosses_ondes_station_logos_v2 --signatures export/installed_signatures.json --output boot2.json --compare boot1.json
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlsplit


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def stable_cache_name(url: str) -> str:
    """Même FNV-1a 64 bits que StationLogoDiskCache._stableKey (Dart)."""
    value = 0xCBF29CE484222325
    for byte in url.encode("utf-8"):
        value ^= byte
        value = (value * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return f"{value:016x}.img"


def active_ids_from_catalog(catalog):
    stations = catalog.get("stations", []) if isinstance(catalog, dict) else catalog
    if not isinstance(stations, list):
        raise ValueError("Le catalogue doit être une liste ou un objet avec stations[].")
    active = set()
    for station in stations:
        if not isinstance(station, dict):
            continue
        if str(station.get("id", "")).strip():
            active.add(str(station["id"]).strip())
        variants = station.get("streamVariants", [])
        if isinstance(variants, list):
            for variant in variants:
                if isinstance(variant, dict):
                    alias = str(variant.get("stationId", "")).strip()
                    if alias:
                        active.add(alias)
    return stations, active


def scan(manifest, catalog, signatures=None, cache_dir=None):
    entries = manifest.get("entries", [])
    if not isinstance(entries, list):
        raise ValueError("Le manifeste ne contient pas entries[].")
    stations, active_ids = active_ids_from_catalog(catalog)
    by_url = Counter()
    invalid = []
    effective = []
    ids_seen = set()
    resolution_warning = 0
    for entry in entries:
        if not isinstance(entry, dict):
            invalid.append("non-object")
            continue
        station_id = str(entry.get("id", "")).strip()
        url = str(entry.get("url", "")).strip()
        revision = entry.get("revision")
        parts = urlsplit(url)
        if not station_id or station_id in ids_seen or not parts.hostname or parts.scheme != "https" or not isinstance(revision, int) or revision <= 0:
            invalid.append(station_id or "(empty)")
            continue
        ids_seen.add(station_id)
        by_url[url] += 1
        width = int(entry.get("width") or 0)
        height = int(entry.get("height") or 0)
        if min(width, height) <= 64 or width * height < 8192:
            resolution_warning += 1
        if station_id in active_ids:
            effective.append(entry)
    urls_to_entries = defaultdict(list)
    for entry in effective:
        urls_to_entries[entry["url"]].append(entry["id"])
    output = {
        "manifest_version": manifest.get("version"),
        "manifest_entries": len(entries),
        "manifest_unique_urls": len(by_url),
        "manifest_shared_url_groups": sum(count > 1 for count in by_url.values()),
        "manifest_shared_url_entries": sum(count for count in by_url.values() if count > 1),
        "manifest_very_low_dimensions": resolution_warning,
        "manifest_invalid_entries": invalid,
        "catalog_stations": len(stations),
        "active_station_and_variant_ids": len(active_ids),
        "applicable_logo_entries": len(effective),
        "applicable_unique_image_urls": len(urls_to_entries),
        "device_inspection": "unavailable",
        "pending": [],
        "reason_counts": {},
        "pending_unique_urls": None,
        "requested_image_bytes_estimate": None,
    }
    if signatures is None or cache_dir is None:
        return output
    if isinstance(signatures, dict) and "installed_signatures" in signatures:
        signatures = signatures["installed_signatures"]
    if not isinstance(signatures, dict):
        raise ValueError("Le JSON de signatures doit être un objet id -> revision|url.")
    cache_root = Path(cache_dir)
    if not cache_root.is_dir():
        raise ValueError(f"Répertoire de cache introuvable : {cache_root}")
    pending = []
    reasons = Counter()
    pending_urls = set()
    pending_bytes = {}
    for entry in effective:
        url = entry["url"]
        station_id = entry["id"]
        file = cache_root / stable_cache_name(url)
        exists = file.is_file() and file.stat().st_size > 0
        installed_signature = signatures.get(station_id)
        expected = f"{entry['revision']}|{url}"
        entry_reasons = []
        if not exists:
            entry_reasons.append("file_missing_or_empty")
        if installed_signature is None or installed_signature == "":
            entry_reasons.append("signature_missing")
        elif installed_signature != expected:
            entry_reasons.append("signature_mismatch")
        if not entry_reasons:
            continue
        reasons.update(entry_reasons)
        pending_urls.add(url)
        pending_bytes[url] = max(pending_bytes.get(url, 0), int(entry.get("sizeBytes") or 0))
        pending.append({
            "station_id": station_id,
            "cache_filename": stable_cache_name(url),
            "expected_revision": entry["revision"],
            "cached_file_bytes": file.stat().st_size if file.is_file() else 0,
            "reasons": entry_reasons,
        })
    output.update({
        "device_inspection": "exported_cache_and_signatures",
        "pending": sorted(pending, key=lambda item: item["station_id"]),
        "reason_counts": dict(sorted(reasons.items())),
        "pending_unique_urls": len(pending_urls),
        "requested_image_bytes_estimate": sum(pending_bytes.values()),
    })
    return output


def compare(previous, current):
    previous_pending = {row["station_id"] for row in previous.get("pending", [])}
    current_pending = {row["station_id"] for row in current.get("pending", [])}
    return {
        "same_manifest_version": previous.get("manifest_version") == current.get("manifest_version"),
        "same_applicable_entries": previous.get("applicable_logo_entries") == current.get("applicable_logo_entries"),
        "first_pending_entries": len(previous_pending),
        "second_pending_entries": len(current_pending),
        "persistently_pending_ids": sorted(previous_pending & current_pending),
        "new_pending_ids": sorted(current_pending - previous_pending),
        "resolved_ids": sorted(previous_pending - current_pending),
        "second_boot_zero_pending": not current_pending,
        "note": "Le cache exporté indique un plan théorique ; il ne mesure PAS les succès HTTP ni les octets réseau.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--signatures", type=Path, help="Export JSON id -> signature, facultatif")
    parser.add_argument("--cache-dir", type=Path, help="Copie du cache Application Support, facultative")
    parser.add_argument("--compare", type=Path, help="Premier snapshot JSON pour comparaison")
    parser.add_argument("--output", type=Path, help="Écrire le résultat sans modifier les sources")
    args = parser.parse_args()
    if bool(args.signatures) != bool(args.cache_dir):
        parser.error("--signatures et --cache-dir doivent être fournis ensemble.")
    report = scan(
        read_json(args.manifest),
        read_json(args.catalog),
        read_json(args.signatures) if args.signatures else None,
        args.cache_dir,
    )
    if args.compare:
        report["two_boot_comparison"] = compare(read_json(args.compare), report)
    serialized = json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True)
    if args.output:
        args.output.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)
    print("\nIMPORTANT : aucune requête HTTP n'a été effectuée ; le succès ou l'échec réseau exige une instrumentation distincte.")


if __name__ == "__main__":
    main()
