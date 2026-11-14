"""Private-only status for individually dated Accoord UID 813941 sessions.

This is a diagnostic, NEVER a qualification or publication input. Only a dated
state and a finite reason category are stored in the private intake branch.
No event names, URLs, coordinates, evidence snippets, or arbitrary error text
are retained. Private raw validation inputs stay on the runner.
"""
import argparse
from collections import Counter
from datetime import date
import json
from pathlib import Path
import re

from ptitesondes_candidate_promotion import (
    covered_by_published_range, permitted,
)
from ptitesondes_private_qualification_diagnostics import (
    ALLOWED_STATUSES, BUCKETS, reason_bucket,
)

SCHEMA = "ptitesondes.private_accoord_session_status.v1"
UID = "813941"
ID_PREFIX = f"openagenda-{UID}-"
STATES = frozenset({
    "published", "approved_private", "covered_by_other_public_event",
    "prevalidated_not_approved", "checked_not_approved",
    "awaiting_batch", "blocked_at_entry",
})
LAST_RESULTS = frozenset({"prevalidated", "rejected"})


def iso_day(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("Date non conforme")
    return date.fromisoformat(value)


def events(document):
    if not isinstance(document, dict) or not isinstance(document.get("events"), list):
        raise ValueError("Catalogue public incorrect")
    result = document["events"]
    if any(not isinstance(item, dict) or not isinstance(item.get("id"), str)
           for item in result):
        raise ValueError("Événement public incorrect")
    return result


def additions(document):
    if not isinstance(document, dict) or not isinstance(document.get("additions"), list):
        raise ValueError("Patch non conforme")
    result = document["additions"]
    if any(not isinstance(item, dict) or not isinstance(item.get("id"), str)
           for item in result):
        raise ValueError("Addition non conforme")
    return result


def previous_checks(previous, today):
    if previous is None:
        return {}
    if (not isinstance(previous, dict) or previous.get("schema") != SCHEMA
            or previous.get("series_uid") != UID
            or not isinstance(previous.get("sessions"), list)):
        raise ValueError("État privé précédent invalide")
    checks = {}
    for item in previous["sessions"]:
        if not isinstance(item, dict) or not set(item).issubset({
                "date", "status", "last_reviewed_on", "last_result",
                "last_reason_group"}):
            raise ValueError("État d'une séance précédente invalide")
        day = iso_day(item.get("date"))
        key = day.isoformat()
        if (key in checks or item.get("status") not in STATES
                or day > date(2100, 1, 1)):
            raise ValueError("Séance précédente répétée ou malformée")
        rev = item.get("last_reviewed_on")
        outcome = item.get("last_result")
        bucket = item.get("last_reason_group")
        if rev is not None:
            if iso_day(rev) > today or outcome not in LAST_RESULTS:
                raise ValueError("Ancien contrôle invalide")
            if (outcome == "rejected" and bucket not in BUCKETS or
                    outcome == "prevalidated" and bucket is not None):
                raise ValueError("Ancienne catégorie non autorisée")
        elif outcome is not None or bucket is not None:
            raise ValueError("Contrôle précédent incomplet")
        checks[key] = {
            k: item[k] for k in
            ("last_reviewed_on", "last_result", "last_reason_group")
            if item.get(k) is not None
        }
    return checks


def build(backlog, catalogue, patch, preview, report, previous, today):
    """All inputs are already on the runner. Output is private diagnostics only."""
    if not isinstance(today, date) or not isinstance(backlog, list):
        raise ValueError("Entrées privées invalides")
    public_items = events(catalogue)
    public_ids = {item["id"] for item in public_items}
    private_ids = {item["id"] for item in additions(patch)}
    preview_items = additions(preview)
    preview_ids = {item["id"] for item in preview_items}
    if not isinstance(report, dict) or (
            report.get("date") != today.isoformat()
            or report.get("mode") != "preview_no_public_write"
            or not isinstance(report.get("details"), list)
            or type(report.get("checked")) is not int
            or type(report.get("accepted_preflight")) is not int
            or report["accepted_preflight"] != len(preview_items)
            or report["checked"] != len(report["details"]) + len(preview_items)):
        raise ValueError("Rapport de lot incohérent")
    review_details = report["details"]
    if any(not isinstance(d, dict) or d.get("status") not in ALLOWED_STATUSES
           for d in review_details):
        raise ValueError("Décisions privées invalides")

    prior = previous_checks(previous, today)
    groups = {}
    for item in backlog:
        if not isinstance(item, dict):
            raise ValueError("Backlog malformé")
        if item.get("external_id") != UID:
            continue
        d = iso_day(item.get("date_start"))
        if d < today:
            continue
        if item.get("date_end") != d.isoformat():
            raise ValueError("Séance Accoord à période ambiguë")
        groups.setdefault(d.isoformat(), []).append(item)

    result = []
    for day, leads in sorted(groups.items()):
        identity = ID_PREFIX + day
        last = dict(prior.get(day, {}))
        matching = [
            detail for detail in review_details if
            detail.get("date") == day and any(
                detail.get("source_url") == lead.get("source_url")
                for lead in leads)
        ]
        if len(matching) > 1:
            raise ValueError("Plusieurs décisions contradictoires pour la séance")
        accepted = identity in preview_ids
        if accepted and matching:
            raise ValueError("Séance simultanément retenue et refusée")
        if accepted:
            last = {"last_reviewed_on": today.isoformat(),
                    "last_result": "prevalidated"}
        elif matching:
            last = {
                "last_reviewed_on": today.isoformat(),
                "last_result": "rejected",
                "last_reason_group": reason_bucket(matching[0]),
            }

        if identity in public_ids:
            state = "published"
        elif identity in private_ids:
            state = "approved_private"
        elif any(covered_by_published_range(lead, public_items) for lead in leads):
            state = "covered_by_other_public_event"
        elif accepted:
            state = "prevalidated_not_approved"
        elif matching:
            state = "checked_not_approved"
        elif any(permitted(lead, today) for lead in leads):
            state = "awaiting_batch"
        else:
            state = "blocked_at_entry"
        result.append({"date": day, "status": state, **last})

    counts = dict(sorted(Counter(x["status"] for x in result).items()))
    return {
        "schema": SCHEMA,
        "series_uid": UID,
        "generated_on": today.isoformat(),
        "public_catalogue_updated_at": catalogue.get("updated_at"),
        "total_future": len(result),
        "status_counts": counts,
        "sessions": result,
        "mode": "diagnostic_only_no_approval_no_publication",
    }


def main():
    parser = argparse.ArgumentParser()
    for arg in ("backlog", "catalogue", "patch", "preview", "report", "output"):
        parser.add_argument("--" + arg, type=Path, required=True)
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--date", type=date.fromisoformat, required=True)
    args = parser.parse_args()
    def load(path):
        return json.loads(path.read_text(encoding="utf-8"))
    previous = load(args.previous) if args.previous and args.previous.exists() else None
    document = build(
        load(args.backlog), load(args.catalogue), load(args.patch),
        load(args.preview), load(args.report), previous, args.date)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    # Intentionally no stdout; keep exact dates and categories private.


if __name__ == "__main__":
    main()
