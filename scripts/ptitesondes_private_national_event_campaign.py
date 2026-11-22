#!/usr/bin/env python3
"""Bounded private rotation over *all* newly discovered OA agenda candidates.

Consumes the private national agenda index report, explores up to 8 segments
per invocation and persists an index/agenda/event-cursor checkpoint. This
module cannot publish, change configured sources or schedule a GitHub Action.
The caller must arrange private execution and source updates separately.
"""
import argparse
from datetime import date, datetime, timedelta
from hashlib import sha256
import json
import os
from pathlib import Path

from ptitesondes_openagenda_national_event_research import (
    MAX_INDEX_BYTES, MAX_TIMINGS,
    select_index_candidate, scan_agenda, valid_after,
    _private_directory, _private_input, _write_new, _write_state,
)
from ptitesondes_openagenda_v2_direct_evidence import _valid_public_read_key

SCHEMA = "ptitesondes.private_national_oa_event_campaign.v1"
STATE_SCHEMA = "ptitesondes.private_national_oa_event_campaign_cursor.v1"
MAX_STEPS = 8
MAX_INDEX_AGENDAS = 160
MAX_SEGMENT_BYTES = 8_000_000  # supports hundreds of exact session hints per event
STATE_FILENAME = "national-event-checkpoint.json"
LOCK_FILENAME = ".national-event-campaign.lock"


def _state_path(output_dir):
    return output_dir / STATE_FILENAME


def load_checkpoint(output_dir, digest, day, total):
    """Fail closed on changed source, day, pagination or invalid prior run."""
    _private_directory(output_dir)
    path = _state_path(output_dir)
    if path.is_symlink():
        raise ValueError("private_campaign_state_symlink")
    if not path.exists():
        return {"schema": STATE_SCHEMA, "source_sha256": digest,
                "scan_day": day.isoformat(), "total_agendas": total,
                "next_agenda_index": 0, "segment": 0, "event_after": None}
    raw = _private_input(path, 3000)
    state = json.loads(raw)
    if (not isinstance(state, dict)
            or set(state) != {"schema", "source_sha256", "scan_day",
                              "total_agendas", "next_agenda_index",
                              "segment", "event_after"}
            or state["schema"] != STATE_SCHEMA
            or state["source_sha256"] != digest
            or state["scan_day"] != day.isoformat()
            or type(state["total_agendas"]) is not int
            or state["total_agendas"] != total
            or type(state["next_agenda_index"]) is not int
            or not 0 <= state["next_agenda_index"] <= total
            or type(state["segment"]) is not int
            or not 0 <= state["segment"] <= 10000
            or (state["event_after"] is not None
                and not valid_after(state["event_after"]))
            or ((state["segment"] == 0) != (state["event_after"] is None))
            or (state["next_agenda_index"] == total
                and (state["event_after"] is not None
                     or state["segment"] != 0))):
        raise ValueError("private_campaign_cursor_or_source_mismatch")
    return state


def plan_campaign(index_doc, digest, day, output_dir, steps=MAX_STEPS):
    if (type(day) is not date
            or not isinstance(digest, str) or len(digest) != 64
            or type(steps) is not int or not 1 <= steps <= MAX_STEPS):
        raise ValueError("invalid_campaign_plan_arguments")
    if (not isinstance(index_doc, dict)
            or index_doc.get("schema") !=
            "ptitesondes.private_national_oa_index.v1"
            or index_doc.get("mode") !=
            "private_index_readonly_discovery_not_admission"
            or index_doc.get("publication_ready") is not False
            or index_doc.get("public_writes") != 0
            or not isinstance(index_doc.get("new_agenda_candidates"), list)
            or not 0 <= len(index_doc["new_agenda_candidates"]) <= MAX_INDEX_AGENDAS):
        raise ValueError("invalid_campaign_index_size")
    # A valid page may contain ZERO previously unknown agendas. That is
    # a successful empty batch, not a deployment failure or missing data.
    if index_doc["new_agenda_candidates"]:
        select_index_candidate(index_doc, 0)
    state = load_checkpoint(output_dir, digest, day,
                            len(index_doc["new_agenda_candidates"]))
    return {"state": state, "steps": steps,
            "total": len(index_doc["new_agenda_candidates"]),
            "index_doc": index_doc, "digest": digest,
            "day": day, "output_dir": output_dir}


def _lock(output_dir):
    _private_directory(output_dir)
    path = output_dir / LOCK_FILENAME
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    return path


def _segment_meta(plan, state):
    return {
        "source_sha256": plan["digest"],
        "scan_day": plan["day"].isoformat(),
        "agenda_index": state["next_agenda_index"],
        "segment": state["segment"],
        "start_cursor": state["event_after"],
    }


def _valid_session_hints(item):
    """Validate private API timing hints; their shape never grants publication."""
    if "explicit_source_session_intervals" not in item:
        return True  # Backwards-compatible, pre-session historical reports.
    intervals = item["explicit_source_session_intervals"]
    if type(intervals) is not list or len(intervals) > MAX_TIMINGS:
        return False
    seen = set()
    for slot in intervals:
        if (type(slot) is not dict or set(slot) != {"begin", "end"}
                or any(type(slot[key]) is not str
                       or not 1 <= len(slot[key]) <= 40
                       for key in ("begin", "end"))):
            return False
        key = (slot["begin"], slot["end"])
        if key in seen:
            return False
        seen.add(key)
        try:
            begin, finish = (datetime.fromisoformat(key[0]),
                             datetime.fromisoformat(key[1]))
        except ValueError:
            return False
        if (begin.tzinfo is None or finish.tzinfo is None
                or begin.utcoffset() is None or finish.utcoffset() is None
                or not begin < finish
                or finish - begin > timedelta(days=2)):
            return False
    return True


def _validate_segment(report, agenda, expected_meta):
    counts = report.get("counts") if isinstance(report, dict) else None
    leads = report.get("event_leads") if isinstance(report, dict) else None
    if (not isinstance(counts, dict)
            or type(counts.get("pages_read")) is not int
            or not 1 <= counts["pages_read"] <= 3
            or type(counts.get("public_event_uids_seen")) is not int
            or not 0 <= counts["public_event_uids_seen"] <= 60
            or not isinstance(leads, list)
            or len(leads) > counts["public_event_uids_seen"]
            or any(not isinstance(lead, dict)
                   or lead.get("publication_ready") is not False
                   or lead.get("public_writes") != 0
                   or not _valid_session_hints(lead)
                   for lead in leads)):
        raise ValueError("invalid_private_agenda_segment")
    if (not isinstance(report, dict)
            or report.get("schema") !=
            "ptitesondes.private_oa_agenda_event_exploration.v1"
            or report.get("mode") != "private_research_event_leads_only"
            or report.get("no_publisher_bridge") is not True
            or report.get("agenda_uid") != agenda["agenda_uid"]
            or report.get("agenda_slug") != agenda["agenda_slug"]
            or report.get("campaign_meta") != expected_meta
            or report.get("publication_ready") is not False
            or report.get("public_writes") != 0
            or not isinstance(report.get("event_leads"), list)
            or len(report["event_leads"]) > 60
            or type(report.get("agenda_scan_complete")) is not bool
            or (report.get("next_cursor") is not None
                and not valid_after(report["next_cursor"]))
            or (report["agenda_scan_complete"]
                != (report["next_cursor"] is None))
            or (not report["agenda_scan_complete"]
                and report["next_cursor"] == expected_meta["start_cursor"])):
        raise ValueError("invalid_private_agenda_segment")


    # Editorial discovery must remain open, but UNKNOWN is never trusted.
    # Optional on older reports, with strict caps and zero approval authority.
    review = report.get("unclassified_editorial_research_only", [])
    if (not isinstance(review, list)
            or len(review) > counts["public_event_uids_seen"]
            or len(review) > 60):
        raise ValueError("unsafe_unclassified_editorial_research")
    seen_research = set()
    admitted = {x.get("event_uid") for x in leads
                if isinstance(x, dict)}
    for item in review:
        if (not isinstance(item, dict)
                or type(item.get("event_uid")) is not int
                or not 0 < item["event_uid"] < 10**12
                or item["event_uid"] in seen_research
                or item["event_uid"] in admitted
                or not _valid_session_hints(item)
                or item.get("agenda_uid") != agenda["agenda_uid"]
                or item.get("agenda_slug") != agenda["agenda_slug"]
                or not isinstance(item.get("title"), str)
                or not 0 < len(item["title"]) <= 300
                or item.get("editorial_category_proposal") is not None
                or item.get("review_state") !=
                "unknown_activity_requires_official_editorial_evidence"
                or any(item.get(k) is not False for k in (
                    "source_organizer_independently_verified",
                    "rights_reviewed", "venue_verified",
                    "publisher_connected", "publication_ready"))
                or type(item.get("public_writes")) is not int
                or item["public_writes"] != 0):
            raise ValueError("unsafe_unclassified_editorial_research")
        seen_research.add(item["event_uid"])


def _advance(state, report):
    updated = dict(state)
    if report["agenda_scan_complete"]:
        updated["next_agenda_index"] += 1
        updated["segment"] = 0
        updated["event_after"] = None
    else:
        if updated["segment"] >= 10000:
            raise ValueError("private_agenda_segment_limit")
        updated["segment"] += 1
        updated["event_after"] = report["next_cursor"]
    return updated


def run_campaign(plan, *, public_key, explorer=scan_agenda):
    """Bounded private campaign with safe replay after checkpoint interruptions.

    Every report carries the exact input digest, agenda index, segment number,
    and *starting* cursor. A finished report left by an interrupted checkpoint
    update can be recovered without repeating network work; any mismatch or
    tampering fails closed, never silently publishing or skipping a session.
    """
    if not _valid_public_read_key(public_key) or not callable(explorer):
        raise ValueError("private_oa_public_read_key_required")
    output_dir = plan["output_dir"]
    marker = _lock(output_dir)
    attempted, freshly_scanned, recovered = 0, 0, 0
    try:
        # Plans can be prepared before another process finishes. Always read
        # the durable checkpoint *after* obtaining the exclusive lock;
        # otherwise an old plan could replay segments and roll back progress.
        state = load_checkpoint(output_dir, plan["digest"], plan["day"],
                                plan["total"])
        while (attempted < plan["steps"]
               and state["next_agenda_index"] < plan["total"]):
            idx, segment = state["next_agenda_index"], state["segment"]
            agenda = select_index_candidate(plan["index_doc"], idx)
            path = output_dir / f"agenda-{idx:04d}-segment-{segment:04d}.json"
            expected = _segment_meta(plan, state)
            if path.is_symlink():
                raise ValueError("existing_private_segment_untrusted")
            if path.exists():
                # Recovery is permitted only for the EXACT fully validated
                # segment that starts from the current checkpoint state.
                try:
                    stored = json.loads(_private_input(path, MAX_SEGMENT_BYTES))
                    _validate_segment(stored, agenda, expected)
                except (OSError, ValueError, TypeError):
                    raise ValueError("existing_private_segment_requires_recovery") from None
                state = _advance(state, stored)
                _write_state(_state_path(output_dir), state)
                recovered += 1
            else:
                report = explorer(
                    agenda, public_key, plan["day"], after=state["event_after"])
                if not isinstance(report, dict):
                    raise ValueError("invalid_private_agenda_segment")
                report = {**report, "campaign_meta": expected}
                _validate_segment(report, agenda, expected)
                # A crash-recovery replay must be able to read the full
                # private report; never write an unreadable oversized file.
                if len(json.dumps(report, ensure_ascii=False, indent=2).encode(
                        "utf-8")) + 1 > MAX_SEGMENT_BYTES:
                    raise ValueError("private_agenda_segment_too_large")
                next_state = _advance(state, report)
                _write_new(path, report)
                _write_state(_state_path(output_dir), next_state)
                state = next_state
                freshly_scanned += 1
            attempted += 1
    finally:
        marker.unlink()
    return {
        "schema": SCHEMA, "mode": "private_readonly_event_campaign",
        "segments_examined": freshly_scanned,
        "segments_recovered_from_private_report": recovered,
        "next_agenda_index": state["next_agenda_index"],
        "total_agendas": plan["total"],
        "finished_index_batch": state["next_agenda_index"] == plan["total"],
        "publication_ready": False, "public_writes": 0,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--private-agenda-index-report", required=True, type=Path)
    ap.add_argument("--private-output-dir", required=True, type=Path)
    ap.add_argument("--day", type=date.fromisoformat, required=True)
    ap.add_argument("--max-steps", type=int, default=MAX_STEPS)
    ap.add_argument("--execute-live", action="store_true")
    args = ap.parse_args()
    raw = _private_input(args.private_agenda_index_report, MAX_INDEX_BYTES)
    digest = sha256(raw).hexdigest()
    document = json.loads(raw)
    plan = plan_campaign(document, digest, args.day, args.private_output_dir,
                         steps=args.max_steps)
    if not args.execute_live:
        print(json.dumps({
            "mode": "dry_run_no_network",
            "remaining_agendas": plan["total"] -
            plan["state"]["next_agenda_index"],
            "next_agenda_index": plan["state"]["next_agenda_index"],
            "public_writes": 0,
        }))
        return
    result = run_campaign(
        plan, public_key=os.environ.get("OPENAGENDA_READ_KEY", ""))
    # No agenda UID, event UID, title, venue or source paths in stdout.
    print(json.dumps(result))


if __name__ == "__main__":
    main()
