#!/usr/bin/env python3
"""Resume all new OpenAgenda campaign segments into PRIVATE research handoffs.

No cron, publisher, GitHub or private-backlog writer. Discover segment files
under a private directory, page up to eight 12-event handoffs per invocation,
and checkpoint exact progress. Live API calls require --execute-live.
"""
import argparse
from datetime import date
from hashlib import sha256
import json
import os
from pathlib import Path
import re

from ptitesondes_private_national_event_campaign import (
    _lock, _state_path as _unused_campaign_state_path,
)
from ptitesondes_openagenda_national_event_research import (
    MAX_INDEX_BYTES, _private_directory, _private_input, _write_new,
    _write_state,
)
from ptitesondes_private_national_qualification_handoff import (
    handoff, verified_report, MAX_REPORT_BYTES,
)
from ptitesondes_openagenda_v2_direct_evidence import _valid_public_read_key

SCHEMA = "ptitesondes.private_national_handoff_rotation.v1"
STATE_SCHEMA = "ptitesondes.private_national_handoff_rotation_cursor.v1"
MAX_STEPS = 8
MAX_SEGMENTS = 8192
SEGMENT = re.compile(r"agenda-(\d{4})-segment-(\d{4})\.json\Z")
STATE_NAME = "national-handoff-rotation-checkpoint.json"
LOCK_NAME = ".national-handoff-rotation.lock"


def segment_files(folder):
    _private_directory(folder)
    files = sorted(folder.glob("agenda-*-segment-*.json"))
    if len(files) > MAX_SEGMENTS:
        raise ValueError("handoff_segment_count_exceeded")
    previous = None
    for path in files:
        match = SEGMENT.fullmatch(path.name)
        if match is None or path.is_symlink():
            raise ValueError("invalid_private_segment_file")
        agenda, seq = (int(match.group(1)), int(match.group(2)))
        if previous is None:
            if (agenda, seq) != (0, 0):
                raise ValueError("noncontiguous_private_segment_files")
        elif not ((agenda == previous[0] and seq == previous[1] + 1)
                  or (agenda == previous[0] + 1 and seq == 0)):
            raise ValueError("noncontiguous_private_segment_files")
        previous = (agenda, seq)
    return files


def _state(output_dir, index_digest, today, segment_total):
    _private_directory(output_dir)
    path = output_dir / STATE_NAME
    if path.is_symlink():
        raise ValueError("invalid_private_rotation_checkpoint")
    if not path.exists():
        return {"schema": STATE_SCHEMA, "source_sha256": index_digest,
                "scan_day": today.isoformat(), "next_segment_index": 0,
                "next_offset": 0}
    state = json.loads(_private_input(path, 3000))
    if (not isinstance(state, dict) or set(state) != {
            "schema", "source_sha256", "scan_day",
            "next_segment_index", "next_offset"}
            or state["schema"] != STATE_SCHEMA
            or state["source_sha256"] != index_digest
            or state["scan_day"] != today.isoformat()
            or type(state["next_segment_index"]) is not int
            or not 0 <= state["next_segment_index"] <= segment_total
            or type(state["next_offset"]) is not int
            or not 0 <= state["next_offset"] <= 60
            or (state["next_segment_index"] == segment_total
                and state["next_offset"] != 0)):
        raise ValueError("invalid_private_rotation_checkpoint")
    return state


def _safe_recovered(output, expected, start, segment_count):
    if (not isinstance(output, dict)
            or output.get("schema") !=
            "ptitesondes.private_national_oa_intake_handoff.v1"
            or output.get("mode") != "private_intake_research_only"
            or output.get("rotation_meta") != expected
            or output.get("safe_to_publish") is not False
            or output.get("publication_ready") is not False
            or output.get("publisher_connected") is not False
            or output.get("public_writes") != 0
            or type(output.get("events_examined")) is not int
            or not 0 <= output["events_examined"] <= 12
            or type(output.get("next_offset")) is not int
            or output["next_offset"] != start + output["events_examined"]
            or not 0 <= output["next_offset"] <= segment_count
            or output.get("finished_segment")
            is not (output["next_offset"] == segment_count)
            or not isinstance(output.get("backlog_leads"), list)
            or not isinstance(output.get("research_holds"), list)):
        raise ValueError("invalid_recovered_private_handoff")


def run_rotation(index_doc, index_digest, today, input_dir, output_dir,
                 *, public_key, steps=MAX_STEPS,
                 operator=handoff):
    """Run bounded self-resuming handoffs; never modify existing backlog."""
    if (type(today) is not date or not isinstance(index_digest, str)
            or not re.fullmatch(r"[a-f0-9]{64}", index_digest)
            or not _valid_public_read_key(public_key)
            or type(steps) is not int or not 1 <= steps <= MAX_STEPS
            or not callable(operator)):
        raise ValueError("invalid_rotation_arguments")
    files = segment_files(input_dir)
    _private_directory(output_dir)
    lock = output_dir / LOCK_NAME
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    examined = recovered = done = 0
    try:
        # Resolve cursor only while holding the exclusive output lock.
        state = _state(output_dir, index_digest, today, len(files))
        for _ in range(steps):
            ix = state["next_segment_index"]
            if ix == len(files):
                break
            file = files[ix]
            raw = _private_input(file, MAX_REPORT_BYTES)
            segment = json.loads(raw)
            verified_report(index_doc, index_digest, segment, today)
            total = len(segment["event_leads"])
            start = state["next_offset"]
            if start > total:
                raise ValueError("rotation_offset_exceeds_event_count")
            report_name = f"handoff-{ix:04d}-{start:03d}.json"
            destination = output_dir / report_name
            expected = {
                "source_sha256": index_digest, "scan_day": today.isoformat(),
                "segment_filename": file.name,
                "segment_sha256": sha256(raw).hexdigest(),
                "start_offset": start,
            }
            if destination.is_symlink():
                raise ValueError("untrusted_existing_private_handoff")
            if destination.exists():
                saved = json.loads(_private_input(destination, MAX_REPORT_BYTES))
                _safe_recovered(saved, expected, start, total)
                outcome = saved
                recovered += 1
            else:
                outcome = operator(index_doc, index_digest, segment, today,
                                   public_key, offset=start)
                if not isinstance(outcome, dict):
                    raise ValueError("invalid_handoff_operator_result")
                outcome = {**outcome, "rotation_meta": expected}
                _safe_recovered(outcome, expected, start, total)
                _write_new(destination, outcome)
                examined += outcome["events_examined"]
            end = outcome["next_offset"]
            if end == total:
                state["next_segment_index"] += 1
                state["next_offset"] = 0
                done += 1
            elif end > start:
                state["next_offset"] = end
            else:
                raise ValueError("rotation_no_forward_progress")
            _write_state(output_dir / STATE_NAME, state)
    finally:
        lock.unlink()
    return {"schema": SCHEMA, "mode": "private_readonly_rotation",
            "events_directly_rechecked": examined,
            "recovered_chunks": recovered,
            "segments_completed_this_run": done,
            "next_segment_index": state["next_segment_index"],
            "next_offset": state["next_offset"],
            "segments_available": len(files),
            "currently_caught_up": state["next_segment_index"] == len(files),
            "publication_ready": False, "public_writes": 0}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--private-agenda-index-report", required=True, type=Path)
    parser.add_argument("--private-campaign-segments", required=True, type=Path)
    parser.add_argument("--private-output-dir", required=True, type=Path)
    parser.add_argument("--day", required=True, type=date.fromisoformat)
    parser.add_argument("--max-steps", type=int, default=MAX_STEPS)
    parser.add_argument("--execute-live", action="store_true")
    args = parser.parse_args()
    paths = (args.private_agenda_index_report.resolve(),
             args.private_campaign_segments.resolve(),
             args.private_output_dir.resolve())
    if len(set(paths)) != 3:
        raise ValueError("private_rotation_paths_must_be_distinct")
    raw = _private_input(args.private_agenda_index_report, MAX_INDEX_BYTES)
    index_doc = json.loads(raw)
    digest = sha256(raw).hexdigest()
    files = segment_files(args.private_campaign_segments)
    # Validate existing checkpoint even on a dry-run, without network/writes.
    state = _state(args.private_output_dir, digest, args.day, len(files))
    if not args.execute_live:
        print(json.dumps({
            "mode": "dry_run_no_network", "segment_files": len(files),
            "next_segment_index": state["next_segment_index"],
            "next_offset": state["next_offset"], "public_writes": 0,
        }))
        return
    outcome = run_rotation(
        index_doc, digest, args.day, args.private_campaign_segments,
        args.private_output_dir,
        public_key=os.environ.get("OPENAGENDA_READ_KEY", ""),
        steps=args.max_steps,
    )
    print(json.dumps(outcome))


if __name__ == "__main__":
    main()
