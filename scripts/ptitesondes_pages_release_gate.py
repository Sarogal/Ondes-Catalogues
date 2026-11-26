"""Fail-closed Pages reconciliation of approved historical corrections.

This does NOT authorize general history edits or publication. It checks that
the live GitHub Pages pair differs from committed public JSON *solely* in
the school-only time field already verified by merge_policy, or a GPS-only
transition already recorded in the trusted Git ledger.
The existing public Pages deployment workflow remains the sole publisher.
"""
import json
from datetime import datetime
import os
from pathlib import Path

from merge_policy import MOMO_HISTORY_ID, historical_event_unchanged
from ptitesondes_pages_verify import ROOT, ORIGIN, LIMITS, get_json
from ptitesondes_places import validate as validate_places
from ptitesondes_historical_gps_ledger import reconcile, SCHEMA

LEDGER_PATH = Path("reviews/ptitesondes-historical-gps-ledger.json")


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


def pages_pending_gps_only(committed, served, ledger):
    """Only retry a committed, ledger-bound GPS repair, not arbitrary drift."""
    try:
        if (set(committed) != {"sorties.json", "lieux.json"}
                or set(served) != set(committed)
                or committed["lieux.json"] != served["lieux.json"]):
            return False
        new, old = committed["sorties.json"], served["sorties.json"]
        if (set(new) != set(old) or new.get("version") != 3
                or any(new[k] != old[k] for k in new if k not in ("events", "updated_at"))):
            return False
        a, b = datetime.fromisoformat(new["updated_at"]), datetime.fromisoformat(old["updated_at"])
        if a.tzinfo is None or b.tzinfo is None or a < b:
            return False
        newer, older = new["events"], old["events"]
        if (not isinstance(newer, list) or not isinstance(older, list)
                or len(newer) != len(older) or len(newer) < 100
                or [e["id"] for e in newer] != [e["id"] for e in older]):
            return False
        if ledger.get("schema") != SCHEMA or set(ledger) != {"schema", "repairs"}:
            return False
        changed = {n["id"] for n, o in zip(newer, older) if n != o}
        if not changed or not changed <= ledger["repairs"].keys():
            return False
        subset = {"schema": SCHEMA, "repairs": {uid: ledger["repairs"][uid] for uid in changed}}
        effective = reconcile(old, new, subset)
        return effective["events"] == newer
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        return False


def status(read=get_json, root=ROOT, ledger_path=LEDGER_PATH):
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
    ledger_file = Path(ledger_path)
    if ledger_file.is_file() and not ledger_file.is_symlink():
        ledger = json.loads(ledger_file.read_text(encoding="utf-8"))
        if pages_pending_gps_only(committed, served, ledger):
            return "approved_gps_only"
    return "unexpected_difference"


def main():
    # An unreachable Pages endpoint must stop this special release (fail closed).
    state = status()
    pending = state in ("approved_momo_only", "approved_gps_only")
    if state == "identical":
        print("Pages identique à Git : aucun rattrapage nécessaire.")
    elif state == "approved_momo_only":
        print("Correction scolaire Momo approuvée dans Git, absente des Pages : déploiement autorisé.")
    elif state == "approved_gps_only":
        print("Corrections GPS inscrites au registre Git, absentes des Pages : rattrapage autorisé.")
    else:
        print("::warning::Écart Pages/Git hors corrections historiques approuvées : aucune dérogation de déploiement.")
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write("changed=" + str(pending).lower() + "\n")


if __name__ == "__main__":
    main()
