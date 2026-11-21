"""PRIVATE national campaign segment -> open-world investigation rotation.

The existing national OA index campaign persists validated, paginated event
segments containing TWO equal-priority research lanes: category-proposed
`event_leads` and previously unclassified artistic formats. This bridge
consumes BOTH lanes automatically, without a curated agenda, venue, city,
organizer, category, wording, or domain list.

Each call gives a bounded slice of the segment fair access to the open-world
OA -> DILA -> municipal website -> source -> exact-session pipeline (#601).
The cursor and per-event checkpoints are in-memory results for an encrypted/
permission-restricted private store. No scheduler, Git write or public patch.
Unknown location, category or missing times is a RESEARCH HOLD, never silently
deleted and never interpreted as event approval. No source metadata is trusted
as a permission to publish.
"""
from copy import deepcopy
from datetime import date
from hashlib import sha256
import json
import re

from ptitesondes_openagenda_national_event_research import valid_after
from ptitesondes_private_national_event_campaign import _validate_segment
from ptitesondes_open_world_municipal_bootstrap import _safe_research_lead
from ptitesondes_open_world_candidate_rotation import (
    SCHEMA as ROTATION_SCHEMA,
    rotate_private_open_world_lead,
)
from ptitesondes_openagenda_v2_direct_evidence import _valid_public_read_key

SCHEMA = "ptitesondes.private_national_segment_rotation_bridge.v1"
STATE_SCHEMA = "ptitesondes.private_national_segment_rotation_cursor.v1"
MAX_EVENTS_PER_STEP = 4
MAX_SEGMENT_EVENTS = 120
MAX_REPORT_BYTES = 8_000_000
MAX_STATE_BYTES = 15_000_000

DONE = "private_daily_discovery_pass_exhausted"
VALID_ROTATION_STATUSES = frozenset((
    "invalid_private_rotation_request",
    "stale_or_invalid_private_checkpoint",
    "live_source_bootstrap_not_confirmed",
    "municipal_crawl_requires_recheck",
    "untrusted_municipal_crawl_discovery",
    "private_source_queue_capacity_requires_replay",
    "untrusted_private_candidate_review",
    "private_seen_capacity_requires_replay",
    "private_rotation_in_progress",
    DONE,
))
DEFER = frozenset((
    "missing_exact_sessions_for_research",
    "missing_municipality_for_research",
    "upstream_segment_candidate_untrusted",
))


def _fingerprint(document):
    if not isinstance(document, dict):
        return None
    try:
        raw = json.dumps(document, sort_keys=True, ensure_ascii=False,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        return None
    return sha256(raw).hexdigest() if 0 < len(raw) <= MAX_REPORT_BYTES else None


def _segment_items(report, today):
    """Validate original campaign record, then preserve ALL research candidates."""
    if not isinstance(report, dict) or type(today) is not date:
        return None
    meta = report.get("campaign_meta")
    if (not isinstance(meta, dict)
            or set(meta) != {"source_sha256", "scan_day",
                             "agenda_index", "segment", "start_cursor"}
            or not isinstance(meta["source_sha256"], str)
            or re.fullmatch(r"[a-f0-9]{64}", meta["source_sha256"]) is None
            or meta["scan_day"] != today.isoformat()
            or type(meta["agenda_index"]) is not int
            or type(meta["segment"]) is not int
            or not 0 <= meta["agenda_index"] < 160
            or not 0 <= meta["segment"] <= 10000
            or (meta["start_cursor"] is not None
                and not valid_after(meta["start_cursor"]))):
        return None
    agenda = {
        "agenda_uid": report.get("agenda_uid"),
        "agenda_slug": report.get("agenda_slug"),
    }
    try:
        _validate_segment(report, agenda, meta)
    except (ValueError, TypeError, KeyError, OverflowError):
        return None
    normal = report["event_leads"]
    unknown = report.get("unclassified_editorial_research_only", [])
    if len(normal) + len(unknown) > MAX_SEGMENT_EVENTS:
        return None
    items = []
    seen = set()
    for role, rows in (("category_proposed", normal),
                       ("unclassified_artistic_research", unknown)):
        for lead in rows:
            uid = lead.get("event_uid") if isinstance(lead, dict) else None
            if (type(uid) is not int or uid in seen
                    or lead.get("agenda_uid") != agenda["agenda_uid"]
                    or lead.get("agenda_slug") != agenda["agenda_slug"]
                    or lead.get("publication_ready") is not False
                    or lead.get("public_writes") != 0):
                return None
            seen.add(uid)
            items.append((uid, role, lead))
    # Independent of initial classifier, no fixed editorial/category ordering.
    return sorted(items, key=lambda entry: entry[0])


def _initial(items, digest, today):
    return {
        "schema": STATE_SCHEMA, "source_sha256": digest,
        "scan_day": today.isoformat(),
        "next_index": 0, "full_passes_completed": 0,
        "items": [
            {"event_uid": uid, "status": "not_checked",
             "attempts": 0, "rotation_checkpoint": None}
            for uid, _, _ in items
        ],
    }


def _state_ok(state, items, digest, today):
    if (not isinstance(state, dict)
            or set(state) != {"schema", "source_sha256", "scan_day",
                              "next_index", "full_passes_completed", "items"}
            or state["schema"] != STATE_SCHEMA
            or state["source_sha256"] != digest
            or state["scan_day"] != today.isoformat()
            or type(state["items"]) is not list
            or len(state["items"]) != len(items)
            or type(state["next_index"]) is not int
            or not 0 <= state["next_index"] <= len(items)
            or type(state["full_passes_completed"]) is not int
            or not 0 <= state["full_passes_completed"] < 10**9):
        return False
    for entry, (uid, _, _) in zip(state["items"], items):
        if (type(entry) is not dict
                or set(entry) != {"event_uid", "status", "attempts",
                                  "rotation_checkpoint"}
                or entry["event_uid"] != uid
                or type(entry["status"]) is not str
                or entry["status"] not in (
                    {"not_checked"} | DEFER | VALID_ROTATION_STATUSES)
                or type(entry["attempts"]) is not int
                or not 0 <= entry["attempts"] < 10**9
                or (entry["rotation_checkpoint"] is not None and
                    not isinstance(entry["rotation_checkpoint"], dict))):
            return False
    try:
        encoded = json.dumps(state, ensure_ascii=False, allow_nan=False)
    except (ValueError, TypeError, UnicodeError):
        return False
    return len(encoded.encode("utf-8")) <= MAX_STATE_BYTES


def _result(status, state=None):
    return {
        "schema": SCHEMA, "status": status,
        "private_state": state, "private_reviews": [],
        "events_considered_this_cycle": 0,
        "category_proposed_considered": 0,
        "unclassified_considered": 0,
        "held_for_future_research": 0,
        "completed_discovery_pass_this_cycle": 0,
        "full_passes_completed": (
            state.get("full_passes_completed", 0)
            if isinstance(state, dict) else 0),
        "source_rights_reviewed": False,
        "organizer_ownership_verified": False,
        "authoritative_deduplication_complete": False,
        "publication_ready": False,
        "publisher_connected": False,
        "public_writes": 0,
    }


def rotate_private_national_segment(
        report, today, public_read_key, previous_state=None, *,
        event_budget=MAX_EVENTS_PER_STEP,
        rotator=rotate_private_open_world_lead, rotator_options=None):
    """Rotate even unclassified OA findings; checkpoint every event fairly.

    A hold does not starve later events: advance segment position, and retry
    held items in the NEXT pass if explicitly invoked again the same day.
    Completed research is not repeated within that day.
    """
    items = _segment_items(report, today)
    digest = _fingerprint(report)
    if (items is None or digest is None
            or type(event_budget) is not int
            or not 1 <= event_budget <= MAX_EVENTS_PER_STEP
            or not _valid_public_read_key(public_read_key)
            or not callable(rotator)
            or rotator_options is not None
            and (not isinstance(rotator_options, dict)
                 or any(key not in (
                     "pages_per_cycle", "sources_per_cycle",
                     "directory_reader", "html_reader",
                     "oa_agenda_reader", "oa_event_reader", "location_proof")
                     for key in rotator_options))):
        return _result("invalid_private_campaign_segment")
    state = (_initial(items, digest, today) if previous_state is None
             else deepcopy(previous_state))
    if not _state_ok(state, items, digest, today):
        return _result("stale_or_tampered_segment_cursor")
    out = _result("national_segment_research_in_progress", state)
    if not items:
        out["status"] = "national_segment_no_event_leads_this_pass"
        return out
    pos = state["next_index"]
    processed = 0
    options = rotator_options or {}
    while processed < event_budget and pos < len(items):
        uid, role, lead = items[pos]
        entry = state["items"][pos]
        pos += 1
        processed += 1
        out["events_considered_this_cycle"] += 1
        out[("category_proposed_considered" if role == "category_proposed"
             else "unclassified_considered")] += 1
        if entry["status"] == DONE:
            # Still count this position for deterministic fair traversal.
            continue
        if not lead.get("explicit_source_session_intervals"):
            status = "missing_exact_sessions_for_research"
            research = None
        elif not isinstance(lead.get("city_unverified"), str) or not (
                lead["city_unverified"].strip()):
            status = "missing_municipality_for_research"
            research = None
        elif not _safe_research_lead(lead, today):
            status = "upstream_segment_candidate_untrusted"
            research = None
        else:
            try:
                research = rotator(
                    lead, public_read_key, today,
                    previous_checkpoint=entry["rotation_checkpoint"],
                    **options)
            except (OSError, ValueError, TypeError, KeyError,
                    TimeoutError, UnicodeError):
                research = None
            status = (research.get("status")
                      if isinstance(research, dict) else
                      "live_source_bootstrap_not_confirmed")
            if (status not in VALID_ROTATION_STATUSES
                    or not isinstance(research, dict)
                    or research.get("schema") != ROTATION_SCHEMA
                    or any(research.get(k) is not False for k in (
                        "organizer_identity_verified",
                        "authoritative_duplicate_check",
                        "source_rights_reviewed",
                        "publisher_connected", "publication_ready"))
                    or research.get("public_writes") != 0):
                research = None
                status = "upstream_segment_candidate_untrusted"
        entry["status"] = status
        entry["attempts"] += 1
        if research is not None:
            new_state = research.get("private_checkpoint")
            if isinstance(new_state, dict):
                entry["rotation_checkpoint"] = new_state
            # There is never a user-facing approval, only a private
            # per-event diagnostic to store outside the public repository.
            out["private_reviews"].append({
                "event_uid": uid, "role": role, "status": status,
                "research": research,
            })
        if status != DONE:
            out["held_for_future_research"] += 1
        else:
            out["completed_discovery_pass_this_cycle"] += 1
    state["next_index"] = pos
    if pos == len(items):
        state["next_index"] = 0
        state["full_passes_completed"] += 1
    if not _state_ok(state, items, digest, today):
        return _result("private_segment_state_capacity_requires_partition",
                       previous_state)
    out["private_state"] = state
    out["full_passes_completed"] = state["full_passes_completed"]
    if state["full_passes_completed"] and all(
            e["status"] == DONE for e in state["items"]):
        out["status"] = "national_segment_full_discovery_completed_today"
    return out


def public_redacted_national_segment_summary(result):
    """Aggregate only: never expose national event URLs, city, titles or times."""
    statuses = {
        "invalid_private_campaign_segment",
        "stale_or_tampered_segment_cursor",
        "national_segment_research_in_progress",
        "national_segment_full_discovery_completed_today",
        "national_segment_no_event_leads_this_pass",
        "private_segment_state_capacity_requires_partition",
    }
    if (not isinstance(result, dict)
            or result.get("schema") != SCHEMA
            or result.get("status") not in statuses
            or any(result.get(k) is not False for k in (
                "source_rights_reviewed", "organizer_ownership_verified",
                "authoritative_deduplication_complete",
                "publication_ready", "publisher_connected"))
            or result.get("public_writes") != 0
            or any(type(result.get(k)) is not int
                   or not 0 <= result[k] <= MAX_SEGMENT_EVENTS
                   for k in ("events_considered_this_cycle",
                             "category_proposed_considered",
                             "unclassified_considered",
                             "held_for_future_research",
                             "completed_discovery_pass_this_cycle"))):
        raise ValueError("invalid_private_national_segment_report")
    return {
        "schema": SCHEMA + ".aggregate", "status": result["status"],
        "events_considered": result["events_considered_this_cycle"],
        "recognized": result["category_proposed_considered"],
        "unclassified": result["unclassified_considered"],
        "held_for_research": result["held_for_future_research"],
        "completed_discovery_pass":
            result["completed_discovery_pass_this_cycle"],
        "publication_ready": False,
        "publisher_connected": False,
        "public_writes": 0,
    }
