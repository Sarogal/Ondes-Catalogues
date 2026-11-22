#!/usr/bin/env python3
"""Opt-in private runner for ALL OA national event campaign segment reports.

A secure, pre-existing private directory supplies the existing
`agenda-NNNN-segment-NNNN.json` files. The runner discovers ALL such files
by directory enumeration; no agenda IDs, venue names, website hosts, towns,
artist or category lists are configured. It writes atomic, 0600 private
state+report snapshots; no GitHub write, schedule, push, publisher or patch.

Defaults to DRY RUN (zero network, zero writes). Running live requires the
operator to supply --execute-live and a public OpenAgenda read key in an
environment variable. The CLI prints only aggregate counters. The eventual
GitHub Actions integration must be reviewed separately before activation.
"""
import argparse
from datetime import date
import json
import os
from pathlib import Path
import re
from hashlib import sha256
import tempfile

from ptitesondes_openagenda_national_event_research import _private_directory
from ptitesondes_openagenda_v2_direct_evidence import _valid_public_read_key
from ptitesondes_national_segment_rotation_bridge import (
    MAX_REPORT_BYTES, MAX_EVENTS_PER_STEP,
    _segment_items, rotate_private_national_segment,
    public_redacted_national_segment_summary,
)

SCHEMA = "ptitesondes.private_national_runner_snapshot.v1"
SELECT_SCHEMA = "ptitesondes.private_national_runner_file_cursor.v1"
MAX_STORE_BYTES = 32_000_000
MAX_INDEX_BYTES = 2000
MAX_SEGMENTS_PER_RUN = 3
REPORT_NAME = re.compile(r"agenda-[0-9]{1,8}-segment-[0-9]{1,8}\.json\Z")


def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, allow_nan=False,
                       separators=(",", ":"), sort_keys=True)
            + "\n").encode("utf-8")


def _safe_existing_file(path, max_bytes):
    _private_directory(path.parent)
    if (path.is_symlink() or not path.is_file()
            or not 0 < path.stat().st_size <= max_bytes):
        raise ValueError("invalid_private_runner_input")
    with path.open("rb") as stream:
        return stream.read(max_bytes + 1)


def _write_atomic_private(path, payload):
    """0600 fsync+replace in 0700 outside-checkout private workspace."""
    _private_directory(path.parent)
    if path.is_symlink() or len(payload) > MAX_STORE_BYTES:
        raise ValueError("unsafe_private_runner_state_path_or_size")
    fd, tmp = tempfile.mkstemp(prefix=".private-national-rotation-",
                                dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _acquire_lock(path):
    _private_directory(path.parent)
    if path.is_symlink():
        raise ValueError("private_runner_lock_symlink")
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    return path


def _state_path(state_dir, report_bytes, day):
    digest = sha256(report_bytes).hexdigest()
    return state_dir / (
        "national-segment-" + digest[:24] + "-" + day.isoformat()
        + ".json"), digest


def _read_snapshot(path, digest, day):
    if path.is_symlink():
        raise ValueError("private_snapshot_symlink")
    if not path.exists():
        return None
    raw = _safe_existing_file(path, MAX_STORE_BYTES)
    try:
        snapshot = json.loads(raw)
    except (UnicodeError, ValueError):
        raise ValueError("invalid_private_snapshot") from None
    if (not isinstance(snapshot, dict)
            or set(snapshot) != {"schema", "source_file_sha256", "scan_day",
                                 "serial", "bridge_state", "last_cycle"}
            or snapshot["schema"] != SCHEMA
            or snapshot["source_file_sha256"] != digest
            or snapshot["scan_day"] != day.isoformat()
            or type(snapshot["serial"]) is not int
            or not 1 <= snapshot["serial"] <= 10**9
            or not isinstance(snapshot["bridge_state"], dict)
            or not isinstance(snapshot["last_cycle"], dict)
            or snapshot["last_cycle"].get("publication_ready") is not False
            or snapshot["last_cycle"].get("publisher_connected") is not False
            or snapshot["last_cycle"].get("public_writes") != 0):
        raise ValueError("untrusted_private_snapshot")
    return snapshot


def run_segment_file(report_path, private_state_dir, day, *,
                     execute_live=False, key=None,
                     event_budget=MAX_EVENTS_PER_STEP,
                     rotator_options=None, rotator=None):
    """Advance ONE segment safely with a single atomic checkpoint/report.

    This is the direct seam between the existing OA campaign and new #604
    rotation. The snapshot stores every private evidence review from the last
    cycle, even if a crash occurs during another file's processing.
    """
    report_path = Path(report_path)
    private_state_dir = Path(private_state_dir)
    _private_directory(private_state_dir)
    raw = _safe_existing_file(report_path, MAX_REPORT_BYTES)
    if not raw or len(raw) > MAX_REPORT_BYTES:
        raise ValueError("invalid_private_campaign_report_size")
    try:
        report = json.loads(raw)
    except (ValueError, UnicodeError):
        raise ValueError("invalid_private_campaign_report_json") from None
    items = _segment_items(report, day)
    if items is None:
        raise ValueError("invalid_private_campaign_report_contract")
    state_path, digest = _state_path(private_state_dir, raw, day)
    if (state_path.resolve() == report_path.resolve()
            or private_state_dir.resolve() == report_path.parent.resolve()):
        raise ValueError("input_and_state_must_be_separate_private_dirs")
    if not execute_live:
        return {
            "status": "dry_run_no_network_or_writes",
            "campaign_candidates": len(items), "public_writes": 0,
        }
    if (not _valid_public_read_key(key)
            or type(event_budget) is not int
            or not 1 <= event_budget <= MAX_EVENTS_PER_STEP):
        raise ValueError("private_runner_read_key_or_budget_invalid")
    lock = _acquire_lock(state_path.with_suffix(".lock"))
    try:
        current = _read_snapshot(state_path, digest, day)
        previous = current["bridge_state"] if current is not None else None
        kwargs = {"event_budget": event_budget}
        if rotator_options is not None:
            kwargs["rotator_options"] = rotator_options
        if rotator is not None:
            kwargs["rotator"] = rotator
        out = rotate_private_national_segment(
            report, day, key, previous, **kwargs)
        if out["status"] not in (
                "national_segment_research_in_progress",
                "national_segment_full_discovery_completed_today",
                "national_segment_no_event_leads_this_pass"):
            raise ValueError("private_campaign_rotation_blocked")
        if not isinstance(out.get("private_state"), dict):
            raise ValueError("private_campaign_rotation_state_missing")
        summary = public_redacted_national_segment_summary(out)
        record = {
            "schema": SCHEMA, "source_file_sha256": digest,
            "scan_day": day.isoformat(),
            "serial": (1 if current is None else current["serial"] + 1),
            "bridge_state": out["private_state"],
            "last_cycle": out,
        }
        encoded = _json_bytes(record)
        if len(encoded) > MAX_STORE_BYTES:
            raise ValueError("private_snapshot_size_requires_partition")
        _write_atomic_private(state_path, encoded)
        return {**summary, "serial": record["serial"]}
    finally:
        lock.unlink()


def _candidate_reports(private_campaign_dir):
    _private_directory(private_campaign_dir)
    candidates = []
    # No source allowlist: only the output FILE-NAME contract of our own
    # earlier campaign. Do not follow symlink files or user-supplied URLs.
    for child in private_campaign_dir.iterdir():
        if REPORT_NAME.fullmatch(child.name):
            if child.is_symlink() or not child.is_file():
                raise ValueError("unsafe_private_campaign_segment_entry")
            candidates.append(child)
    return sorted(candidates, key=lambda f: f.name)


def _selection_path(state_dir, day):
    return state_dir / ("national-segment-selection-" +
                        day.isoformat() + ".json")


def _read_selector(path, day):
    if path.is_symlink():
        raise ValueError("unsafe_national_selection_file")
    if not path.exists():
        return 0
    try:
        payload = json.loads(_safe_existing_file(path, MAX_INDEX_BYTES))
    except (ValueError, UnicodeError):
        raise ValueError("invalid_national_selection_state") from None
    if (not isinstance(payload, dict)
            or set(payload) != {"schema", "day", "next_index"}
            or payload["schema"] != SELECT_SCHEMA
            or payload["day"] != day.isoformat()
            or type(payload["next_index"]) is not int
            or not 0 <= payload["next_index"] < 10**9):
        raise ValueError("untrusted_national_selection_state")
    return payload["next_index"]


def run_all_discovered_segments(
        private_campaign_dir, private_state_dir, day, *,
        execute_live=False, key=None, event_budget=MAX_EVENTS_PER_STEP,
        segment_budget=MAX_SEGMENTS_PER_RUN,
        rotator_options=None, rotator=None):
    """Auto-enumerate ALL current campaign segments, fair round-robin by file.

    New reports are discovered on subsequent invocations. Report limits
    bound each run, not membership; no city, domain or agenda goes into a
    static manifest. A broken report produces a hold, not starvation.
    """
    private_campaign_dir, private_state_dir = (
        Path(private_campaign_dir), Path(private_state_dir))
    _private_directory(private_state_dir)
    reports = _candidate_reports(private_campaign_dir)
    if (private_campaign_dir.resolve() == private_state_dir.resolve()
            or type(day) is not date
            or type(segment_budget) is not int
            or not 1 <= segment_budget <= MAX_SEGMENTS_PER_RUN):
        raise ValueError("invalid_national_runner_inputs")
    if not execute_live:
        return {
            "mode": "dry_run_no_network_or_writes",
            "segment_reports_detected": len(reports),
            "public_writes": 0,
        }
    if not _valid_public_read_key(key):
        raise ValueError("public_oa_key_missing")
    path = _selection_path(private_state_dir, day)
    lock = _acquire_lock(path.with_suffix(".lock"))
    try:
        start = _read_selector(path, day)
        outputs = []
        for step in range(min(segment_budget, len(reports))):
            idx = (start + step) % len(reports)
            try:
                output = run_segment_file(
                    reports[idx], private_state_dir, day,
                    execute_live=True, key=key, event_budget=event_budget,
                    rotator_options=rotator_options, rotator=rotator)
                # Only generic counts leave the protected per-segment file.
                outputs.append({"status": "processed",
                                "events_considered":
                                output["events_considered"]})
            except (ValueError, OSError, TimeoutError, TypeError, KeyError):
                outputs.append({"status": "segment_requires_research_review",
                                "events_considered": 0})
        # Atomically advance the selector after each batch. A process crash
        # may replay a file, but cannot lose its individually saved checkpoint.
        next_index = (start + len(outputs)) % len(reports) if reports else 0
        _write_atomic_private(path, _json_bytes({
            "schema": SELECT_SCHEMA, "day": day.isoformat(),
            "next_index": next_index,
        }))
        return {
            "mode": "private_research_only",
            "segment_reports_detected": len(reports),
            "segment_reports_examined": len(outputs),
            "segment_reports_held": sum(
                x["status"] != "processed" for x in outputs),
            "event_slots_examined": sum(
                x["events_considered"] for x in outputs),
            "publisher_connected": False,
            "publication_ready": False, "public_writes": 0,
        }
    finally:
        lock.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-campaign-dir", type=Path, required=True)
    parser.add_argument("--private-state-dir", type=Path, required=True)
    parser.add_argument("--day", required=True, type=date.fromisoformat)
    parser.add_argument("--max-segments", default=MAX_SEGMENTS_PER_RUN, type=int)
    parser.add_argument("--events-per-segment", default=MAX_EVENTS_PER_STEP,
                        type=int)
    parser.add_argument("--execute-live", action="store_true")
    args = parser.parse_args()
    result = run_all_discovered_segments(
        args.private_campaign_dir, args.private_state_dir, args.day,
        execute_live=args.execute_live,
        key=os.environ.get("OPENAGENDA_READ_KEY", ""),
        segment_budget=args.max_segments,
        event_budget=args.events_per_segment)
    print(json.dumps(result, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    main()
