"""Private-only independent evidence work planner for HTML family outings.

This does NOT verify an event, confer source rights, approve a venue, release a
candidate, or publish. Its input is the already-validated private HTML queue;
it prepares a bounded cross-city list of evidence challenges for trusted
workers without per-event hand-coded allowlists.

No file/network/Git access or private row logging. The task list stays
PRIVATE. Only fixed anonymous numeric totals may be reported publicly.
"""
from collections import defaultdict, deque
from datetime import date
from urllib.parse import urlsplit

from proof import norm
from ptitesondes_nonmusical_private_queue_handoff import (
    _validate_row, MAX_QUEUE,
)

SCHEMA = "ptitesondes.html_independent_review_plan.v1"
MAX_WORK_ITEMS = 80
MAX_SOURCE_ITEMS = 24
MAX_SESSION_TASKS = 8
CHALLENGES = (
    "refresh_pinned_exact_session",
    "verify_family_audience_and_access",
    "verify_current_organizer_with_independent_authority",
    "resolve_independent_venue_and_geo",
    "fetch_live_catalogue_and_check_exact_slot",
    "recheck_generic_nonmusical_release_contract",
)
SOURCE_CHALLENGES = {
    "institutional_source_policy_missing": "register_independently_attested_source",
    "institutional_source_policy_invalid": "audit_curated_institutional_registry",
    "institutional_source_policy_pending": "review_factual_reuse_policy_once_per_host",
    "institutional_source_policy_expired": "renew_source_factual_reuse_review",
    "institutional_source_policy_restricted": "maintain_restricted_source_hold",
}
COLLISION_CHALLENGES = {
    "historical_collision_ambiguous": "independently_recheck_distinct_clock",
}
TERMINAL_HOLDS = frozenset((
    "historical_duplicate", "institutional_source_policy_restricted",
))
ALL_TASKS = frozenset(CHALLENGES) | frozenset(SOURCE_CHALLENGES.values()) | frozenset(COLLISION_CHALLENGES.values())
REPORT_KEYS = (
    "input_private_reviews", "future_sessions", "expired_sessions",
    "duplicates_held", "restricted_sources_held",
    "deferred_by_existing_retry", "sessions_due",
    "selected_sessions", "selected_source_policies",
    "pending_sessions_unselected", "cities_covered_in_batch",
    "distinct_cities_due", "distinct_host_policies_due",
)


def _checked_queue(queue):
    if type(queue) is not list or len(queue) > MAX_QUEUE:
        raise ValueError("independent_review_input_invalid")
    ids = set()
    for row in queue:
        _validate_row(row)
        if row["review_id"] in ids:
            raise ValueError("independent_review_duplicate_id")
        ids.add(row["review_id"])


def _round_robin(groups, limit, today):
    """Equitable rotating city start, then one near-term session per city.

    Dates stay exact (no age/price restrictions or whitelist of venues).
    Clock is already part of every review ID and is never merged.
    """
    if not groups:
        return []
    keys = sorted(groups)
    shift = today.toordinal() % len(keys)
    keys = keys[shift:] + keys[:shift]
    active = deque(keys)
    selected = []
    while active and len(selected) < limit:
        key = active.popleft()
        selected.append(groups[key].popleft())
        if groups[key]:
            active.append(key)
    return selected


def plan_independent_reviews(queue, today, *, limit=40, source_limit=12):
    """Private challenges plus a separate anonymous report; NEVER an approval.

    A challenge means 'obtain and verify this evidence', not 'this evidence was
    obtained'. Source rights are requested ONCE PER HOST; unknown price, exact
    age and registration are not invented and never pre-empt discovery.
    """
    if (type(today) is not date or type(limit) is not int
            or not 1 <= limit <= MAX_WORK_ITEMS
            or type(source_limit) is not int
            or not 1 <= source_limit <= MAX_SOURCE_ITEMS):
        raise ValueError("independent_review_bad_options")
    _checked_queue(queue)
    counts = {key: 0 for key in REPORT_KEYS}
    counts["input_private_reviews"] = len(queue)
    source_records = {}
    groups = defaultdict(list)
    for row in queue:
        day = date.fromisoformat(row["date_start"])
        if day < today:
            counts["expired_sessions"] += 1
            continue
        counts["future_sessions"] += 1
        reason = row["reason_code"]
        if reason == "historical_duplicate":
            counts["duplicates_held"] += 1
            continue
        # Restricted institutional material must not be retried as if a
        # temporary outage could grant permission.
        if reason == "institutional_source_policy_restricted":
            counts["restricted_sources_held"] += 1
        if (row["review_class"] == "retryable"
                and row["next_retry_on"] > today.isoformat()):
            counts["deferred_by_existing_retry"] += 1
            continue
        # Classify independent work even if existing v1 queue called the
        # missing venue "manual". A new unknown place is a discovery task,
        # never automatic rejection due to absent pre-reviewed venue name.
        if reason != "institutional_source_policy_restricted":
            groups[norm(row["city"])].append(row)
        # Host rights and provenance are a SOURCE question, not N identical
        # legal tasks for N workshops in the same institution.
        if reason in SOURCE_CHALLENGES:
            hostname = urlsplit(row["source_url"]).hostname
            if hostname and hostname not in source_records:
                source_records[hostname] = row
    for items in groups.values():
        items.sort(key=lambda r: (
            r["date_start"], r["last_seen"], r["review_id"],
        ))
    counts["distinct_cities_due"] = len(groups)
    counts["sessions_due"] = sum(len(v) for v in groups.values())
    selected = _round_robin(
        {city: deque(rows) for city, rows in groups.items()}, limit, today)
    # Only private review IDs leave this function, not source URLs, towns,
    # coordinates, event titles, descriptions, licence claims or event data.
    session_tasks = []
    for row in selected:
        tasks = list(CHALLENGES)
        if row["reason_code"] in COLLISION_CHALLENGES:
            tasks.insert(0, COLLISION_CHALLENGES[row["reason_code"]])
        if len(tasks) > MAX_SESSION_TASKS:
            raise ValueError("independent_review_task_capacity")
        session_tasks.append({
            "review_id": row["review_id"], "challenges": tasks,
            "evidence_verified": False, "admission_authorized": False,
        })
    source_items = sorted(
        source_records.values(),
        key=lambda r: (r["first_seen"], r["review_id"]),
    )[:source_limit]
    source_tasks = [{
        "sample_private_review_id": row["review_id"],
        "challenge": SOURCE_CHALLENGES[row["reason_code"]],
        "legal_rights_attested": False,
        "source_approved": False,
    } for row in source_items]
    counts["selected_sessions"] = len(session_tasks)
    counts["selected_source_policies"] = len(source_tasks)
    counts["pending_sessions_unselected"] = counts["sessions_due"] - len(session_tasks)
    counts["cities_covered_in_batch"] = len({
        norm(row["city"]) for row in selected
    })
    counts["distinct_host_policies_due"] = len(source_records)
    counts["work_items_total"] = len(session_tasks) + len(source_tasks)
    counts["public_writes"] = 0
    counts["publisher_connected"] = False
    counts["publication_ready"] = False
    counts["approved"] = False
    counts["contains_candidate_data"] = False
    return {
        "schema": SCHEMA,
        "private_tasks": {
            "sessions": session_tasks, "source_policies": source_tasks,
        },  # NEVER LOG this mapping or serialize it to a public artifact
        "report": dict(schema=SCHEMA, **counts),  # fixed count keys only
    }
