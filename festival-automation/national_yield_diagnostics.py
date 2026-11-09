"""Private, offline-only yield diagnosis after festival editorial reconciliation.

No HTTP requests, no publication decisions, no public artifacts. An absent
watch key means NOT_OBSERVED, never a successful zero-result scan.
"""
import argparse
from collections import Counter
from datetime import date
import json
from pathlib import Path

SCHEMA = "grossesondes.festival-yield-diagnostics-private.v1"
STATE_SCHEMA = "grossesondes.source-watch.v1"
REVIEW_SCHEMA = "grossesondes.national-editorial-reconciliation-private.v1"
MAX_DOSSIERS = 500
MAX_CHECKS = 50


def _read(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("private diagnostic input must be an object")
    return data


def _watch(checks, observed_key, today, expected=None):
    if checks is None:
        return {"status": "NOT_OBSERVED", "attempts_today": 0,
                "candidate_checks_today": 0, "unavailable_today": 0}
    if not isinstance(checks, dict) or len(checks) > MAX_CHECKS:
        raise ValueError("invalid private watch checks")
    if expected is not None and any(k not in expected for k in checks):
        raise ValueError("unexpected private watch identity")
    attempted = 0
    candidates = 0
    unavailable = 0
    for row in checks.values():
        if not isinstance(row, dict):
            raise ValueError("invalid private watch record")
        when = row.get("lastAttempted")
        if when is not None:
            if not isinstance(when, str) or date.fromisoformat(when) > date.fromisoformat(today):
                raise ValueError("invalid private watch timestamp")
        if when != today:
            continue
        attempted += 1
        if observed_key == "candidate_seen":
            if type(row.get("candidate_seen")) is not bool:
                raise ValueError("invalid institutional candidate flag")
            candidates += int(row["candidate_seen"])
            unavailable += int(row.get("institutional_status") == "UNAVAILABLE"
                               or row.get("first_party_status") == "UNAVAILABLE")
        else:
            status = row.get("status")
            if not isinstance(status, str):
                raise ValueError("invalid historical status")
            candidates += int(status == "YEAR_MENTION_REVIEW_ONLY")
            unavailable += int(status == "UNAVAILABLE")
    return {"status": "ATTEMPTED_TODAY" if attempted else "NOT_ATTEMPTED_TODAY",
            "attempts_today": attempted, "candidate_checks_today": candidates,
            "unavailable_today": unavailable}


def diagnose(state, review, today):
    date.fromisoformat(today)
    if state.get("schema") != STATE_SCHEMA or review.get("schema") != REVIEW_SCHEMA:
        raise ValueError("unexpected private festival schema")
    if review.get("as_of") != today:
        raise ValueError("editorial review date differs from collection date")
    if (review.get("publication_authorized") is not False
            or review.get("safe_to_publish") is not False
            or review.get("publications") != 0):
        raise ValueError("not a review-only source")
    dossiers = review.get("dossiers")
    if not isinstance(dossiers, list) or len(dossiers) > MAX_DOSSIERS:
        raise ValueError("invalid editorial dossiers")
    blocks = Counter()
    statuses = Counter()
    for row in dossiers:
        if (not isinstance(row, dict)
                or row.get("publication_authorized") is not False
                or row.get("safe_to_publish") is not False
                or row.get("review_only") is not True):
            raise ValueError("unsafe editorial dossier")
        reasons = row.get("missing_checks")
        if (not isinstance(reasons, list) or len(reasons) > 50
                or any(not isinstance(s, str) or len(s) > 120 for s in reasons)):
            raise ValueError("invalid editorial blocking reasons")
        status = row.get("status")
        if not isinstance(status, str) or len(status) > 120:
            raise ValueError("invalid dossier status")
        statuses[status] += 1
        blocks.update(set(reasons))
    if len(dossiers) != review.get("dossiers_count"):
        raise ValueError("editorial dossier count mismatch")
    from historical_future_lead_watch import APPROVED as HISTORICAL
    from targeted_institutional_future_watch import SOURCES as INSTITUTIONAL
    return {
        "schema": SCHEMA, "as_of": today,
        "review_only": True, "publication_authorized": False,
        "safe_to_publish": False, "publications": 0,
        "dossiers_total": len(dossiers),
        "drafts_total": review.get("editorial_drafts_count"),
        "public_editions_count": review.get("public_editions_count"),
        "historical_references_count": review.get("historic_references_count"),
        "status_counts": dict(sorted(statuses.items())),
        "blocking_reason_counts": dict(sorted(blocks.items())),
        "historical_watch": _watch(
            state.get("historical_future_source_checks_private"),
            "status", today, expected=HISTORICAL),
        "institutional_watch": _watch(
            state.get("institutional_future_checks_private"),
            "candidate_seen", today, expected=INSTITUTIONAL),
        "note": "Private diagnostics only. A green run is not publication evidence.",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--intake", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    report = _read(args.report)
    if report.get("schema") != "grossesondes.source-watch-report.v1":
        raise ValueError("unexpected collection report")
    today = report.get("date")
    if not isinstance(today, str):
        raise ValueError("missing collection date")
    state = _read(args.intake / "source-watch-state.json")
    review = _read(args.intake / "national-festival-editorial-review.json")
    diagnosis = diagnose(state, review, today)
    (args.intake / "national-festival-yield-diagnostics.json").write_text(
        json.dumps(diagnosis, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print("FESTIVALS_PRIVATE_DIAGNOSTICS: recorded; no public output")


if __name__ == "__main__":
    main()
