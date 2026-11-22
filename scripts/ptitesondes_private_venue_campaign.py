#!/usr/bin/env python3
"""Private, explicit seven-batch venue campaign runner; never a publisher.

Dry-run is the default. No GitHub workflow, scheduler, token reader, public
artifact or catalogue writer is reachable from this entrypoint.
"""
import argparse
from datetime import date
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys

from ptitesondes_generic_venue_osm_preflight import (
    MAX_PER_RUN, groups_for_review,
)
from ptitesondes_private_venue_batch_rollup import rollup_private_batches

ROOT = Path(__file__).resolve().parents[1]
PREFLIGHT = ROOT / "scripts" / "ptitesondes_generic_venue_osm_preflight.py"
MAX_BACKLOG_BYTES = 1_000_000
MAX_SOURCES_BYTES = 60_000
MAX_REPORT_BYTES = 1_000_000


def _private_file(path, byte_limit):
    if (path.is_symlink() or not path.is_file()
            or path.resolve().is_relative_to(ROOT)
            or not 0 < path.stat().st_size <= byte_limit):
        raise ValueError("invalid_private_input_path")


def _private_directory(path):
    if (path.is_symlink() or not path.is_dir()
            or path.resolve().is_relative_to(ROOT)
            or path.stat().st_mode & 0o077):
        raise ValueError("invalid_private_output_directory")


def _fingerprint(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare_campaign(backlog_path, source_path, output_dir, day):
    """Read only private inputs; return an exact-day, bounded batch plan."""
    if type(day) is not date:
        raise ValueError("invalid_campaign_day")
    _private_file(backlog_path, MAX_BACKLOG_BYTES)
    _private_file(source_path, MAX_SOURCES_BYTES)
    _private_directory(output_dir)
    backlog = json.loads(backlog_path.read_text(encoding="utf-8"))
    sources = json.loads(source_path.read_text(encoding="utf-8"))
    if (not isinstance(backlog, list)
            or not isinstance(sources, dict)
            or sources.get("schema") != "ptitesondes.sources.v1"
            or not isinstance(sources.get("openagenda_agendas"), list)):
        raise ValueError("invalid_private_campaign_input")
    groups = groups_for_review(backlog, day)
    batch_count = math.ceil(len(groups) / MAX_PER_RUN)
    names = [output_dir / ("venue-batch-" + day.isoformat() + "-"
                           + str(i) + ".json") for i in range(batch_count)]
    summary_path = output_dir / ("venue-campaign-" + day.isoformat() + ".json")
    if any(path.exists() or path.is_symlink()
           for path in [*names, summary_path]):
        raise ValueError("private_campaign_output_already_exists")
    return {
        "batch_count": batch_count,
        "unknown_venues": len(groups),
        "report_paths": names,
        "summary_path": summary_path,
        "backlog_hash": _fingerprint(backlog_path),
        "sources_hash": _fingerprint(source_path),
    }


def _assert_snapshot(plan, backlog_path, source_path):
    if (_fingerprint(backlog_path) != plan["backlog_hash"]
            or _fingerprint(source_path) != plan["sources_hash"]):
        raise ValueError("private_campaign_snapshot_changed")


def _safe_summary(summary):
    """Whitelist ONLY aggregate counters; never serialize private records."""
    keys = (
        "batches_complete", "batches_examined", "unknown_unique_venues",
        "unknown_distinct_candidate_sessions", "full_live_scan",
        "reusable_location_proof_venues_private",
        "candidate_sessions_on_proven_places_not_published",
        "publication_ready", "public_writes",
    )
    return {key: summary[key] for key in keys}


def execute_campaign(plan, backlog_path, source_path, output_dir, day,
                     runner=subprocess.run):
    """Execute only on explicit opt-in, with seven disjoint reports in private."""
    if not os.environ.get("OPENAGENDA_READ_KEY"):
        raise ValueError("openagenda_public_read_key_required")
    if plan["batch_count"] == 0:
        raise ValueError("no_private_venues_to_examine")
    _private_file(backlog_path, MAX_BACKLOG_BYTES)
    _private_file(source_path, MAX_SOURCES_BYTES)
    _private_directory(output_dir)
    _assert_snapshot(plan, backlog_path, source_path)
    old_umask = os.umask(0o077)
    try:
        for i, report in enumerate(plan["report_paths"]):
            _assert_snapshot(plan, backlog_path, source_path)
            command = [
                sys.executable, str(PREFLIGHT),
                "--backlog", str(backlog_path),
                "--private-source-config", str(source_path),
                "--output-private-report", str(report),
                "--day", day.isoformat(),
                "--batch-index", str(i),
                "--live-probe", "--official-municipal-pages",
                "--official-address-geocode", "--shared-location-evidence",
            ]
            # Never echo subprocess stdout/stderr: even an exception may
            # contain private venue names, UID, source URLs or local paths.
            try:
                result = runner(
                    command, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, check=False, timeout=1800)
            except subprocess.TimeoutExpired:
                raise RuntimeError("private_campaign_batch_timeout") from None
            if result.returncode != 0:
                raise RuntimeError("private_campaign_batch_failed") from None
            if (report.is_symlink() or not report.is_file()
                    or report.stat().st_size > MAX_REPORT_BYTES):
                raise ValueError("invalid_private_batch_report")
            _assert_snapshot(plan, backlog_path, source_path)
        reports = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in plan["report_paths"]
        ]
        summary = rollup_private_batches(reports)
        safe = _safe_summary(summary)
        with plan["summary_path"].open("x", encoding="utf-8") as out:
            json.dump(safe, out, ensure_ascii=False, indent=2)
            out.write("\n")
        return safe
    finally:
        os.umask(old_umask)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backlog", required=True, type=Path)
    parser.add_argument("--private-source-config", required=True, type=Path)
    parser.add_argument("--private-output-dir", required=True, type=Path)
    parser.add_argument("--day", type=date.fromisoformat, required=True)
    parser.add_argument("--execute-live", action="store_true")
    args = parser.parse_args()
    plan = prepare_campaign(
        args.backlog, args.private_source_config,
        args.private_output_dir, args.day)
    if not args.execute_live:
        print(json.dumps({
            "mode": "dry_run_only", "unknown_venues": plan["unknown_venues"],
            "batch_count": plan["batch_count"], "public_writes": 0,
        }))
        return
    safe = execute_campaign(
        plan, args.backlog, args.private_source_config,
        args.private_output_dir, args.day)
    print(json.dumps(safe))


if __name__ == "__main__":
    main()
