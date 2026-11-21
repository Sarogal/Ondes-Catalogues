#!/usr/bin/env python3
"""Manual, private-only OpenAgenda national observation orchestration.

This is NOT a publisher, scheduler or admission decision. Its inputs and all
evidence remain in an outside-checkout 0700 directory. It continues previously
captured index batches and discovers new ones without any source allowlist.
The caller alone is responsible for persisting that PRIVATE directory between
ephemeral GitHub runners; stdout contains counters only.
"""
import argparse
from datetime import date
from hashlib import sha256
import json
import os
from pathlib import Path
import re

from ptitesondes_openagenda_public_agenda_index import (
    MAX_CONFIG_BYTES, load_state as load_index_state,
    scan_index_pages, _write_new_report, _write_state_atomic,
)
from ptitesondes_openagenda_national_event_research import (
    MAX_INDEX_BYTES, _private_directory, _private_input,
)
from ptitesondes_openagenda_v2_direct_evidence import _valid_public_read_key
from ptitesondes_private_national_event_campaign import (
    plan_campaign, run_campaign,
)
from ptitesondes_private_national_rotation_runner import (
    MAX_SEGMENTS_PER_RUN, run_all_discovered_segments,
    _write_atomic_private, _safe_existing_file,
)

CONTROLLER_SCHEMA = "ptitesondes.private_national_observation_control.v1"
REPORT_RE = re.compile(r"index-(20[0-9]{2}-[0-9]{2}-[0-9]{2})-([a-zA-Z0-9_-]{1,70})\\.json\\Z")
BATCH_RE = re.compile(r"[a-zA-Z0-9_-]{1,70}\\Z")
INDEX_EVERY_N_INVOCATIONS = 12
MAX_BATCHES_PER_RUN = 2
MAX_CONTROL_BYTES = 4096


def private_subdir(path):
    path = Path(path)
    if not path.exists():
        path.mkdir(mode=0o700)
    _private_directory(path)
    return path


def controller_read(path):
    if not path.exists():
        return {"schema": CONTROLLER_SCHEMA, "invocations": 0,
                "next_batch_index": 0}
    raw = _safe_existing_file(path, MAX_CONTROL_BYTES)
    data = json.loads(raw)
    if (not isinstance(data, dict)
            or set(data) != {"schema", "invocations", "next_batch_index"}
            or data["schema"] != CONTROLLER_SCHEMA
            or type(data["invocations"]) is not int
            or not 0 <= data["invocations"] < 10**9
            or type(data["next_batch_index"]) is not int
            or not 0 <= data["next_batch_index"] < 10**9):
        raise ValueError("untrusted_private_observation_controller")
    return data


def available_index_reports(index_dir):
    reports = []
    for path in index_dir.iterdir():
        match = REPORT_RE.fullmatch(path.name)
        if match:
            _private_input(path, MAX_INDEX_BYTES)
            scan_day = date.fromisoformat(match.group(1))
            reports.append((path, scan_day))
    return sorted(reports, key=lambda pair: pair[0].name)


def run_observation(source_config, root, day, batch_id, *,
                    execute_live=False, key="", index_reader=scan_index_pages,
                    campaign_runner=run_campaign,
                    segment_runner=run_all_discovered_segments):
    """Inspect a bounded fair rotation; resume every saved campaign batch.

    The original day stays attached to each collected report. Older reports
    remain discoverable rather than being silently dropped at midnight. Their
    old evidence is research ONLY and must be freshly checked for admission.
    """
    root = Path(root)
    _private_directory(root)
    if type(day) is not date or not isinstance(batch_id, str) or not BATCH_RE.fullmatch(batch_id):
        raise ValueError("invalid_private_observation_arguments")
    index_dir = private_subdir(root / "index") if execute_live else root / "index"
    reports_dir = private_subdir(index_dir / "reports") if execute_live else index_dir / "reports"
    existing = (available_index_reports(reports_dir)
                if reports_dir.is_dir() else [])
    if not execute_live:
        return {"mode": "dry_run_no_network_or_writes",
                "stored_index_batches": len(existing), "public_writes": 0}
    if not _valid_public_read_key(key):
        raise ValueError("private_observation_read_key_required")
    config_raw = _private_input(Path(source_config), MAX_CONFIG_BYTES)
    config = json.loads(config_raw)
    if (not isinstance(config, dict)
            or config.get("schema") != "ptitesondes.sources.v1"
            or not isinstance(config.get("openagenda_agendas"), list)):
        raise ValueError("invalid_private_sources_contract")
    campaign_root = private_subdir(root / "campaigns")
    rotation_root = private_subdir(root / "rotations")
    control_path = root / "controller.json"
    controller = controller_read(control_path)

    # Index census is independent from the historical 16 known agendas. The
    # existing config is used only to identify which OA UIDs are already known.
    # Keep each batch: adding a fresh index cannot destroy unfinished ones.
    name = f"index-{day.isoformat()}-{batch_id}.json"
    new_path = reports_dir / name
    index_scanned = False
    if controller["invocations"] % INDEX_EVERY_N_INVOCATIONS == 0:
        if not new_path.exists():
            state_path = index_dir / "cursor.json"
            state = load_index_state(state_path)
            result = index_reader(
                config["openagenda_agendas"],
                start_cursor=state["after"], public_read_key=key,
            )
            if (result.get("schema") != "ptitesondes.private_national_oa_index.v1"
                    or result.get("publication_ready") is not False
                    or result.get("public_writes") != 0):
                raise ValueError("untrusted_national_index_response")
            _write_new_report(new_path, result)
            # The report is safely stored BEFORE advancing the index cursor.
            _write_state_atomic(state_path, {
                "schema": state["schema"], "after": result["next_cursor"],
                "completed_passes": state["completed_passes"] +
                                    int(result["index_pass_exhausted"]),
            })
            index_scanned = True

    reports = available_index_reports(reports_dir)
    n = len(reports)
    started = held = completed = examined_segments = examined_events = 0
    # Round robin across ALL saved batches; old batches are never replaced by
    # today's index. New reports enter the same queue on subsequent passes.
    start = controller["next_batch_index"] % n if n else 0
    selected = [reports[(start + step) % n]
                for step in range(min(n, MAX_BATCHES_PER_RUN))]
    for report_path, scan_day in selected:
        try:
            raw = _private_input(report_path, MAX_INDEX_BYTES)
            digest = sha256(raw).hexdigest()
            campaign = private_subdir(campaign_root / digest[:24])
            rotation = private_subdir(rotation_root / digest[:24])
            plan = plan_campaign(json.loads(raw), digest, scan_day, campaign)
            result = campaign_runner(plan, public_key=key)
            if (result.get("public_writes") != 0
                    or result.get("publication_ready") is not False):
                raise ValueError("unsafe_national_campaign_result")
            started += 1
            completed += int(result["finished_index_batch"])
            rotation_result = segment_runner(
                campaign, rotation, scan_day, execute_live=True, key=key,
                segment_budget=MAX_SEGMENTS_PER_RUN,
            )
            if (rotation_result.get("public_writes") != 0
                    or rotation_result.get("publication_ready") is not False):
                raise ValueError("unsafe_national_rotation_result")
            examined_segments += rotation_result["segment_reports_examined"]
            examined_events += rotation_result["event_slots_examined"]
            held += rotation_result["segment_reports_held"]
        except (OSError, ValueError, TypeError, KeyError, TimeoutError,
                UnicodeError):
            # This report stays on disk and remains in the next rotation.
            held += 1

    updated = {
        "schema": CONTROLLER_SCHEMA,
        "invocations": controller["invocations"] + 1,
        "next_batch_index": (start + len(selected)) % n if n else 0,
    }
    _write_atomic_private(control_path, (
        json.dumps(updated, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8"))
    return {"mode": "private_observation_readonly",
            "stored_index_batches": n, "new_index_census": int(index_scanned),
            "index_batches_examined": len(selected),
            "index_batches_advanced": started,
            "index_batches_finished_this_pass": completed,
            "segments_examined": examined_segments,
            "event_slots_examined": examined_events,
            "held_for_research": held,
            "publisher_connected": False,
            "publication_ready": False, "public_writes": 0}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--private-source-config", required=True, type=Path)
    parser.add_argument("--private-observation-root", required=True, type=Path)
    parser.add_argument("--day", required=True, type=date.fromisoformat)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--execute-live", action="store_true")
    args = parser.parse_args()
    result = run_observation(
        args.private_source_config, args.private_observation_root,
        args.day, args.batch_id, execute_live=args.execute_live,
        key=os.environ.get("OPENAGENDA_READ_KEY", ""))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
