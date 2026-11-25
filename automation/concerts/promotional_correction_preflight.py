#!/usr/bin/env python3
"""Private append-only correction gate; never writes the public catalogue.

A proposal is not an approval. Run the existing trusted Publisher preview
on a single exact correction, then atomically append it only in apply mode.
Keep new event/site publication independent of this maintenance operation.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from automation.concerts.approval_preflight import atomic_store
from automation.concerts.published_lineup_patch_builder import SCHEMA
from scripts import concert_published_lineup_contract as contract
from scripts import concerts_private_approval_preview as preview


def select(previous, report, reference, current, today, *, audit=preview.audit):
    """Return an unchanged or one-row-extended ledger and private diagnostics."""
    result = {"status": "no_changes", "validatedByPublisher": False,
              "applied": False, "examined": 0, "held": 0}
    if (not isinstance(report, dict) or report.get("schema") != SCHEMA
            or report.get("asOf") != today.isoformat()
            or report.get("publicationAllowed") is not False
            or report.get("publisherAuthorityGranted") is not False
            or not isinstance(report.get("proposals"), list)):
        result["status"] = "invalid_or_stale_proposals"
        return previous, result
    if (not isinstance(previous, dict)
            or previous.get("schema") != "grossesondes.concert.approvals.v1"
            or not isinstance(previous.get("approvals"), list)
            or not isinstance(previous.get("lineupCorrections", []), list)):
        raise ValueError("Invalid private approval ledger")
    events = {e["id"]: e for e in current["events"]}
    approvals = {a["event"]["id"]: a for a in previous["approvals"]}
    if len(approvals) != len(previous["approvals"]):
        raise ValueError("Duplicate historical approval ID")
    if not approvals.keys() <= events.keys():
        result["status"] = "deferred_new_events_pending"
        return previous, result
    old = previous.get("lineupCorrections", [])
    corrected = {r["eventId"] for r in old}
    if len(corrected) != len(old):
        raise ValueError("Duplicate historical correction ID")
    for row in old:
        e = events.get(row["eventId"], {})
        if (e.get("artistIds") != row.get("artistIds")
                or e.get("title") != row.get("title")):
            result["status"] = "deferred_previous_correction_pending"
            return previous, result
    protected = {e["id"] for e in reference["events"]}
    seen = set()
    for row in report["proposals"]:
        if not isinstance(row, dict):
            continue
        evidence = row.get("officialEvidence")
        if (not isinstance(evidence, list) or len(evidence) != 1
                or not isinstance(evidence[0], dict)
                or evidence[0].get("proofType") != contract.PROMOTIONAL_PROOF):
            continue
        eid = row.get("eventId")
        if (not isinstance(eid, str) or eid in seen or eid in corrected
                or eid in protected or eid not in approvals
                or eid not in events):
            continue
        if result["examined"] >= 8:
            break
        seen.add(eid)
        result["examined"] += 1
        if row.get("reviewedAt") != today.isoformat():
            result["held"] += 1
            continue
        proposed = copy.deepcopy(previous)
        proposed.setdefault("lineupCorrections", []).append(copy.deepcopy(row))
        try:
            contract.plan(row, approvals[eid], current, today)
            # Real publisher re-fetches the UID-bound source independently,
            # checks historical protections and the exact event/artist delta.
            if audit(previous, proposed, reference, current, today) != 1:
                raise ValueError("Unexpected private correction preview delta")
        except (ValueError, TypeError, KeyError, OSError, TimeoutError):
            result["held"] += 1
            continue
        result["status"] = "validated"
        result["validatedByPublisher"] = True
        return proposed, result
    if result["held"]:
        result["status"] = "held"
    return previous, result


def main():
    parser = argparse.ArgumentParser()
    for name in ("before", "proposals", "reference", "catalogue", "report"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    def load(path):
        return json.loads(path.read_text(encoding="utf-8"))
    original = load(args.before)
    today = dt.datetime.now(ZoneInfo("Europe/Paris")).date()
    proposed, result = select(original, load(args.proposals),
                              load(args.reference), load(args.catalogue), today)
    if args.apply and result["validatedByPublisher"]:
        atomic_store(args.before, proposed)
        result["applied"] = True
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print("Promotional correction preflight complete; see private report.")


if __name__ == "__main__":
    main()
