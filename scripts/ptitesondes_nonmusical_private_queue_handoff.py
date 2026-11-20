"""Private-only HTML family-session review queue (NOT a publisher).

This module is an in-memory compatibility bridge for the existing PRIVATE
automation-intake/ptitesondes storage. It intentionally uses a separate
html-review-candidates.json rather than altering backlog.json: the current
OpenAgenda intake key omits a session's clock and would collapse two sessions
on the same date.

Only a trusted runner, having independently fetched its pinned official index,
child page and venue/history registries, may pass packets. This function
RECOMPUTES the HTML gate and facts, never accepts a collector's approval or
a caller-supplied route result. It does not fetch, log, write, publish or issue
a ptitesondes.patch.v1. No candidate may enter the music publisher.
"""
from copy import deepcopy
from datetime import date, timedelta
import hashlib
import json
import re
from urllib.parse import urlsplit

from proof import norm
from ptitesondes_factual_reuse_preflight import prepare_private_html_factual_draft
from ptitesondes_family_national_scope import FAMILY_TYPES, LEGACY_MUSICAL
from ptitesondes_nonmusical_html_gate_router import (
    ACTIONS, STAGES, route_nonmusical_html_session,
)

SCHEMA = "ptitesondes.html_private_review_queue.v1"
MAX_BATCH = 30
MAX_QUEUE = 4000
PACKET_KEYS = frozenset((
    "lead", "page", "trusted_index", "child_prefix", "independent_context",
))
ROW_KEYS = frozenset((
    "schema", "review_id", "source_url", "title", "city", "venue",
    "category", "date_start", "start_local", "reason_code",
    "next_private_review_action", "review_class", "next_retry_on",
    "first_seen", "last_seen", "observations", "status",
    "safe_to_publish", "approved", "published",
))
# A temporary registry problem or a stale independent snapshot should be
# retried, but never interpreted as verified provenance.
RETRYABLE = frozenset((
    "historical_snapshot_unchecked",
    "reviewed_venue_unchecked",
    "reviewed_venue_untrusted",
    "institutional_source_policy_expired",
    "institutional_source_policy_invalid",
))
CLOCK = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d\Z")
FORBIDDEN = frozenset(("additions", "updates", "patch", "publication_ready"))


def _day(value):
    if type(value) is not str:
        return False
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _text(value, limit):
    return (type(value) is str and 1 <= len(value) <= limit
            and value == value.strip()
            and re.search(r"[\x00-\x1f\x7f<>]", value) is None)


def _source_url(value):
    if not _text(value, 1000):
        return False
    try:
        u = urlsplit(value)
        return (u.scheme == "https" and bool(u.hostname) and
                u.username is None and u.password is None and
                u.hostname not in ("localhost", "127.0.0.1", "::1") and
                u.fragment == "")
    except ValueError:
        return False


def _identity(row):
    # Both exact day and local clock are mandatory. The source URL keeps
    # distinct official pages traceable even if they describe similar shows.
    return [
        row["source_url"], norm(row["title"]), norm(row["city"]),
        norm(row["venue"]), row["date_start"], row["start_local"],
    ]


def _id(row):
    body = json.dumps(_identity(row), ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False)
    return "html-review-" + hashlib.sha256(body.encode("utf-8")).hexdigest()[:32]


def _validate_row(row):
    if (type(row) is not dict or set(row) != ROW_KEYS
            or row.get("schema") != SCHEMA
            or row.get("status") != "pending_independent_review"
            or row.get("safe_to_publish") is not False
            or row.get("approved") is not False
            or row.get("published") is not False
            or not _source_url(row.get("source_url"))
            or not all(_text(row.get(k), size) for k, size in (
                ("title", 180), ("city", 120), ("venue", 160)))
            or row.get("category") not in FAMILY_TYPES
            or row.get("category") in LEGACY_MUSICAL
            or not _day(row.get("date_start"))
            or type(row.get("start_local")) is not str
            or CLOCK.fullmatch(row["start_local"]) is None
            or row.get("reason_code") not in STAGES
            or row.get("next_private_review_action") != ACTIONS[row["reason_code"]]
            or row.get("review_class") != (
                "retryable" if row["reason_code"] in RETRYABLE else "manual"
            )
            or not _day(row.get("first_seen"))
            or not _day(row.get("last_seen"))
            or row["first_seen"] > row["last_seen"]
            or not (type(row.get("observations")) is int
                    and 1 <= row["observations"] <= 10**8)):
        raise ValueError("invalid_private_html_review_queue_record")
    retry = row.get("next_retry_on")
    if row["review_class"] == "retryable":
        if not _day(retry):
            raise ValueError("invalid_private_html_retry_day")
    elif retry is not None:
        raise ValueError("invalid_private_html_manual_review_day")
    if row.get("review_id") != _id(row):
        raise ValueError("invalid_private_html_review_identity")


def _row_from_proof(draft, route, today, previous):
    row = {
        "schema": SCHEMA,
        "source_url": draft.get("source_url"),
        "title": draft.get("source_title_identity_only"),
        "city": draft.get("city"),
        "venue": draft.get("venue"),
        "category": draft.get("category"),
        "date_start": draft.get("date_start"),
        "start_local": draft.get("start_local"),
        "reason_code": route["stage"],
        "next_private_review_action": ACTIONS[route["stage"]],
        "review_class": "retryable" if route["stage"] in RETRYABLE else "manual",
        "next_retry_on": (today + timedelta(days=2)).isoformat()
        if route["stage"] in RETRYABLE else None,
        "first_seen": previous["first_seen"] if previous else today.isoformat(),
        "last_seen": today.isoformat(),
        "observations": min(previous["observations"] + 1, 10**8)
        if previous else 1,
        "status": "pending_independent_review",
        "safe_to_publish": False, "approved": False, "published": False,
    }
    if not (_source_url(row["source_url"])
            and all(_text(row[k], n) for k, n in (
                ("title", 180), ("city", 120), ("venue", 160)))
            and _day(row["date_start"])
            and type(row["start_local"]) is str
            and CLOCK.fullmatch(row["start_local"])):
        return None
    row["review_id"] = _id(row)
    _validate_row(row)
    return row


def reconcile_private_html_review_queue(existing, packets, today):
    """Produce private queue data and PUBLIC-SAFE aggregate counts, in memory.

    The returned queue is confidential and MUST be written only to the private
    branch by a future authorized runner step. The report is fixed-shape
    counts; never print/log the queue or packet, even on error.
    """
    if (type(today) is not date or type(existing) is not list
            or type(packets) is not list or len(existing) > MAX_QUEUE
            or len(packets) > MAX_BATCH):
        raise ValueError("invalid_private_html_review_batch")
    stored = {}
    for original in existing:
        _validate_row(original)
        if original["review_id"] in stored:
            raise ValueError("duplicate_private_html_review_id")
        stored[original["review_id"]] = deepcopy(original)
    report = {
        "schema": SCHEMA, "input_packets": len(packets),
        "previous_private_reviews": len(stored),
        "new_private_reviews": 0, "rechecked_private_reviews": 0,
        "held_without_exact_review_facts": 0, "malformed_packets_held": 0,
        "retained_unseen_private_reviews": 0, "total_private_reviews": 0,
        "retryable_private_reviews": 0, "manual_private_reviews": 0,
        "possible_cross_source_same_session": 0,
        "catalogue_additions": 0, "private_patch_additions": 0,
        "public_writes": 0, "publisher_connected": False,
        "publication_ready": False, "approval_granted": False,
    }
    seen = set()
    for packet in packets:
        if type(packet) is not dict or set(packet) != PACKET_KEYS:
            report["malformed_packets_held"] += 1
            continue
        try:
            route = route_nonmusical_html_session(
                packet["lead"], packet["page"], packet["trusted_index"],
                packet["child_prefix"], packet["independent_context"], today)
            if (route.get("stage") not in STAGES
                    or route.get("source_exact_session_confirmed") is not True
                    or route.get("source_only_factual_draft_possible") is not True
                    or route.get("can_submit_to_publisher") is not False
                    or route.get("publication_ready") is not False):
                report["held_without_exact_review_facts"] += 1
                continue
            facts = prepare_private_html_factual_draft(
                packet["lead"], packet["page"], packet["trusted_index"],
                packet["child_prefix"])
            if (facts.get("status") != "private_draft_for_rights_review"
                    or type(facts.get("draft")) is not dict
                    or facts["draft"].get("safe_to_publish") is not False):
                report["held_without_exact_review_facts"] += 1
                continue
            draft = facts["draft"]
            if (draft.get("category") not in FAMILY_TYPES
                    or draft["category"] in LEGACY_MUSICAL):
                report["held_without_exact_review_facts"] += 1
                continue
            skeleton = {
                "source_url": draft.get("source_url"),
                "title": draft.get("source_title_identity_only"),
                "city": draft.get("city"), "venue": draft.get("venue"),
                "date_start": draft.get("date_start"),
                "start_local": draft.get("start_local"),
            }
            if (not _source_url(skeleton["source_url"])
                    or not all(_text(skeleton.get(k), size) for k, size in (
                        ("title", 180), ("city", 120), ("venue", 160)))
                    or not _day(skeleton["date_start"])
                    or type(skeleton["start_local"]) is not str
                    or CLOCK.fullmatch(skeleton["start_local"]) is None):
                report["held_without_exact_review_facts"] += 1
                continue
            rid = _id(skeleton)
            row = _row_from_proof(draft, route, today, stored.get(rid))
            if row is None:
                report["held_without_exact_review_facts"] += 1
                continue
            # Duplicate packets within one run are not repeated observations.
            if rid in seen:
                continue
            seen.add(rid)
            if rid in stored:
                report["rechecked_private_reviews"] += 1
            else:
                if len(stored) >= MAX_QUEUE:
                    raise ValueError("private_html_review_queue_capacity_reached")
                report["new_private_reviews"] += 1
            stored[rid] = row
        except (KeyError, ValueError, TypeError, AttributeError):
            # Never reveal source material in exception strings / public logs.
            report["held_without_exact_review_facts"] += 1
    report["retained_unseen_private_reviews"] = len(stored) - len(seen)
    report["total_private_reviews"] = len(stored)
    rows = sorted(stored.values(), key=lambda r: r["review_id"])
    report["retryable_private_reviews"] = sum(
        r["review_class"] == "retryable" for r in rows)
    report["manual_private_reviews"] = len(rows) - report["retryable_private_reviews"]
    # A cross-source match needs independent judgement, never silent deletion.
    groups = {}
    for row in rows:
        key = tuple(norm(row[k]) for k in ("title", "city", "venue")) + (
            row["date_start"], row["start_local"])
        groups.setdefault(key, set()).add(row["source_url"])
    report["possible_cross_source_same_session"] = sum(
        len(urls) for urls in groups.values() if len(urls) > 1)
    return {"queue": rows, "report": report}
