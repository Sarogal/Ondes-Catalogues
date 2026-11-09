"""Private-only, bounded diagnostics for the *actual* verified outings batch.

Never echo candidate names, raw source URLs, arbitrary exception strings, or
backlog contents. Does not modify patches or relax evidence checks.
"""
import argparse
from collections import Counter
from datetime import date
import json
from pathlib import Path
import re


ALLOWED_STATUSES = frozenset({
    "already_published", "rejected_schema", "unverified", "deferred"
})
BUCKETS = frozenset({
    "already_published", "schema", "official_page_dynamic",
    "official_page_unavailable", "organizer_proof", "venue_or_gps",
    "date_or_time", "age_or_audience", "title_or_identity",
    "uid_or_source", "transport_or_data", "other"
})


def reason_bucket(detail):
    """Map free-text private reasons to stable category codes, never copying text."""
    status = detail["status"]
    if status == "already_published":
        return "already_published"
    if status == "rejected_schema":
        return "schema"
    reason = str(detail.get("reason", "")).casefold()
    if any(x in reason for x in ("dynamique", "javascript", "loading")):
        return "official_page_dynamic"
    if any(x in reason for x in ("organisateur", "secondaire", "programme")):
        return "organizer_proof"
    if any(x in reason for x in ("page officielle", "fiche officielle", "source officielle",
                                 "inaccessible", "redirection", "domaine officiel",
                                 "non autorisée")):
        return "official_page_unavailable"
    if any(x in reason for x in ("géolocalis", "position", "coordonn", "gps",
                                 "lieu absent", "registre")):
        return "venue_or_gps"
    if any(x in reason for x in ("date", "séance", "horaire", "heure",
                                 "calendrier", "temps")):
        return "date_or_time"
    if any(x in reason for x in ("âge", "enfant", "famill", "jeune public",
                                 "musical", "destination")):
        return "age_or_audience"
    if any(x in reason for x in ("titre", "ville", "lieu différent")):
        return "title_or_identity"
    if any(x in reason for x in ("uid", "canonique", "index", "agenda", "source différente")):
        return "uid_or_source"
    if any(x in reason for x in ("timeout", "http", "erreur", "réponse",
                                 "json", "malform")):
        return "transport_or_data"
    return "other"


def summarise(report, expected_day, expected_slot):
    if not isinstance(report, dict):
        raise ValueError("Rapport de prévalidation absent")
    if (report.get("date") != expected_day.isoformat()
            or report.get("mode") != "preview_no_public_write"
            or report.get("review_slot") != expected_slot):
        raise ValueError("Rapport daté ou créneau différent")
    fields = ("backlog_total", "eligible_with_reviewed_venue", "eligible_raw",
              "duplicate_collector_leads_skipped", "conflicting_uid_days_deferred",
              "review_batch", "review_batches", "checked",
              "accepted_preflight", "deferred_or_duplicates")
    if any(type(report.get(k)) is not int for k in fields):
        raise ValueError("Compteurs invalides")
    (backlog, eligible, raw_eligible, duplicates, conflicts, batch, batches,
     checked, accepted, rejected) = (report[k] for k in fields)
    if (not 0 <= backlog <= 4000 or not 0 <= eligible <= backlog
            or not 0 <= raw_eligible <= backlog
            or not 0 <= duplicates <= raw_eligible
            or not 0 <= conflicts <= raw_eligible - duplicates
            or eligible + duplicates + conflicts > raw_eligible
            or not 0 <= checked <= min(eligible, 15)
            or not 0 <= accepted <= checked
            or rejected != checked - accepted
            or not 0 <= rejected <= 15
            or not 0 <= batches <= 4000):
        raise ValueError("Comptages de prévalidation incohérents")
    if (batches == 0 and (eligible or batch or checked)
            or batches > 0 and (not 1 <= batch <= batches)):
        raise ValueError("Rotation de la prévalidation incohérente")
    details = report.get("details")
    if not isinstance(details, list) or len(details) != rejected:
        raise ValueError("Détail de vérification manquant")
    if any(not isinstance(x, dict) or x.get("status") not in ALLOWED_STATUSES
           for x in details):
        raise ValueError("Statut de preuve inconnu")
    counts = Counter(reason_bucket(x) for x in details)
    if not set(counts).issubset(BUCKETS):
        raise ValueError("Catégorie de diagnostic hors contrat")
    # Explicitly do NOT emit details, reasons, source links, titles, or UID.
    return {
        "schema": "ptitesondes.private_qualification_summary.v1",
        "day": expected_day.isoformat(), "slot": expected_slot,
        "backlog_total": backlog, "eligible": eligible,
        "eligible_raw": raw_eligible,
        "not_eligible_for_review": backlog - raw_eligible,
        "duplicate_collector_leads_skipped": duplicates,
        "conflicting_uid_days_deferred": conflicts,
        "batch": batch, "batches": batches,
        "checked": checked, "accepted_preflight": accepted,
        "rejected": rejected,
        "reason_groups": dict(sorted(counts.items())),
        "publications": 0, "mode": "private_diagnostic_only"
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--date", required=True, type=date.fromisoformat)
    parser.add_argument("--slot", required=True, type=int, choices=range(4))
    args = parser.parse_args()
    data = json.loads(args.report.read_text(encoding="utf-8"))
    summary = summarise(data, args.date, args.slot)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(
        summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # Do not print the report: only the private file contains the counts.


if __name__ == "__main__":
    main()
