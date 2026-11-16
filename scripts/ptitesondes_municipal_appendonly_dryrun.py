"""Municipal append-only REHEARSAL — never a publisher, never a patch.

Runs exclusively in memory against an exact copy of the currently served
catalogue. Each hypothetical addition must pass the existing municipal
independent proof, category/age contract, geo freshness and a stronger
duplicate check. Unknown categories stay blocked by the current merge_policy;
we model an explicitly *hypothetical* future category extension ONLY for QA.

No human approval is inferred, no private token is used, and no path writes.
"""
from copy import deepcopy
from datetime import date
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

from merge_policy import REQUIRED, byid, valid
from official_organizer_proof import canonical_event_title
from proof import norm
from ptitesondes_nonmusic_release_contract import TYPES
from ptitesondes_municipal_preflight import audit_municipal, read_official

SCHEMA = "ptitesondes.municipal_appendonly_rehearsal.v1"
ALLOWED_PLANNING_BLOCKERS = frozenset((
    "municipal_public_prevalidator_not_activated",
    "private_manual_approval_not_present",
    "frontend_v172_category_filter_unverified",
    "category_not_accepted_by_current_public_contract",
    "access_information_requires_manual_review",
    "editorial_conditions_required",
    "conditions_explicit_recheck_required",
))
# No case with a source-derived contradiction can enter even the rehearsal.
NEVER_ADMIT = frozenset((
    "cancelled_or_unavailable", "official_session_changed",
    "already_public", "already_public_semantic_or_range",
    "access_information_requires_manual_review_incomplete",
))


def canonical_sha256(doc):
    return hashlib.sha256(json.dumps(
        doc, ensure_ascii=False, sort_keys=True, allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _event_from_proposal(candidate, checked_on, geo_checked_on):
    """Hypothetical structure only, NOT verified/publishable metadata."""
    event = {
        "id": candidate["review_id"],
        "title": candidate["title"],
        "category": candidate["category_proposal"],
        "category_label": candidate["category_label_proposal"],
        "date_start": candidate["date_start"],
        "date_end": candidate["date_end"],
        "time": candidate["start_local"],
        "city": candidate["city"],
        "department": candidate["department_proposal"],
        "region": candidate["region_proposal"],
        "venue": candidate["venue"],
        "source_url": candidate["official_event_url"],
        "source_label": candidate["source_label_proposal"],
        "lat": candidate["lat"],
        "lng": candidate["lng"],
        "geo_precision": "venue",
        "verified_at": checked_on,
        "geo_verified_at": geo_checked_on,
        "age_label": candidate["age_label_proposal"],
        # No claims of free admission, price, missing registration or
        # unsourced description. The actual UI uses "Voir conditions".
    }
    if candidate["age_min_proposal"] is not None:
        event["age_min"] = candidate["age_min_proposal"]
    if candidate["age_max_proposal"] is not None:
        event["age_max"] = candidate["age_max_proposal"]
    return event


def _overlaps_publication(event, historical):
    """Stricter than the existing merge on same organizer occurrence/date."""
    start = date.fromisoformat(event["date_start"])
    end = date.fromisoformat(event["date_end"])
    signature = (
        canonical_event_title(event), norm(event["city"]), norm(event["venue"])
    )
    for previous in historical:
        first = previous.get("date_start")
        last = previous.get("date_end") or first
        try:
            a, b = date.fromisoformat(first), date.fromisoformat(last)
        except (ValueError, TypeError):
            # Malformed historical data cannot be changed here.
            return True
        if a > end or b < start:
            continue
        if previous.get("source_url") == event["source_url"]:
            return True
        prev_sig = (
            canonical_event_title(previous), norm(previous.get("city")),
            norm(previous.get("venue"))
        )
        if prev_sig == signature:
            return True
    return False


def _valid_stamp(value, today):
    if not isinstance(value, str):
        return False
    try:
        checked = date.fromisoformat(value)
    except ValueError:
        return False
    return checked.isoformat() == value and 0 <= (today - checked).days <= 14


def rehearse(catalogue, review, access, today, source_get=read_official,
             verified_dates=None):
    """Return counters only; NEVER return an updated catalogue or patch.

    verified_dates maps review IDs to separately supplied official and
    geographic verification dates. No dates are minted from this script.
    The hypothetical count has *zero* relation to human release approvals.
    """
    if type(today) is not date:
        raise ValueError("invalid_rehearsal_date")
    if not isinstance(verified_dates, dict):
        raise ValueError("missing_reviewed_verification_dates")
    before = canonical_sha256(catalogue)
    historical = byid(catalogue)
    previous_events = catalogue["events"]
    original = deepcopy(catalogue)
    report = audit_municipal(review, access, catalogue, today, get=source_get)
    if report["examined"] != len(review["candidates"]):
        raise ValueError("municipal_proof_count_mismatch")
    private_checks = report["details_private_only"]
    if len({row["review_id"] for row in private_checks}) != len(private_checks):
        raise ValueError("duplicate_municipal_proof_ids")

    # Existing public rules: no new non-musical category is currently allowed.
    current_categories = {event.get("category") for event in previous_events}
    permitted_model_categories = current_categories | set(TYPES)
    fields = set().union(*(set(event) for event in previous_events))
    simulated = deepcopy(original)
    accepted_in_model = 0
    blocked = 0
    would_require_review = 0
    seen_ids = set(historical)
    proof_by_id = {item["review_id"]: item for item in private_checks}
    for candidate in review["candidates"]:
        rid = candidate["review_id"]
        reasons = set(proof_by_id[rid]["reasons"])
        if reasons - ALLOWED_PLANNING_BLOCKERS or reasons & NEVER_ADMIT:
            blocked += 1
            continue
        # Every proof record must retain the mandatory no-approval blockers.
        if not {"private_manual_approval_not_present",
                "municipal_public_prevalidator_not_activated"} <= reasons:
            blocked += 1
            continue
        # A "not stated" condition must never be silently called free.
        condition = next((a for a in access["reviewed"]
                          if a.get("review_id") == rid), None)
        if not isinstance(condition, dict) or condition.get("price_evidence") != "not_stated" or condition.get("registration_evidence") != "not_stated":
            blocked += 1
            continue
        stamps = verified_dates.get(rid)
        if not isinstance(stamps, dict) or set(stamps) != {
            "source_checked_on", "geo_checked_on",
        }:
            blocked += 1
            continue
        source_day = stamps["source_checked_on"]
        geo_day = stamps["geo_checked_on"]
        if not _valid_stamp(source_day, today) or not _valid_stamp(geo_day, today):
            blocked += 1
            continue
        event = _event_from_proposal(candidate, source_day, geo_day)
        if rid in seen_ids or _overlaps_publication(event, simulated["events"]):
            blocked += 1
            continue
        # This check would FAIL in the current publisher: category not yet
        # allowlisted. We NEVER override the real publisher category set.
        real_ok, reason = valid(event, current_categories, fields, today)
        if real_ok or reason != "catégorie inconnue":
            blocked += 1
            continue
        model_ok, reason = valid(event, permitted_model_categories, fields, today)
        if not model_ok or event["category"] not in TYPES:
            blocked += 1
            continue
        # We never call merge() with a spoofed reference to bypass its gates.
        # Only in-memory prefix append; not a real publisher release path.
        simulated["events"].append(event)
        seen_ids.add(rid)
        accepted_in_model += 1
        would_require_review += 1

    if canonical_sha256(catalogue) != before or catalogue != original:
        raise ValueError("source_catalogue_mutated")
    if simulated["events"][:len(previous_events)] != previous_events:
        raise ValueError("historic_prefix_changed")
    if simulated["updated_at"] != original["updated_at"]:
        raise ValueError("catalogue_update_timestamp_tampered")
    if len(simulated["events"]) != len(previous_events) + accepted_in_model:
        raise ValueError("append_only_count_mismatch")
    return {
        "schema": SCHEMA,
        "mode": "in_memory_hypothetical_only_no_patch_no_publication",
        "catalogue_sha256": before,
        "historical_preserved": len(previous_events),
        "catalogue_unchanged": True,
        "historical_records_modified": 0,
        "historical_records_deleted": 0,
        "hypothetical_additions": accepted_in_model,
        "hypothetical_total": len(simulated["events"]),
        "blocked_from_rehearsal": blocked,
        "private_reviews_still_required": would_require_review,
        "current_publisher_supports_new_categories": False,
        "approval_granted_to_publisher": False,
        "publication_ready": 0,
        "public_writes": 0,
    }


def main():
    import argparse
    p = argparse.ArgumentParser()
    for name in ("catalogue", "review", "access", "verified-dates"):
        p.add_argument("--" + name, required=True, type=Path)
    p.add_argument("--date", type=date.fromisoformat, required=True)
    args = p.parse_args()
    read = lambda key: json.loads(getattr(args, key).read_text(encoding="utf-8"))
    result = rehearse(read("catalogue"), read("review"), read("access"),
                      args.date, verified_dates=read("verified_dates"))
    # Print only non-identifying numbers. No output file path, patch, commits,
    # private IDs or URL fields. This program cannot write any catalogue.
    print(json.dumps({
        "historical_preserved": result["historical_preserved"],
        "hypothetical_additions": result["hypothetical_additions"],
        "blocked_from_rehearsal": result["blocked_from_rehearsal"],
        "publication_ready": 0, "public_writes": 0,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
