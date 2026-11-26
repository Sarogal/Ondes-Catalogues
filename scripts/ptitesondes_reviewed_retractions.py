#!/usr/bin/env python3
"""One-off, manifest-reviewed editorial retractions, not a Publisher update API.

Only explicit source-reviewed OpenAgenda IDs are eligible. The normal Publisher
stays append-only. No private backlog, source list, or arbitrary event deletion.
The original catalogue is never overwritten without identity/contents checks.
"""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

SCHEMA = "ptitesondes.reviewed_retractions.v1"
REASONS = frozenset(("school_support_primary",
                     "non_performance_gathering_primary",
                     "evergreen_commercial_studio_availability",
                     "adult_audience_official", "market_gathering_primary",
                     "mixed_umbrella_programme_primary", "park_visit_programme_primary"))
EVENT_ID = re.compile(r"openagenda-[1-9][0-9]{0,11}-20[0-9]{2}-[0-9]{2}-[0-9]{2}\Z")
TITLE_CLUES = {
    # For the adult-audience reason the exact source-reviewed record,
    # official municipal evidence URL and concert category are checked below.
    "adult_audience_official": re.compile(r"\S"),
    # Exact reviewed incident, not an editorial whitelist or venue filter.
    "park_visit_programme_primary": re.compile(r"^Le Hameau Enchanté$", re.I),
    "mixed_umbrella_programme_primary": re.compile(r"^Les Journées polyglottes$", re.I),
    "market_gathering_primary": re.compile(
        r"^\s*march[ée]\s+de\s+(?:no[ëe]l|saint[- ]nicolas)\b", re.I),
    "school_support_primary": re.compile(
        r"(?:accompagnement|soutien) scolaire|aide aux devoirs|revisions scolaires", re.I),
    "non_performance_gathering_primary": re.compile(
        r"^\s*(?:forum|conference|colloque|table ronde)\b", re.I),
    # Review is restricted to an EXACT already-published snapshot and
    # source-verified studio-service title, not a general filter on
    # events at studios or on concerts with many performances.
    "evergreen_commercial_studio_availability": re.compile(
        r"enregistrez votre musique en studio|enregistrement en studio", re.I),
}


def reject(condition, code):
    if not condition:
        raise ValueError(code)


def https(url):
    if type(url) is not str or not 8 <= len(url) <= 2000:
        return False
    try:
        value = urlsplit(url)
        return (value.scheme == "https" and bool(value.hostname)
                and value.port in (None, 443)
                and not value.username and not value.password
                and not value.fragment and bool(value.path.strip("/")))
    except ValueError:
        return False


def digest(document):
    return hashlib.sha256(
        json.dumps(document, sort_keys=True, ensure_ascii=False,
                   separators=(",", ":")).encode("utf-8")).hexdigest()


def reviewed_retraction(document, manifest):
    """Pure function: (corrected JSON, immutable audit, changed).

    Mixed already-removed/present plans fail closed; an already completed
    removal is idempotent. Independent fields of all other events are intact.
    """
    reject(type(document) is dict and type(document.get("events")) is list,
           "invalid_public_catalogue")
    events = document["events"]
    reject(all(type(x) is dict and type(x.get("id")) is str for x in events)
           and len({e["id"] for e in events}) == len(events),
           "catalogue_invalid_or_duplicate_ids")
    reject(type(manifest) is dict and manifest.get("schema") == SCHEMA
           and manifest.get("reviewed_on") in ("2026-11-22", "2026-11-23", "2026-11-25")
           and type(manifest.get("catalogue_min_count")) is int
           and manifest["catalogue_min_count"] >= 1
           and type(manifest.get("approvals")) is list
           and 1 <= len(manifest["approvals"]) <= 80,
           "invalid_reviewed_manifest")
    approvals = manifest["approvals"]
    targets = {}
    for row in approvals:
        reject(type(row) is dict
               and set(row) == {"action", "reason_code", "evidence_url",
                                "expected_event"}
               and row["action"] == "withdraw"
               and row["reason_code"] in REASONS
               and https(row["evidence_url"])
               and type(row["expected_event"]) is dict,
               "invalid_reviewed_approval")
        expected = row["expected_event"]
        eid = expected.get("id")
        reject(type(eid) is str and EVENT_ID.fullmatch(eid) is not None
               and eid not in targets
               and type(expected.get("title")) is str
               and TITLE_CLUES[row["reason_code"]].search(expected["title"])
               and type(expected.get("source_url")) is str
               and https(expected["source_url"])
               and urlsplit(expected["source_url"]).hostname == "openagenda.com"
               and (row["reason_code"] != "evergreen_commercial_studio_availability"
                    or (manifest["reviewed_on"] == "2026-11-23"
                        and row["evidence_url"] == expected["source_url"])),
               "invalid_approval_identity_or_reason")
        if row["reason_code"] in ("adult_audience_official", "market_gathering_primary"):
            reject(manifest["reviewed_on"] == "2026-11-25",
                   "invalid_editorial_review_date")
        if row["reason_code"] == "adult_audience_official":
            reject(expected.get("category") == "concert"
                   and urlsplit(row["evidence_url"]).hostname == "metropole.nantes.fr"
                   and urlsplit(row["evidence_url"]).path.startswith(
                       "/que-faire-a-nantes/agenda/" + eid.split("-")[1] + "_"),
                   "invalid_official_adult_audience_evidence")
        if row["reason_code"] == "mixed_umbrella_programme_primary":
            reject(manifest["reviewed_on"] == "2026-11-25"
                   and expected.get("category") == "concert"
                   and expected.get("time") == "10:00"
                   and urlsplit(row["evidence_url"]).hostname == "metropole.nantes.fr"
                   and urlsplit(row["evidence_url"]).path.startswith(
                       "/que-faire-a-nantes/agenda/" + eid.split("-")[1] + "_")
                   and urlsplit(expected["source_url"]).path.split("/")[-1].startswith(eid.split("-")[1] + "_"),
                   "invalid_official_mixed_programme_evidence")
        if row["reason_code"] == "park_visit_programme_primary":
            reject(manifest["reviewed_on"] == "2026-11-25"
                   and eid.startswith("openagenda-23913876-")
                   and expected.get("category") == "concert"
                   and expected.get("time") == "09:30"
                   and row["evidence_url"] == "https://www.duboeuf.com/fr/le-parc/le-hameau-enchante/"
                   and expected["source_url"] == "https://openagenda.com/datatourisme-region-bourgogne-franche-comte/events/23913876_le-hameau-enchante",
                   "invalid_official_park_visit_evidence")
        targets[eid] = row
    original = {e["id"]: e for e in events}
    present = [eid for eid in targets if eid in original]
    reject(len(present) in (0, len(targets)),
           "partially_applied_plan_not_safe_to_repeat")
    if not present:
        return document, None, False
    reject(len(events) >= manifest["catalogue_min_count"],
           "catalogue_smaller_than_reviewed_snapshot")
    for eid, item in targets.items():
        reject(original[eid] == item["expected_event"],
               "reviewed_record_changed_since_approval")
    corrected_events = [e for e in events if e["id"] not in targets]
    reject(len(events) - len(corrected_events) == len(targets)
           and [e for e in events if e["id"] not in targets] == corrected_events,
           "non_target_records_changed")
    corrected = dict(document)
    corrected["events"] = corrected_events
    corrected["updated_at"] = datetime.now(
        ZoneInfo("Europe/Paris")).isoformat(timespec="seconds")
    audit = {
        "schema": "ptitesondes.reviewed_retraction_audit.v1",
        "reviewed_on": manifest["reviewed_on"],
        "applied_at": corrected["updated_at"],
        "before_count": len(events), "after_count": len(corrected_events),
        "catalogue_before_sha256": digest(document),
        "catalogue_after_sha256": digest(corrected),
        "withdrawn": [
            {"id": eid, "reason_code": row["reason_code"],
             "evidence_url": row["evidence_url"],
             "original_source_url": row["expected_event"]["source_url"]}
            for eid, row in targets.items()
        ],
    }
    return corrected, audit, True


def atomic_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(obj, ensure_ascii=False, indent=2) + "\n")
    fd, name = tempfile.mkstemp(prefix="reviewed-", suffix=".tmp",
                                 dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--catalogue", type=Path, required=True)
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--audit-out", type=Path, required=True)
    ap.add_argument("--apply", action="store_true",
                    help="Only use in the isolated reviewed-retraction workflow")
    args = ap.parse_args()
    document = json.loads(args.catalogue.read_text(encoding="utf-8"))
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    corrected, audit, changed = reviewed_retraction(document, manifest)
    if args.apply and changed:
        # Store the audit before the catalogue; an aborted runner never pushes
        # either. Git commit/push must atomically include both files.
        atomic_json(args.audit_out, audit)
        atomic_json(args.catalogue, corrected)
    print("reviewed_retractions=" + str(
        len(audit["withdrawn"]) if changed else 0))
    print("changed=" + str(bool(args.apply and changed)).lower())


if __name__ == "__main__":
    main()
