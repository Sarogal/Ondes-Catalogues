"""Private, offline-only yield diagnosis after festival editorial reconciliation.

No HTTP requests, no publication decisions, no public artifacts. An absent
watch key means NOT_OBSERVED, never a successful zero-result scan.
"""
import argparse
from collections import Counter
from datetime import date
import json
import re
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



# This comparison records changes in PRIVATE research observations, not proofs
# of publication readiness. A new date *hint* is not a confirmed event date.
DOSS_ID = re.compile(r"^national-[a-f0-9]{20}$")


def _review_rows(review, today):
    """Validate a stored review before reading identities or research signals."""
    if (not isinstance(review, dict) or review.get("schema") != REVIEW_SCHEMA
            or review.get("review_only") is not True
            or review.get("publication_authorized") is not False
            or review.get("safe_to_publish") is not False
            or review.get("publications") != 0):
        raise ValueError("unsafe comparison review")
    as_of = review.get("as_of")
    if (not isinstance(as_of, str) or
            date.fromisoformat(as_of) > date.fromisoformat(today)):
        raise ValueError("future or absent comparison timestamp")
    rows = review.get("dossiers")
    if (not isinstance(rows, list) or len(rows) > MAX_DOSSIERS
            or len(rows) != review.get("dossiers_count")):
        raise ValueError("malformed comparison dossier count")
    index = {}
    for row in rows:
        if (not isinstance(row, dict) or
                row.get("safe_to_publish") is not False or
                row.get("publication_authorized") is not False or
                row.get("review_only") is not True):
            raise ValueError("unauthorized comparison dossier")
        key = row.get("id")
        if not isinstance(key, str) or not DOSS_ID.fullmatch(key) or key in index:
            raise ValueError("invalid or duplicate comparison identity")
        status = row.get("status")
        if not isinstance(status, str) or len(status) > 120:
            raise ValueError("invalid comparison status")
        checks = row.get("missing_checks")
        if (not isinstance(checks, list) or len(checks) > 50
                or any(not isinstance(x, str) or len(x) > 120 for x in checks)):
            raise ValueError("invalid comparison blockers")
        index[key] = row
    return as_of, index


def _signals(row):
    """Separate observed evidence from references to old-edition metadata."""
    evidence, research = set(), set()
    primary = row.get("primary_observation")
    if primary is not None:
        if not isinstance(primary, dict):
            raise ValueError("invalid primary comparison observation")
        if primary.get("dates_visible_in_primary") is True:
            start, end = primary.get("start_date_hint"), primary.get("end_date_hint")
            if isinstance(start, str) and isinstance(end, str):
                evidence.add(("primary_date_claim", start, end))
    for field, kind in (
            ("historical_homepage_date_hints_review_only", "homepage_date_hint"),
            ("institutional_future_date_hints_review_only", "institutional_date_hint")):
        hints = row.get(field, [])
        if not isinstance(hints, list) or len(hints) > 12:
            raise ValueError("invalid comparison dates")
        for hint in hints:
            if not isinstance(hint, dict):
                raise ValueError("invalid comparison hint")
            start, end = hint.get("start_date_hint"), hint.get("end_date_hint")
            if isinstance(start, str) and isinstance(end, str):
                date.fromisoformat(start)
                date.fromisoformat(end)
                evidence.add((kind, start, end, str(hint.get("season_hint"))))
            if field.startswith("institutional") and hint.get(
                    "organizer_name_home_review_only"):
                research.add(("current_home_organizer_name_hint",))
    press = row.get("press_date_observations_review_only", [])
    if not isinstance(press, list) or len(press) > 4:
        raise ValueError("invalid private press evidence")
    from targeted_press_edition_watch import SOURCES as APPROVED_PRESS
    approved_urls = {item["url"] for item in APPROVED_PRESS.values()}
    for source in press:
        if (not isinstance(source, dict)
                or source.get("article_url") not in approved_urls
                or source.get("review_only") is not True
                or source.get("publisher_origin_assessed") is not False
                or source.get("independence_verified") is not False
                or source.get("publication_authorized") is not False):
            raise ValueError("unsafe private press source")
        claims = source.get("claims")
        if not isinstance(claims, list) or len(claims) > 2:
            raise ValueError("invalid press claims")
        for claim in claims:
            if (not isinstance(claim, dict)
                    or claim.get("review_only") is not True
                    or claim.get("independence_verified") is not False
                    or claim.get("publication_authorized") is not False
                    or claim.get("edition_dates_verified") is not False):
                raise ValueError("unsafe press claim in comparison")
            start, end = claim.get("start_date_hint"), claim.get("end_date_hint")
            date.fromisoformat(start)
            date.fromisoformat(end)
            evidence.add(("press_article_date_claim", source["article_url"],
                          start, end, claim.get("season_hint")))
    details = row.get("regional_detail_observations", [])
    if not isinstance(details, list) or len(details) > 50:
        raise ValueError("invalid comparison regional details")
    for item in details:
        if not isinstance(item, dict):
            raise ValueError("invalid comparison regional observation")
        if item.get("name_seen") is True and item.get("edition_year_near_name") is True:
            evidence.add(("regional_name_year_observation", str(item.get("url", ""))))
    archive = row.get("archive_identity_hints", [])
    if not isinstance(archive, list) or len(archive) > 8:
        raise ValueError("invalid comparison historic hints")
    for hint in archive:
        if not isinstance(hint, dict):
            raise ValueError("invalid comparison archive")
        slug = hint.get("slug")
        if not isinstance(slug, str) or len(slug) > 160:
            raise ValueError("invalid comparison archive identity")
        for key in ("organizer", "city", "department", "venue"):
            if hint.get("prior_edition_" + key + "_review_only"):
                research.add(("historical_" + key + "_hint", slug))
    return evidence, research


def compare_progress(previous, current, today):
    """A missing prior review is UNKNOWN, never evidence of zero progress."""
    if previous is None:
        return {"status": "NOT_OBSERVED", "previous_as_of": None}
    previous_date, before = _review_rows(previous, today)
    _, after = _review_rows(current, today)
    deltas = []
    new_ids = sorted(set(after) - set(before))
    absent_ids = sorted(set(before) - set(after))
    totals = dict(new_dossiers=len(new_ids), disappeared_dossiers=len(absent_ids),
                  evidence_gained_dossiers=0, evidence_lost_dossiers=0,
                  research_hints_gained_dossiers=0, blockers_removed_dossiers=0,
                  unchanged_existing_dossiers=0)
    for key in sorted(set(before) & set(after)):
        old, new = before[key], after[key]
        old_evidence, old_research = _signals(old)
        evidence, research = _signals(new)
        gained, lost = evidence - old_evidence, old_evidence - evidence
        gained_research = research - old_research
        removed_blocks = set(old["missing_checks"]) - set(new["missing_checks"])
        added_blocks = set(new["missing_checks"]) - set(old["missing_checks"])
        status_changed = new["status"] != old["status"]
        totals["evidence_gained_dossiers"] += bool(gained)
        totals["evidence_lost_dossiers"] += bool(lost)
        totals["research_hints_gained_dossiers"] += bool(gained_research)
        totals["blockers_removed_dossiers"] += bool(removed_blocks)
        if not (gained or lost or gained_research or removed_blocks
                or added_blocks or status_changed):
            totals["unchanged_existing_dossiers"] += 1
            continue
        deltas.append({
            "id": key, "before_status": old["status"], "after_status": new["status"],
            "evidence_added": sorted({x[0] for x in gained}),
            "evidence_lost": sorted({x[0] for x in lost}),
            "research_hints_added": sorted({x[0] for x in gained_research}),
            "blockers_removed": sorted(removed_blocks),
            "blockers_added": sorted(added_blocks),
        })
    return {
        "status": "COMPARED_SAME_DAY" if previous_date == today else "COMPARED",
        "previous_as_of": previous_date,
        **totals, "new_dossier_ids": new_ids,
        "disappeared_dossier_ids": absent_ids,
        "changed_dossiers": deltas,
        "note": ("Hints, historical metadata and removed blockers are not "
                 "publication approvals. A disappeared dossier may be stale, not resolved."),
    }


def diagnose(state, review, today, previous_review=None):
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
        "progress_since_previous_review": compare_progress(previous_review, review, today),
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
    parser.add_argument("--previous-review", type=Path)
    args = parser.parse_args()
    report = _read(args.report)
    if report.get("schema") != "grossesondes.source-watch-report.v1":
        raise ValueError("unexpected collection report")
    today = report.get("date")
    if not isinstance(today, str):
        raise ValueError("missing collection date")
    state = _read(args.intake / "source-watch-state.json")
    review = _read(args.intake / "national-festival-editorial-review.json")
    previous = (_read(args.previous_review) if args.previous_review
                and args.previous_review.is_file() else None)
    diagnosis = diagnose(state, review, today, previous_review=previous)
    (args.intake / "national-festival-yield-diagnostics.json").write_text(
        json.dumps(diagnosis, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print("FESTIVALS_PRIVATE_DIAGNOSTICS: recorded; no public output")


if __name__ == "__main__":
    main()
