#!/usr/bin/env python3
"""Private-only read/plan/stage independent HTML verification worklist.

Runs within the pre-existing public GitHub runner AFTER loading its authenticated
private checkout. It never fetches arbitrary URLs, authorizes publication,
writes public files, commits, pushes, or reveals confidential review fields.
No action processes the worklist until a separately reviewed worker exists.
"""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import tempfile
from zoneinfo import ZoneInfo

from ptitesondes_html_private_queue_cycle import (
    _private_target, _load_queue, MAX_FILE_BYTES,
)
from ptitesondes_html_independent_review_planner import (
    plan_independent_reviews, SCHEMA as PLANNER_SCHEMA,
)

SCHEMA = "ptitesondes.html_independent_private_worklist_stage.v1"
PRIVATE_WORKLIST = Path("automation-intake/ptitesondes/html-independent-worklist.json")
MAX_WORKLIST_BYTES = 500_000


def stage_private_worklist(root, plan, now):
    """Atomic, fixed-location PRIVATE write; output is a plan, not evidence."""
    queue_target = _private_target(root)
    worklist_path = queue_target.parents[1] / PRIVATE_WORKLIST
    # Note: queue_target is <root>/automation-intake/ptitesondes/..,
    # parents[1] must be <root>/automation-intake, NOT repo root. The
    # precise target is constructed relative to validated checkout.
    worklist_path = queue_target.parent / "html-independent-worklist.json"
    if (worklist_path.is_symlink() or not worklist_path.parent.is_dir()
            or plan.get("schema") != PLANNER_SCHEMA
            or type(plan.get("private_tasks")) is not dict
            or not isinstance(now, datetime)
            or now.tzinfo is None or now.utcoffset() is None):
        raise ValueError("invalid_private_worklist")
    payload = {
        "schema": SCHEMA,
        "planned_on": now.date().isoformat(),
        "worklist_is_evidence": False,
        "publication_ready": False,
        "approved": False,
        "published": False,
        "tasks": plan["private_tasks"],
    }
    raw = (json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)
           + "\n").encode("utf-8")
    if len(raw) > MAX_WORKLIST_BYTES:
        raise ValueError("private_worklist_oversize")
    fd, tmp = tempfile.mkstemp(prefix=".html-private-worklist-", dir=worklist_path.parent)
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(raw)
            file.flush()
            os.fsync(file.fileno())
        os.replace(tmp, worklist_path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return worklist_path


def execute_worklist(root, now, *, mode="preview", limit=40,
                     source_limit=12):
    if mode not in ("preview", "stage"):
        raise ValueError("invalid_private_worklist_mode")
    queue_file = _private_target(root)
    queue = _load_queue(queue_file)
    plan = plan_independent_reviews(
        queue, now.date(), limit=limit, source_limit=source_limit)
    if mode == "stage":
        stage_private_worklist(root, plan, now)
    # Public logs must contain counts only. Source URLs, review IDs, cities,
    # dates of individual sessions, and task identities remain private.
    return dict(plan["report"], mode=mode)


def main():
    arg = argparse.ArgumentParser()
    arg.add_argument("--state-checkout", type=Path, required=True)
    arg.add_argument("--mode", choices=("preview", "stage"), default="preview")
    arg.add_argument("--limit", type=int, default=40)
    arg.add_argument("--source-limit", type=int, default=12)
    a = arg.parse_args()
    try:
        r = execute_worklist(
            a.state_checkout, datetime.now(ZoneInfo("Europe/Paris")),
            mode=a.mode, limit=a.limit, source_limit=a.source_limit)
        print(json.dumps(r, ensure_ascii=False, sort_keys=True))
    except (OSError, UnicodeError, TypeError, ValueError, KeyError):
        raise SystemExit("PRIVATE_HTML_WORKLIST_FAILED_CLOSED") from None


if __name__ == "__main__":
    main()
