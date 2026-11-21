#!/usr/bin/env python3
"""Preserve PRIVATE open-world research when another same-day intake starts.

Fresh collection correctly rebuilds historical additions, but it does not
understand the separate research-only queue. Do not delete those unapproved
requests simply because a new collector run or a review-slot catchup is empty.

This is strictly private and offline. It cannot approve, verify, publish or
write public catalogues. The independent Publisher rechecks every request.
"""
import argparse
from datetime import date
from pathlib import Path

from ptitesondes_open_world_private_dossier_intake import (
    attach_research_dossiers,
)
from ptitesondes_national_backlog_bridge import _atomic_json, _read


def carry_same_day_research(previous, fresh, today):
    """Copy only research hints from a matching private patch, never approvals."""
    if type(today) is not date:
        raise ValueError("invalid_research_carry_day")
    for patch in (previous, fresh):
        if (type(patch) is not dict
                or patch.get("schema") != "ptitesondes.patch.v1"
                or patch.get("generated_at") != today.isoformat()
                or patch.get("safe_to_publish") is not False
                or type(patch.get("source")) is not dict
                or type(patch.get("checks")) is not dict
                or patch["checks"].get("ids_unique") is not True
                or not all(isinstance(patch.get(k), list)
                           for k in ("additions", "updates", "deferred"))
                or patch["updates"]):
            raise ValueError("invalid_or_stale_private_patch")
    if previous["source"] != fresh["source"]:
        raise ValueError("private_reference_changed_during_carry")
    if "open_world_research" not in previous:
        return fresh
    queue = previous["open_world_research"]
    if not isinstance(queue, list) or len(queue) > 30:
        raise ValueError("invalid_private_research_queue")
    # This cannot overwrite the newly collected historical additions.
    # A simultaneous new queue on the fresh patch is deduplicated.
    return attach_research_dossiers(fresh, queue, today)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--existing", required=True, type=Path)
    parser.add_argument("--fresh", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--day", required=True, type=date.fromisoformat)
    args = parser.parse_args()
    checkout = Path(__file__).resolve().parents[1].resolve()
    for file in (args.existing, args.fresh, args.output):
        if file.resolve().is_relative_to(checkout):
            raise ValueError("private_research_carry_must_not_write_public_checkout")
    if args.output == args.existing or args.output == args.fresh:
        raise ValueError("private_carry_requires_distinct_output")
    existing, _ = _read(args.existing, 1_500_000)
    fresh, _ = _read(args.fresh, 1_500_000)
    combined = carry_same_day_research(existing, fresh, args.day)
    _atomic_json(args.output, combined)
    # Never log the private candidate IDs, titles, URLs or venues.
    print("PRIVATE_RESEARCH_QUEUE_CARRIED: no approval, no public writes")


if __name__ == "__main__":
    main()
