"""Full, read-only review of every *currently admissible* P'tites Ondes lead.

Uses exactly the same independent evidence gate as scheduled previews.
No candidate data/UID/URL is printed. The full diagnostic is private-only.
This cannot approve a patch or write the public catalogue.
"""
import argparse
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from merge_policy import ORIGIN
from ptitesondes_candidate_promotion import (
    MAX_FETCH, evaluate, permitted, private_admission_diagnostics,
    unique_review_candidates,
)
from ptitesondes_private_qualification_diagnostics import reason_bucket

SCHEMA = "ptitesondes.private_full_candidate_audit.v1"
MAX_AUDIT_CANDIDATES = 200


def full_audit(leads, baseline, published, today, *, review=evaluate):
    """Review all grouped UID/day candidates in <=15-item batches, never publish."""
    if not isinstance(leads, list) or len(leads) > 4000:
        raise ValueError("Backlog local invalide")
    candidates, eligible_raw, duplicates, conflicts = unique_review_candidates(
        leads, today)
    if len(candidates) > MAX_AUDIT_CANDIDATES:
        raise ValueError("Audit trop volumineux : fractionnement explicite requis")
    seen = set()
    counts = Counter()
    checked = accepted = 0
    candidate_keys = {(c["external_id"], c["date_start"]) for c in candidates}
    if len(candidate_keys) != len(candidates):
        raise ValueError("UID/jour admissible répété")
    for begin in range(0, len(candidates), MAX_FETCH):
        group = candidates[begin:begin + MAX_FETCH]
        keys = {(c["external_id"], c["date_start"]) for c in group}
        raw_group = [
            lead for lead in leads
            if permitted(lead, today) and
            (lead["external_id"], lead["date_start"]) in keys
        ]
        patch, report = review(raw_group, baseline, published, today,
                               limit=MAX_FETCH, slot=0)
        if (report.get("eligible_with_reviewed_venue") != len(group) or
                report.get("checked") != len(group) or
                report.get("date") != today.isoformat() or
                report.get("mode") != "preview_no_public_write" or
                report.get("accepted_preflight") != len(patch.get("additions", [])) or
                report.get("deferred_or_duplicates") != len(report.get("details", [])) or
                len(patch["additions"]) + len(report["details"]) != len(group) or
                patch.get("safe_to_publish") is not False):
            raise ValueError("Lot d'audit incomplet ou publication non interdite")
        checked += len(group)
        accepted += len(patch["additions"])
        for detail in report["details"]:
            if detail.get("status") not in (
                    "already_published", "rejected_schema", "unverified", "deferred"):
                raise ValueError("Refus de preuve non qualifié")
            counts[reason_bucket(detail)] += 1
        seen.update(keys)
    if seen != candidate_keys or checked != len(candidates) or (
            accepted + sum(counts.values()) != checked):
        raise ValueError("Audit incomplet ou compteurs incohérents")
    ids = [e["id"] for e in published["events"]]
    if len(set(ids)) != len(ids):
        raise ValueError("Catalogue publié comportant des ID dupliqués")
    return {
        "schema": SCHEMA, "day": today.isoformat(),
        "mode": "private_full_audit_no_approval_no_publication",
        "backlog_total": len(leads),
        "raw_eligible": eligible_raw,
        "unique_admissible": len(candidates),
        "duplicate_collector_leads": duplicates,
        "conflicting_uid_days_excluded": conflicts,
        "checked": checked,
        "accepted_preflight_decisions": accepted,
        "rejected_decisions": sum(counts.values()),
        "reason_groups": dict(sorted(counts.items())),
        "admission_diagnostics": private_admission_diagnostics(leads, today),
        "public_catalogue_at_audit": {
            "events": len(ids), "updated_at": published["updated_at"],
        },
        "public_writes": 0, "private_patch_approvals": 0,
        "notes": "Prévalidation seulement ; aucune approbation ni publication.",
    }


def public_summary(report):
    """Numeric allowlist for GitHub's public logs and job summaries."""
    fields = ("backlog_total", "raw_eligible", "unique_admissible",
              "duplicate_collector_leads", "conflicting_uid_days_excluded",
              "checked", "accepted_preflight_decisions", "rejected_decisions",
              "public_writes")
    if report.get("schema") != SCHEMA:
        raise ValueError("Audit malformé")
    return {field: report[field] for field in fields
            if type(report.get(field)) is int}


def read_json(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, (dict, list)):
        raise ValueError("JSON inattendu")
    return data


def read_historic():
    req = Request(ORIGIN, headers={"User-Agent": "OndesPublicDataAudit/1.0"})
    with urlopen(req, timeout=30) as response:
        data = response.read(1_000_001)
    if len(data) > 1_000_000:
        raise ValueError("Historique trop volumineux")
    return json.loads(data)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backlog-file", type=Path, required=True)
    parser.add_argument("--catalogue-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    today = datetime.now(ZoneInfo("Europe/Paris")).date()
    result = full_audit(read_json(args.backlog_file), read_historic(),
                        read_json(args.catalogue_file), today)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print(json.dumps(public_summary(result), sort_keys=True))


if __name__ == "__main__":
    main()
