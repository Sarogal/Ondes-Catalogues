#!/usr/bin/env python3
"""Bounded national OpenAgenda -> open-world source research on PRIVATE state.

Not an admission engine or publisher. Reuses existing SSRF-safe, independent
OA/DILA/municipal/source readers. Candidate lists never contain named allowed
agendas, venues, organizers, domains or cities. New sources remain untrusted.
The only public output is a numeric summary, never URLs, identity or snippets.
"""
import argparse
from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
import re

from ptitesondes_national_backlog_bridge import (
    _atomic_json, _inventory, _inventory_key, _read,
)
from ptitesondes_open_world_candidate_rotation import (
    rotate_private_open_world_lead, public_redacted_rotation_summary,
)
from ptitesondes_openagenda_v2_direct_evidence import _valid_public_read_key

SCHEMA = "ptitesondes.private_national_openworld_research_cycle.v1"
# Increase the daily national scan throughput while staying inside the
# 45-minute private runner. This is a bounded work budget, not a source list.
# Repeated cycles use the persisted opaque cursor to reach later candidates.
MAX_EVENTS_PER_CYCLE = 8
MAX_STORED_CHECKPOINTS = 10000
MAX_REPORT_BYTES = 1_500_000


def _future_original(entry, today):
    """Never synthesize a session; retain only exact observed future intervals."""
    lead = entry[2]["event_leads"][entry[4]]
    intervals = lead.get("explicit_source_session_intervals")
    if not isinstance(intervals, list):
        return None
    future = []
    for slot in intervals:
        if not isinstance(slot, dict):
            return None
        try:
            begin = datetime.fromisoformat(slot["begin"])
            end = datetime.fromisoformat(slot["end"])
        except (ValueError, TypeError, KeyError):
            return None
        if (begin.tzinfo is None or end.tzinfo is None
                or begin.utcoffset() is None or end.utcoffset() is None
                or not begin < end):
            return None
        if today <= begin.date() <= today + timedelta(days=184):
            future.append(slot)
    if not future:
        return None
    return dict(lead, explicit_source_session_intervals=future)


def _state(cursor, today):
    if cursor is None:
        return {"schema": SCHEMA, "scan_day": today.isoformat(),
                "last_completed_ref": None, "checkpoints": {}}
    if (type(cursor) is not dict or cursor.get("schema") != SCHEMA
            or not isinstance(cursor.get("scan_day"), str)
            or not isinstance(cursor.get("last_completed_ref"), (str, type(None)))
            or (cursor.get("last_completed_ref") is not None
                and re.fullmatch(r"[a-f0-9]{64}",
                                 cursor["last_completed_ref"]) is None)
            or type(cursor.get("checkpoints")) is not dict
            or len(cursor["checkpoints"]) > MAX_STORED_CHECKPOINTS
            or any(re.fullmatch(r"[a-f0-9]{64}", key) is None
                   or type(value) is not dict
                   for key, value in cursor["checkpoints"].items())):
        raise ValueError("invalid_private_research_cursor")
    # Daily retry history is ephemeral, never a permanent blacklist.
    if cursor["scan_day"] != today.isoformat():
        return {"schema": SCHEMA, "scan_day": today.isoformat(),
                "last_completed_ref": cursor["last_completed_ref"],
                "checkpoints": {}}
    return {"schema": SCHEMA, "scan_day": today.isoformat(),
            "last_completed_ref": cursor["last_completed_ref"],
            "checkpoints": dict(cursor["checkpoints"])}


def research_cycle(root, today, key, *, cursor=None,
                   max_events=MAX_EVENTS_PER_CYCLE,
                   inventory_reader=_inventory,
                   operator=rotate_private_open_world_lead):
    if (type(today) is not date or not _valid_public_read_key(key)
            or type(max_events) is not int
            or not 1 <= max_events <= MAX_EVENTS_PER_CYCLE
            or not callable(inventory_reader) or not callable(operator)):
        raise ValueError("invalid_private_research_cycle_request")
    state = _state(cursor, today)
    candidates = []
    for entry in inventory_reader(Path(root)):
        lead = _future_original(entry, today)
        if lead is None:
            continue
        ref = _inventory_key(entry)
        # Highest priority: explicit musical editorial proposals that still
        # have upcoming sessions, without excluding unknown activity research.
        beginnings = [x["begin"] for x in
                      lead["explicit_source_session_intervals"]]
        weight = 0 if lead.get("editorial_category_proposal") else 1
        candidates.append((weight, min(beginnings), ref, lead))
    candidates.sort(key=lambda x: (x[0], x[1], x[2]))
    if not candidates:
        summary = {"mode": "private_source_research_only",
                   "candidates_with_future_sessions": 0,
                   "events_examined": 0, "source_reviews": 0,
                   "exact_session_claims_unverified": 0,
                   "visible_session_claims_unverified": 0,
                   "publisher_connected": False,
                   "publication_ready": False, "public_writes": 0}
        return [], state, summary
    keys = [x[2] for x in candidates]
    if state["last_completed_ref"] in keys:
        first = (keys.index(state["last_completed_ref"]) + 1) % len(keys)
    else:
        first = 0
    reports = []
    for step in range(min(max_events, len(candidates))):
        _, _, ref, lead = candidates[(first + step) % len(candidates)]
        report = operator(
            lead, key, today,
            previous_checkpoint=state["checkpoints"].get(ref),
            pages_per_cycle=2, sources_per_cycle=1)
        # The generic verifier *must* report no final admission/publisher
        # rights. Never trust source- or caller-provided 'verified' flags.
        public_redacted_rotation_summary(report)
        checkpoint = report.get("private_checkpoint")
        if type(checkpoint) is not dict:
            raise ValueError("missing_private_research_checkpoint")
        state["checkpoints"][ref] = checkpoint
        if len(state["checkpoints"]) > MAX_STORED_CHECKPOINTS:
            raise ValueError("private_research_checkpoint_capacity")
        reports.append({"ref": ref, "day": today.isoformat(),
                        "review": report})
        state["last_completed_ref"] = ref
    summary = {
        "mode": "private_source_research_only",
        "candidates_with_future_sessions": len(candidates),
        "events_examined": len(reports),
        "source_reviews": sum(x["review"]["oa_urls_rechecked"] +
                              x["review"]["source_candidates_examined"]
                              for x in reports),
        "exact_session_claims_unverified": sum(
            x["review"]["oa_exact_session_claims_unverified"]
            for x in reports),
        "visible_session_claims_unverified": sum(
            x["review"]["oa_visible_exact_session_claims_unverified"]
            for x in reports),
        "publisher_connected": False, "publication_ready": False,
        "public_writes": 0,
    }
    return reports, state, summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--private-observation-root", required=True, type=Path)
    ap.add_argument("--private-research-root", required=True, type=Path)
    ap.add_argument("--day", type=date.fromisoformat, required=True)
    ap.add_argument("--max-events-per-cycle", type=int,
                    default=MAX_EVENTS_PER_CYCLE)
    ap.add_argument("--execute-live", action="store_true")
    args = ap.parse_args()
    # Explicit dry run has no network, private I/O or writes.
    if not args.execute_live:
        print(json.dumps({"mode": "dry_run_no_network_or_writes",
                          "publication_ready": False, "public_writes": 0}))
        return
    repo = Path(__file__).resolve().parents[1]
    if (args.private_research_root.resolve().is_relative_to(repo)
            or args.private_observation_root.resolve().is_relative_to(repo)
            or args.private_research_root.is_symlink()):
        raise ValueError("private_research_must_stay_outside_public_checkout")
    key = os.environ.get("OPENAGENDA_READ_KEY", "")
    root = args.private_research_root
    root.mkdir(parents=True, exist_ok=True)
    cursor_path = root / "cursor.json"
    previous = _read(cursor_path, 12_000_000)[0] if cursor_path.exists() else None
    reports, state, summary = research_cycle(
        args.private_observation_root, args.day, key, cursor=previous,
        max_events=args.max_events_per_cycle)
    day_dir = root / "reports" / args.day.isoformat()
    for report in reports:
        target = day_dir / (report["ref"] + ".json")
        if len(json.dumps(report, ensure_ascii=False).encode("utf-8")) > MAX_REPORT_BYTES:
            raise ValueError("oversized_private_research_result")
        _atomic_json(target, report)
    _atomic_json(cursor_path, state)
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
