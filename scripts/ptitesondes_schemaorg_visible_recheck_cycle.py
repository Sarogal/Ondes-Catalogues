#!/usr/bin/env python3
"""Trusted private runner: recheck structured hints against VISIBLE HTML.

No GitHub secrets, commits, pushes, publication patches or public writes.
The verified private checkout is the only possible file-writing destination.
A live GitHub Pages comparison is required before any recheck of duplicates.
"""
import argparse
from datetime import datetime, timedelta
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from ptitesondes_html_index_detail_live_smoke import _independent_context
from ptitesondes_html_private_queue_cycle import (
    _private_target, _load_queue, _stage_queue, _validated_manifest,
)
from ptitesondes_public_catalogue_live_drift import check_served_catalogue
from ptitesondes_schemaorg_private_intake import (
    _file as _hints_target, _read_private, _validate_pins,
)
from ptitesondes_schemaorg_visible_session_recheck import (
    recheck_schemaorg_visible_sessions,
)

SCHEMA = "ptitesondes.schemaorg_private_visible_recheck_cycle.v1"


def run_recheck(root, now, *, mode="preview", limit=24,
                live_checker=check_served_catalogue,
                review_runner=recheck_schemaorg_visible_sessions):
    if (type(now) is not datetime or now.tzinfo is None
            or now.utcoffset() is None
            or mode not in ("preview", "stage")
            or type(limit) is not int or not 1 <= limit <= 40):
        raise ValueError("invalid_schemaorg_recheck_cycle")
    # Validate private checkout before even reading its untrusted hints.
    review_path = _private_target(root)
    hints_path = _hints_target(root)
    hints = _read_private(hints_path)
    existing_reviews = _load_queue(review_path)
    # The timestamp in the JSON describes last DATA change, not live fetch.
    # Evidence is only routed after a *current* bounded, exact HTTPS fetch.
    live = live_checker(now)
    if (type(live) is not dict
            or live.get("same_data_as_checked_out_repository") is not True
            or type(live.get("live_event_count")) is not int
            or live["live_event_count"] < 100
            or live.get("live_event_count") != live.get("local_event_count")
            or live.get("public_writes") != 0
            or live.get("publication_ready") is not False
            or live.get("approval_granted") is not False):
        raise ValueError("schemaorg_live_catalogue_mismatch")
    independent = _independent_context()
    manifest = _validated_manifest()
    pins = _validate_pins()
    # Conservative global day prevents a still-current overseas session from
    # being discarded just because it is tomorrow in mainland France.
    earliest_day = (now.astimezone(ZoneInfo("UTC")) - timedelta(days=1)).date()
    result = review_runner(
        existing_reviews, hints, earliest_day, manifest, pins, independent,
        limit=limit, offset=now.toordinal() * 4 + now.hour // 6)
    if (type(result) is not dict
            or type(result.get("private_review_queue")) is not list
            or type(result.get("report")) is not dict
            or result["report"].get("public_writes") != 0
            or result["report"].get("publication_ready") is not False
            or result["report"].get("publisher_connected") is not False):
        raise ValueError("unsafe_schemaorg_visible_recheck")
    if mode == "stage":
        _stage_queue(review_path, result["private_review_queue"])
    return {
        "schema": SCHEMA,
        "live_catalogue_refetched_matching": True,
        "mode": mode,
        **result["report"],
    }


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--state-checkout", type=Path, required=True)
    a.add_argument("--mode", choices=("preview", "stage"), default="preview")
    a.add_argument("--limit", type=int, default=24)
    args = a.parse_args()
    try:
        report = run_recheck(
            args.state_checkout, datetime.now(ZoneInfo("Europe/Paris")),
            mode=args.mode, limit=args.limit)
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    except (ValueError, TypeError, KeyError, OSError, UnicodeError):
        raise SystemExit("PRIVATE_SCHEMAORG_VISIBLE_RECHECK_FAILED_CLOSED") from None


if __name__ == "__main__":
    main()
