#!/usr/bin/env python3
"""Contrôle de libération des archives : lecture seule, jamais de réécriture du socle."""
import hashlib
import json
from pathlib import Path

from grossesondes_cloud_sync import load_production
from grossesondes_history_guard import load_registry, validate_history_extension
from grossesondes_preview import ROOT, index, require

MANIFEST = ROOT / "reference-manifest.json"


def check():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    sources = manifest.get("sources", {})
    baseline = sources.get("festival-history.json", {})
    require(baseline.get("count") == 170
            and baseline.get("source_date") == "2026-10-22"
            and baseline.get("sha256") == "8e100c12a71ab2822b9bdec5cdd880b8e19025bc4e78feb35aa602f012f7e86e",
            "source initiale des 170 archives remplacée")
    registry = load_registry()
    mirror_history = json.loads((ROOT / "festival-history.json").read_text(encoding="utf-8"))
    mirror_calendar = json.loads((ROOT / "festivals.json").read_text(encoding="utf-8"))
    original = load_production(manifest)
    added = validate_history_extension(original["festival-history.json"], mirror_history, registry)
    require(added == 3 and len(mirror_history["knownFestivals"]) == 173,
            "nombre exact de nouvelles archives non respecté")
    cal = index(mirror_calendar, "festivals", 1)
    source_cal = index(original["festivals.json"], "festivals", 1)
    require(all(slug in cal for slug in source_cal),
            "le miroir calendrier a perdu une fiche du socle")
    require(all(r.get("slug") not in cal for r in mirror_history["knownFestivals"][170:]),
            "une archive a été ajoutée comme prochaine édition")
    report = {
        "result": "SAFE_HISTORY_APPEND_ONLY",
        "original_archives": len(original["festival-history.json"]["knownFestivals"]),
        "approved_archives": added,
        "published_history_candidate": len(mirror_history["knownFestivals"]),
        "calendar_not_modified_by_release": True,
        "approved_slugs": registry["approvedSlugs"],
        "deferred_slugs": registry["deferredSlugs"],
        "baseline_manifest_sha256": baseline["sha256"],
        "source_checks": "Both public Infomaniak JSON contents verified against pinned SHA256; no rebase.",
        "writes": "NONE",
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    check()
