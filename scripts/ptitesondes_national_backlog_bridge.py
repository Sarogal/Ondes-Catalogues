#!/usr/bin/env python3
"""Safely feed freshly rechecked national research leads into PRIVATE intake.

This is NOT an admission or publication path. Every event is freshly re-read
from OpenAgenda; the existing preflight, source, location, audience, duplicate
and public merge checks remain mandatory. No web/source allowlist is added.
The input observation is private and may come from a preceding scan day.
"""
import argparse
from datetime import date
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import tempfile

from proof import norm
from ptitesondes_openagenda_public_agenda_index import SCHEMA as INDEX_SCHEMA
from ptitesondes_openagenda_national_event_research import MAX_INDEX_BYTES
from ptitesondes_private_national_qualification_handoff import (
    handoff, verified_report, validate_private_handoff_chunk, MAX_REPORT_BYTES,
)
from ptitesondes_openagenda_v2_direct_evidence import _valid_public_read_key

SCHEMA = "ptitesondes.private_national_backlog_bridge.v1"
REPORT_RE = re.compile(r"index-(20\d\d-\d\d-\d\d)-[a-zA-Z0-9_-]{1,70}\.json\Z")
SEGMENT_RE = re.compile(r"agenda-\d{4}-segment-\d{4}\.json\Z")
MAX_EVENTS_PER_RUN = 8
MAX_BACKLOG = 4000
MAX_INDEX_REPORTS = 100
MAX_SEGMENTS = 10000


def _read(path, maximum):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > maximum:
        raise ValueError("invalid_private_bridge_input")
    raw = path.read_bytes()
    if len(raw) > maximum:
        raise ValueError("oversized_private_bridge_input")
    return json.loads(raw), raw


def _atomic_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError("untrusted_bridge_output_symlink")
    fd, name = tempfile.mkstemp(prefix=".national-bridge-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(obj, out, ensure_ascii=False, indent=2)
            out.write("\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _inventory(root):
    """Recreate the exact per-agenda index digest used by the saved campaign."""
    reports = root / "index" / "reports"
    if not reports.is_dir() or reports.is_symlink():
        return []
    index_files = sorted(reports.glob("index-*.json"))
    if len(index_files) > MAX_INDEX_REPORTS:
        raise ValueError("too_many_private_index_reports")
    todo = []
    segment_count = 0
    for index_path in index_files:
        match = REPORT_RE.fullmatch(index_path.name)
        if not match:
            raise ValueError("untrusted_private_index_filename")
        scan_day = date.fromisoformat(match.group(1))
        doc, raw = _read(index_path, MAX_INDEX_BYTES)
        if (not isinstance(doc, dict) or doc.get("schema") != INDEX_SCHEMA
                or doc.get("publication_ready") is not False
                or doc.get("public_writes") != 0
                or not isinstance(doc.get("new_agenda_candidates"), list)):
            raise ValueError("untrusted_private_index_document")
        campaign = root / "campaigns" / sha256(raw).hexdigest()[:24]
        if not campaign.is_dir() or campaign.is_symlink():
            continue
        for i, _ in enumerate(doc["new_agenda_candidates"]):
            source = campaign / f"agenda-{i:04d}"
            if not source.is_dir() or source.is_symlink():
                continue
            single = dict(doc, new_agenda_candidates=[doc["new_agenda_candidates"][i]])
            digest = sha256(json.dumps(
                single, sort_keys=True, ensure_ascii=False,
                separators=(",", ":")).encode("utf-8")).hexdigest()
            for segment_path in sorted(source.glob("agenda-*-segment-*.json")):
                segment_count += 1
                if segment_count > MAX_SEGMENTS or not SEGMENT_RE.fullmatch(segment_path.name):
                    raise ValueError("untrusted_private_segment_count_or_name")
                segment, _ = _read(segment_path, MAX_REPORT_BYTES)
                verified_report(single, digest, segment, scan_day)
                for offset, event in enumerate(segment["event_leads"]):
                    if not isinstance(event, dict) or type(event.get("event_uid")) is not int:
                        raise ValueError("untrusted_private_event_reference")
                    todo.append((single, digest, segment, scan_day, offset))
    return todo


def _identity(lead):
    return (str(lead.get("external_id")), lead.get("date_start"))


def bridge(root, backlog, today, key, *, cursor=None, limit=MAX_EVENTS_PER_RUN,
           operator=handoff):
    if (type(today) is not date or not _valid_public_read_key(key)
            or not isinstance(backlog, list) or len(backlog) > MAX_BACKLOG
            or type(limit) is not int or not 1 <= limit <= MAX_EVENTS_PER_RUN
            or not callable(operator)):
        raise ValueError("invalid_bridge_arguments")
    inventory = _inventory(Path(root))
    # Inventory fingerprint tracks new reports, segments and event order.
    fingerprint = sha256(json.dumps(
        [(scan_day.isoformat(), digest, seg["agenda_uid"], ev["event_uid"])
         for doc, digest, seg, scan_day, offset in inventory
         for ev in [seg["event_leads"][offset]]],
        separators=(",", ":")).encode("utf-8")).hexdigest()
    cursor = cursor if isinstance(cursor, dict) else {}
    if cursor and (cursor.get("schema") != SCHEMA
                   or type(cursor.get("next_index")) is not int
                   or cursor["next_index"] < 0
                   or not isinstance(cursor.get("inventory_sha256"), str)):
        raise ValueError("invalid_private_bridge_cursor")
    start = (cursor.get("next_index", 0) % len(inventory)
             if inventory and cursor.get("inventory_sha256") == fingerprint
             else 0)
    result = list(backlog)
    known = {}
    for row in result:
        if isinstance(row, dict) and row.get("collector") in (
                "openagenda-v2", "opendatasoft-index"):
            ident = _identity(row)
            known.setdefault(ident, row)
    examined = accepted_as_leads = duplicates = holds = 0
    for step in range(min(limit, len(inventory))):
        doc, digest, segment, scan_day, offset = inventory[
            (start + step) % len(inventory)]
        source = segment["event_leads"][offset]
        uid = str(source["event_uid"])
        future_days = [s for s in source["explicit_source_session_days"]
                       if s >= today.isoformat()]
        if future_days and all((uid, day) in known for day in future_days):
            duplicates += 1
            examined += 1
            continue
        outcome = operator(
            doc, digest, segment, today, key,
            offset=offset, max_fetch=1, source_scan_day=scan_day)
        validate_private_handoff_chunk(outcome, segment, offset)
        examined += 1
        for row in outcome["backlog_leads"]:
            ident = _identity(row)
            if row["date_start"] < today.isoformat():
                holds += 1
                continue
            previous = known.get(ident)
            if previous is not None:
                if any(norm(previous.get(k, "")) != norm(row.get(k, ""))
                       for k in ("title", "city", "venue")):
                    holds += 1  # conflict: never silently replace old lead
                else:
                    duplicates += 1
                continue
            if len(result) >= MAX_BACKLOG:
                raise ValueError("private_backlog_full")
            known[ident] = row
            result.append(row)
            accepted_as_leads += 1
        holds += len(outcome["research_holds"])
    next_index = (start + examined) % len(inventory) if inventory else 0
    state = {"schema": SCHEMA, "inventory_sha256": fingerprint,
             "next_index": next_index}
    summary = {"mode": "private_leads_not_approved",
               "events_rechecked": examined, "new_unverified_leads": accepted_as_leads,
               "existing_leads_skipped": duplicates, "research_holds": holds,
               "total_private_leads": len(result), "public_writes": 0,
               "publication_ready": False}
    return result, state, summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--private-observation-root", required=True, type=Path)
    ap.add_argument("--backlog-file", required=True, type=Path)
    ap.add_argument("--output-file", required=True, type=Path)
    ap.add_argument("--cursor-file", required=True, type=Path)
    ap.add_argument("--day", required=True, type=date.fromisoformat)
    ap.add_argument("--execute-live", action="store_true")
    args = ap.parse_args()
    if (len({p.resolve() for p in (
            args.backlog_file, args.output_file, args.cursor_file)}) != 3
            or args.output_file.is_symlink() or args.cursor_file.is_symlink()):
        raise ValueError("bridge_paths_not_isolated")
    if not args.execute_live:
        print(json.dumps({"mode": "dry_run_no_network_or_writes", "public_writes": 0}))
        return
    backlog, _ = _read(args.backlog_file, 2_000_000)
    cursor = (_read(args.cursor_file, 1024)[0]
              if args.cursor_file.exists() else None)
    merged, state, summary = bridge(
        args.private_observation_root, backlog, args.day,
        os.environ.get("OPENAGENDA_READ_KEY", ""), cursor=cursor)
    _atomic_json(args.output_file, merged)
    _atomic_json(args.cursor_file, state)
    # Never log event identities, URLs or titles on public runners.
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
