#!/usr/bin/env python3
"""Stage ODS-missing OA-direct diagnostics on the *PRIVATE* storage branch only.

The bridge already owns the locked private git checkout and optional push.
This script performs no git/network writes and no catalogue publication.
The OpenAgenda read-only key is passed solely as an environment variable.
"""
import argparse
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import tempfile
from zoneinfo import ZoneInfo

from ptitesondes_html_private_queue_cycle import _private_target
from ptitesondes_ods_direct_mirror_absence_audit import (
    SCHEMA as AUDIT_SCHEMA, MAX_RECORDS, _safe_row,
    audit_missing_ods_direct,
)

SCHEMA = "ptitesondes.ods_direct_private_stage.v1"
RELATIVE = Path("automation-intake/ptitesondes/reports/ods-direct-mirror-audit.json")
BACKLOG = Path("automation-intake/ptitesondes/backlog.json")
SOURCES = Path("automation/sources.json")
MAX_BYTES = 350_000


def _valid_root(root):
    return _private_target(root).parents[2]


def _json(path, limit):
    if (not path.is_file() or path.is_symlink()
            or path.stat().st_size > limit):
        raise ValueError("private_source_file_unavailable")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        raise ValueError("private_source_file_invalid") from None


def _read_existing(path):
    if not path.exists():
        return []
    data = _json(path, MAX_BYTES)
    if type(data) is not dict or set(data) != {"schema", "private_rows"}:
        raise ValueError("private_direct_audit_schema_invalid")
    if data["schema"] != AUDIT_SCHEMA or type(data["private_rows"]) is not list:
        raise ValueError("private_direct_audit_schema_invalid")
    if len(data["private_rows"]) > MAX_RECORDS:
        raise ValueError("private_direct_audit_capacity")
    ids = set()
    for row in data["private_rows"]:
        _safe_row(row)
        if row["audit_id"] in ids:
            raise ValueError("private_direct_audit_duplicate_id")
        ids.add(row["audit_id"])
    return data["private_rows"]


def _stage(root, private_rows):
    if type(private_rows) is not list or len(private_rows) > MAX_RECORDS:
        raise ValueError("private_direct_audit_output_invalid")
    for row in private_rows:
        _safe_row(row)
    target = root / RELATIVE
    if target.is_symlink():
        raise ValueError("private_direct_audit_symlink")
    raw = (json.dumps({
        "schema": AUDIT_SCHEMA, "private_rows": private_rows,
    }, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    if len(raw) > MAX_BYTES:
        raise ValueError("private_direct_audit_output_oversize")
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".ods-direct-review-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, target)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def run_private_direct_cycle(root, now, *, mode="preview", max_work=12,
                             public_key=None, evaluator=audit_missing_ods_direct,
                             discover_unconfigured=False):
    if (type(now) is not datetime or now.tzinfo is None
            or now.utcoffset() is None
            or mode not in ("preview", "stage")
            or type(max_work) is not int or not 1 <= max_work <= 25
            or type(discover_unconfigured) is not bool
            or (discover_unconfigured and mode != "preview")):
        raise ValueError("private_direct_cycle_invalid")
    root = _valid_root(root)
    leads = _json(root / BACKLOG, 2_000_000)
    source_cfg = _json(root / SOURCES, 60_000)
    if (type(leads) is not list or len(leads) > 4000
            or type(source_cfg) is not dict
            or source_cfg.get("schema") != "ptitesondes.sources.v1"
            or type(source_cfg.get("openagenda_agendas")) is not list):
        raise ValueError("private_direct_sources_invalid")
    previous = _read_existing(root / RELATIVE)
    day = (now.astimezone(ZoneInfo("UTC")) - timedelta(days=1)).date()
    key = public_key if public_key is not None else os.environ.get("OPENAGENDA_READ_KEY", "")
    if not key:
        raise ValueError("public_read_only_key_missing")
    research_options = {}
    if discover_unconfigured:
        # Explicit preview opt-in only. No staged private write or production
        # workflow has been enabled. Unknown slugs remain untrusted sources.
        from ptitesondes_openagenda_slug_discovery import lookup_agenda_by_slug
        research_options["agenda_discovery"] = lookup_agenda_by_slug
    result = evaluator(
        leads, previous, source_cfg["openagenda_agendas"], key, day,
        offset=now.toordinal() * 4 + now.hour // 6,
        max_work=max_work, **research_options)
    if (type(result) is not dict
            or type(result.get("private_rows")) is not list
            or type(result.get("report")) is not dict
            or result["report"].get("publisher_connected") is not False
            or result["report"].get("approved") is not False
            or result["report"].get("publication_ready") is not False
            or result["report"].get("public_writes") != 0):
        raise ValueError("private_direct_audit_unsafe_report")
    # Validate results before writing. Even a compromised evaluator may not
    # smuggle rights/approval into a private file.
    for row in result["private_rows"]:
        _safe_row(row)
    if mode == "stage":
        _stage(root, result["private_rows"])
    # No candidate URL/UID, token, title, city, venue or date in stdout.
    return {"schema": SCHEMA, "mode": mode, **result["report"]}


def main():
    args = argparse.ArgumentParser()
    args.add_argument("--state-checkout", type=Path, required=True)
    args.add_argument("--mode", choices=("preview", "stage"), default="preview")
    args.add_argument("--max-work", type=int, default=12)
    args.add_argument("--discover-unconfigured", action="store_true",
                      help="read-only research, preview mode only; never publish")
    a = args.parse_args()
    try:
        report = run_private_direct_cycle(
            a.state_checkout, datetime.now(ZoneInfo("Europe/Paris")),
            mode=a.mode, max_work=a.max_work,
            discover_unconfigured=a.discover_unconfigured)
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    except (ValueError, TypeError, KeyError, OSError, UnicodeError):
        raise SystemExit("PRIVATE_ODS_DIRECT_AUDIT_FAILED_CLOSED") from None


if __name__ == "__main__":
    main()
