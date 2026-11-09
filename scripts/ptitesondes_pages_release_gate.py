"""Fail-closed, one-time Pages reconciliation of the reviewed Momo school-only fix.

This does NOT authorize general history edits or publication. It checks that
the live GitHub Pages pair differs from committed public JSON *solely* in
the single school-only time field already verified by merge_policy.
The existing public Pages deployment workflow remains the sole publisher.
"""
import json
import os
from pathlib import Path

from merge_policy import MOMO_HISTORY_ID, historical_event_unchanged
from ptitesondes_pages_verify import ROOT, ORIGIN, LIMITS, get_json
from ptitesondes_places import validate as validate_places


def pages_pending_momo_only(committed, served):
    """True only when precisely the approved historic Momo edit is missing."""
    if not isinstance(committed, dict) or not isinstance(served, dict):
        return False
    names = {"sorties.json", "lieux.json"}
    if set(committed) != names or set(served) != names:
        return False
    if committed["lieux.json"] != served["lieux.json"]:
        return False
    current = committed["sorties.json"]
    previous = served["sorties.json"]
    if not isinstance(current, dict) or not isinstance(previous, dict):
        return False
    if set(current) != set(previous) or current.get("version") != 3:
        return False
    if any(current[k] != previous[k] for k in current if k != "events"):
        return False
    newer, older = current.get("events"), previous.get("events")
    if not isinstance(newer, list) or not isinstance(older, list):
        return False
    if len(newer) != len(older) or len(newer) < 100:
        return False
    found, ids = 0, set()
    for existing, published in zip(newer, older):
        if not isinstance(existing, dict) or not isinstance(published, dict):
            return False
        uid = existing.get("id")
        if not isinstance(uid, str) or not uid or uid in ids:
            return False
        ids.add(uid)
        if existing == published:
            continue
        if uid != MOMO_HISTORY_ID or not historical_event_unchanged(
                published, existing):
            return False
        found += 1
    return found == 1


def status(read=get_json, root=ROOT):
    committed = {
        name: json.loads((Path(root) / name).read_text(encoding="utf-8"))
        for name in LIMITS
    }
    validate_places(committed["lieux.json"])
    served = {
        name: read(ORIGIN + name, size)
        for name, size in LIMITS.items()
    }
    validate_places(served["lieux.json"])
    if committed == served:
        return "identical"
    if pages_pending_momo_only(committed, served):
        return "approved_momo_only"
    return "unexpected_difference"


def main():
    # An unreachable Pages endpoint must stop this special release (fail closed).
    state = status()
    pending = state == "approved_momo_only"
    if state == "identical":
        print("Pages identique à Git : aucun rattrapage nécessaire.")
    elif pending:
        print("Correction scolaire Momo approuvée dans Git, absente des Pages : déploiement autorisé.")
    else:
        print("::warning::Écart Pages/Git hors correction Momo : aucune dérogation de déploiement.")
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write("changed=" + str(pending).lower() + "\n")


if __name__ == "__main__":
    main()
