#!/usr/bin/env python3
"""Fail-closed, offline publication preflight for proposed private approvals.

Official discoveries are still quarantined.  This command verifies that a
proposed *append-only* change to approved.json survives the EXACT cloud
publisher's merge/validation, before an automated workflow may persist it.
No private record is uploaded to a public workflow artifact or printed.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import sys
import tempfile
from zoneinfo import ZoneInfo


def require(condition, message):
    if not condition:
        raise ValueError(message)


def check_append_only(previous, proposed, today):
    """Reject deletion, mutation, reviewer substitution and duplicate IDs."""
    require(isinstance(previous, dict) and isinstance(proposed, dict),
            "Approval queues must be JSON objects")
    require(previous.get("schema") == "grossesondes.concert.approvals.v1"
            and proposed.get("schema") == previous["schema"],
            "Unknown approvals schema")
    require(previous.keys() == proposed.keys(), "Approval metadata changed")
    old = previous.get("approvals")
    new = proposed.get("approvals")
    require(isinstance(old, list) and isinstance(new, list),
            "Missing approval list")
    require(len(new) >= len(old) and new[:len(old)] == old,
            "Existing private approvals were modified or removed")
    for key in previous:
        if key != "approvals":
            require(proposed[key] == previous[key],
                    "Protected private approval metadata changed")
    appended = new[len(old):]
    require(len(appended) <= 16, "Too many new approvals in a single pass")
    existing_ids = {a.get("event", {}).get("id") for a in old
                    if isinstance(a, dict) and isinstance(a.get("event"), dict)}
    added_ids = set()
    pairs = set()
    for approval in appended:
        require(isinstance(approval, dict)
                and approval.get("reviewDecision") == "approved"
                and approval.get("reviewedBy") == "automated-official-recheck"
                and approval.get("reviewedAt") == today.isoformat(),
                "Unexpected automated reviewer or stale official review")
        event = approval.get("event")
        require(isinstance(event, dict), "Missing approved event")
        event_id = event.get("id")
        require(isinstance(event_id, str) and event_id
                and event_id not in existing_ids and event_id not in added_ids,
                "Duplicate or missing approval event ID")
        added_ids.add(event_id)
        pair = (event.get("officialUrl"), event.get("date"))
        require(all(isinstance(x, str) and x for x in pair)
                and pair not in pairs,
                "Duplicate official URL and event date")
        pairs.add(pair)
    return appended


def validate_proposal(previous, proposed, reference, current, today, publisher):
    """Use the real publisher to prove that EVERY new approval can be emitted."""
    appended = check_append_only(previous, proposed, today)
    if not appended:
        return {"newApprovals": 0, "publishableEvents": 0,
                "validatedByPublisher": False}
    already = {e["id"] for e in current["events"]}
    incoming = {approval["event"]["id"] for approval in appended}
    require(not incoming.intersection(already),
            "An automated approval ID is already in the public catalogue")
    candidate, stats = publisher(reference, current, proposed, today)
    published = {e["id"]: e for e in candidate["events"]}
    for approval in appended:
        event = approval["event"]
        require(published.get(event["id"]) == event,
                "At least one proposed approval was held or modified by the publisher")
    require(len(candidate["events"]) - len(current["events"]) == len(appended),
            "Unexpected number of publishable events")
    return {"newApprovals": len(appended),
            "publishableEvents": len(appended),
            "validatedByPublisher": True}


def atomic_store(path, data):
    """Never leave a partially written private approvals file."""
    descriptor, filename = tempfile.mkstemp(
        prefix=".approved-preflight-", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as out:
            json.dump(data, out, indent=2, ensure_ascii=False)
            out.write("\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(filename, path)
    finally:
        if os.path.exists(filename):
            os.unlink(filename)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--catalogue", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    def load(path):
        return json.loads(path.read_text(encoding="utf-8"))
    original, proposed = load(args.before), load(args.candidate)
    reference, current = load(args.reference), load(args.catalogue)
    today = dt.datetime.now(ZoneInfo("Europe/Paris")).date()
    # Import the exact production publisher, not a simplified approximation.
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / "scripts"))
    import concerts_cloud_sync
    stats = validate_proposal(
        original, proposed, reference, current, today,
        concerts_cloud_sync.merge)
    stats["applied"] = bool(args.apply and stats["newApprovals"])
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(stats, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    if stats["applied"]:
        atomic_store(args.before, proposed)
    print("Official approval preflight: checked; see private report.")


if __name__ == "__main__":
    main()
