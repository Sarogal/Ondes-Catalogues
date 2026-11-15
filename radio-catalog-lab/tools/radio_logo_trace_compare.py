#!/usr/bin/env python3
"""Comparer les traces opt-in GO_LOGO_AUDIT de deux démarrages Flutter.

Aucun accès réseau, aucune écriture. Les traces ne contiennent que des IDs
publics, clés FNV d'URL, codes HTTP et comptages, jamais d'URL complète.
Usage : python tools/radio_logo_trace_compare.py boot1.log boot2.log
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

PREFIX = "GO_LOGO_AUDIT "


def read_events(path: Path):
    events = []
    for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if PREFIX not in line:
            continue
        raw = line.split(PREFIX, 1)[1].strip()
        try:
            event = json.loads(raw)
        except json.JSONDecodeError as error:
            raise ValueError(f"{path}:{number}: trace tronquée ou JSON invalide ({error})") from error
        if not isinstance(event, dict) or not event.get("type"):
            raise ValueError(f"{path}:{number}: événement sans type")
        events.append(event)
    if not events:
        raise ValueError(f"Pas de trace {PREFIX.strip()} dans {path}")
    return events


def summarize(events):
    starts = [i for i, e in enumerate(events) if e["type"] == "boot_start"]
    if len(starts) != 1:
        raise ValueError(f"Le fichier doit contenir exactement un boot_start, trouvé {len(starts)}.")
    events = events[starts[0]:]
    ready = next((i for i, e in enumerate(events) if e["type"] == "boot_ready"), None)
    if ready is None:
        raise ValueError("boot_ready absent : démarrage incomplet, comparaison impossible.")
    events = events[:ready + 1]
    types = Counter(e["type"] for e in events)
    plans = [e for e in events if e["type"] == "plan_summary"]
    manifest = [e for e in events if e["type"] == "manifest_selected"]
    details = [e for e in events if e["type"] == "pending_entry"]
    network = [e for e in events if e["type"] == "http_image"]
    attempts = [e for e in network if e.get("outcome") == "attempt"]
    results = [e for e in network if e.get("outcome") != "attempt"]
    outcomes = Counter(e.get("outcome", "unknown") for e in results)
    reasons = Counter()
    for entry in details:
        if entry.get("file_present") is False:
            reasons["file_missing_or_empty"] += 1
        if entry.get("signature_state") == "missing":
            reasons["signature_missing"] += 1
        elif entry.get("signature_state") == "mismatch":
            reasons["signature_mismatch"] += 1
    http_statuses = Counter(str(e["http_status"]) for e in results if e.get("http_status") is not None)
    return {
        "complete_boot": True,
        "manifest_version": manifest[-1].get("manifest_version") if manifest else None,
        "catalog_station_count": manifest[-1].get("catalog_station_count") if manifest else None,
        "pending_entries": plans[-1].get("pending_station_entries") if plans else None,
        "pending_unique_urls": plans[-1].get("pending_unique_urls") if plans else None,
        "pending_station_ids": sorted(set(str(e["station_id"]) for e in details)),
        "reasons": dict(reasons),
        "http_attempt_count": len(attempts),
        "http_unique_url_keys": len({str(e.get("url_key")) for e in attempts}),
        "http_outcomes": dict(outcomes),
        "http_status_codes": dict(http_statuses),
        "stored_image_objects": outcomes.get("stored", 0),
        "rejected_or_failed_requests": len(results) - outcomes.get("stored", 0),
        "reported_response_image_bytes": sum(int(e.get("received_bytes") or 0) for e in results),
        "requests_missing_outcome": max(0, len(attempts) - len(results)),
        "trace_types": dict(types),
        "note": "received_bytes compte les corps des réponses HTTP connues ; ce n'est pas une mesure du trafic filaire ou de fichiers enregistrés.",
    }


def compare(first, second):
    a = set(first["pending_station_ids"])
    b = set(second["pending_station_ids"])
    versions_match = first["manifest_version"] == second["manifest_version"]
    return {
        "same_manifest_version": versions_match,
        "first_pending": first["pending_entries"],
        "second_pending": second["pending_entries"],
        "repeated_pending_ids": sorted(a & b),
        "new_pending_ids": sorted(b - a),
        "resolved_pending_ids": sorted(a - b),
        "second_boot_zero_network_images": second["http_attempt_count"] == 0,
        "second_boot_zero_pending": second["pending_entries"] == 0,
        "acceptance_met": versions_match and second["pending_entries"] == 0 and second["http_attempt_count"] == 0,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("first_boot", type=Path)
    parser.add_argument("second_boot", type=Path)
    args = parser.parse_args()
    first = summarize(read_events(args.first_boot))
    second = summarize(read_events(args.second_boot))
    print(json.dumps({"boot1": first, "boot2": second, "comparison": compare(first, second)},
                     indent=2, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
