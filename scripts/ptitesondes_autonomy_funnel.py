#!/usr/bin/env python3
"""Read-only, redacted funnel audit for P'tites Ondes outings.

Consumes PRIVATE aggregate reports and the PUBLIC catalogue. Never reads raw
candidate identities, never fetches a URL, and never writes a patch/catalogue.
"""
import argparse
from collections import Counter
from datetime import date
import json
from pathlib import Path
import re

SCHEMA = "ptitesondes.autonomy_funnel_audit.v1"
REASON = re.compile(r"^[a-z][a-z0-9_]{0,47}$")


def nonnegative(value, label):
    if type(value) is not int or value < 0:
        raise ValueError("invalid_count_" + label)
    return value


def summarize(collection, qualification, catalogue, today):
    if not isinstance(today, date):
        raise ValueError("invalid_date")
    if not all(isinstance(doc, dict) for doc in
               (collection, qualification, catalogue)):
        raise ValueError("invalid_report")
    if collection.get("day") != today.isoformat():
        raise ValueError("collection_day_mismatch")
    if qualification.get("day") != today.isoformat():
        raise ValueError("qualification_day_mismatch")
    diagnostics = qualification.get("admission_diagnostics")
    if not isinstance(diagnostics, dict):
        raise ValueError("admission_diagnostics_absent")
    reasons = diagnostics.get("reason_counts")
    if not isinstance(reasons, dict) or not reasons:
        raise ValueError("reason_counts_absent")
    counts = {}
    for code, value in reasons.items():
        if not isinstance(code, str) or not REASON.fullmatch(code):
            raise ValueError("invalid_reason_code")
        counts[code] = nonnegative(value, code)
    backlog = nonnegative(qualification.get("backlog_total"), "backlog")
    if (sum(counts.values()) != backlog or
            nonnegative(diagnostics.get("raw_leads"), "raw_leads") != backlog):
        raise ValueError("backlog_reasons_do_not_reconcile")
    reported_backlog = nonnegative(collection.get("en_attente_total"), "collected_backlog")
    if reported_backlog != backlog:
        raise ValueError("collection_and_qualification_backlog_disagree")
    if catalogue.get("version") != 3 or not isinstance(catalogue.get("events"), list):
        raise ValueError("invalid_public_catalogue")
    published_ids = set()
    future_categories = Counter()
    future = 0
    for event in catalogue["events"]:
        if not isinstance(event, dict) or not isinstance(event.get("id"), str):
            raise ValueError("invalid_public_event")
        if event["id"] in published_ids:
            raise ValueError("duplicate_public_id")
        published_ids.add(event["id"])
        try:
            end = date.fromisoformat(event.get("date_end") or event["date_start"])
        except (TypeError, KeyError, ValueError):
            raise ValueError("invalid_public_event_date") from None
        if end >= today:
            future += 1
            category = event.get("category")
            if not isinstance(category, str) or not REASON.fullmatch(category.replace("-", "_")):
                raise ValueError("invalid_public_category")
            future_categories[category] += 1
    requests = nonnegative(collection.get("sources_interrogees"), "api_requests")
    agendas = nonnegative(collection.get("openagenda_agendas_interroges"), "oa_agendas")
    configured = nonnegative(collection.get("openagenda_agendas_configures"), "oa_configured")
    if agendas > configured:
        raise ValueError("openagenda_count_inconsistent")
    failures = collection.get("sources_en_echec")
    if not isinstance(failures, list):
        raise ValueError("source_failures_invalid")
    # Failure descriptions may contain sensitive source URLs: expose COUNT only.
    checked = nonnegative(qualification.get("checked"), "checked")
    accepted = nonnegative(qualification.get("accepted_preflight"), "prevalidated")
    if accepted > checked:
        raise ValueError("prevalidation_count_inconsistent")
    return {
        "schema": SCHEMA,
        "day": today.isoformat(),
        "mode": "redacted_read_only_never_publish",
        "public": {
            "catalogue_events": len(published_ids),
            "future_events": future,
            "future_categories": dict(sorted(future_categories.items())),
            "updated_at": catalogue.get("updated_at"),
        },
        "collection": {
            "api_requests_successful_not_distinct_sources": requests,
            "distinct_source_organizations": None,
            "openagenda_agendas_configured": configured,
            "openagenda_agendas_interrogated": agendas,
            "failed_source_requests_or_agendas": len(failures),
            "relevant_sessions": nonnegative(collection.get("seances_pertinentes"), "relevant"),
            "new_leads_reported": nonnegative(collection.get("decouvertes_nouvelles_en_attente"), "new"),
        },
        "backlog": {
            "total": backlog,
            "first_gate_reason_counts": dict(sorted(counts.items())),
            "first_gate_eligible_not_approved": counts.get("eligible", 0),
            "automatically_recoverable_count": None,
        },
        "qualification": {
            "checked_decisions": checked,
            "prevalidated_not_published": accepted,
            "publication_not_proven_by_this_report": True,
        },
        "safety": {
            "candidate_names_or_urls_exposed": False,
            "public_writes": 0,
            "human_approval_inferred": False,
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection", type=Path, required=True)
    parser.add_argument("--qualification", type=Path, required=True)
    parser.add_argument("--catalogue", type=Path, required=True)
    parser.add_argument("--date", type=date.fromisoformat, required=True)
    args = parser.parse_args()
    docs = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in (args.collection, args.qualification, args.catalogue)
    ]
    print(json.dumps(summarize(*docs, args.date),
                     sort_keys=True, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
