#!/usr/bin/env python3
"""Private, read-only geo preflight against the actual publisher.

The only authorized preview delta is one independently revalidated existing
venue patch. Concurrent pending concert approvals and lineup corrections must
produce exactly the same outputs with or without the proposed geo change.
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

from automation.concerts import existing_venue_geo_evidence as evidence
from scripts import concert_existing_venue_geo_contract as contract
from scripts import concerts_cloud_sync as sync


def select(previous, report, reference, current, today, *, publisher=sync.merge):
    result = {"status": "no_changes", "examined": 0, "held": 0,
              "validatedByPublisher": False, "applied": False}
    if (not isinstance(report, dict)
            or report.get("schema") != evidence.SCHEMA + ".scan"
            or report.get("asOf") != today.isoformat()
            or report.get("publicationAllowed") is not False
            or report.get("publisherAuthorityGranted") is not False
            or not isinstance(report.get("proposals"), list)):
        result["status"] = "invalid_or_stale_proposals"
        return previous, result
    contract.require(isinstance(previous, dict)
                     and previous.get("schema") == sync.SCHEMA
                     and isinstance(previous.get("approvals"), list)
                     and isinstance(previous.get(contract.KEY, []), list),
                     "invalid prior approval ledger")
    original = copy.deepcopy(previous)
    signed_ids = {row["venueId"] for row in previous.get(contract.KEY, [])}
    seen = set()
    baseline = None
    for proposal in report["proposals"][:4]:
        if not isinstance(proposal, dict):
            continue
        vid = proposal.get("venueId")
        if not isinstance(vid, str) or vid in signed_ids or vid in seen:
            continue
        seen.add(vid)
        result["examined"] += 1
        try:
            row = contract.signed_proposal(proposal, today)
            plan = contract.plan(row, current, today)
            contract.require(not plan["already"], "no new geography change")
            if baseline is None:
                baseline = publisher(reference, current, previous, today)
            before, counts_before = baseline
            # Prior signed corrections, if still pending, must not be
            # overridden or silently counted as the current proposal.
            contract.require(any(v == plan["original"] for v in before["venues"]),
                             "original is changed by another approved operation")
            proposed = copy.deepcopy(previous)
            proposed.setdefault(contract.KEY, []).append(row)
            after, counts_after = publisher(reference, current, proposed, today)
            expected = copy.deepcopy(before)
            expected["venues"] = [
                copy.deepcopy(plan["target"]) if v["id"] == vid else v
                for v in expected["venues"]]
            expected_counts = dict(counts_before)
            expected_counts["correctedVenues"] += 1
            # updatedAt/edition are exclusively publisher-generated metadata.
            ignored = {"updatedAt", "edition"}
            contract.require(
                {k: v for k, v in after.items() if k not in ignored} ==
                {k: v for k, v in expected.items() if k not in ignored}
                and counts_after == expected_counts,
                "publisher did not emit exactly the single geographic correction")
            contract.require(previous == original, "private history mutated")
        except (ValueError, TypeError, KeyError, OSError, TimeoutError):
            result["held"] += 1
            continue
        result["status"] = "validated"
        result["validatedByPublisher"] = True
        result["venueId"] = vid
        return proposed, result
    if result["held"]:
        result["status"] = "held"
    return previous, result


def main():
    parser = argparse.ArgumentParser()
    for name in ("before", "reference", "catalogue", "report"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--slot", type=int, required=True)
    args = parser.parse_args()
    def load(path):
        return json.loads(path.read_text(encoding="utf-8"))
    today = dt.datetime.now(ZoneInfo("Europe/Paris")).date()
    current = load(args.catalogue)
    research = evidence.scan(current, today, slot=args.slot)
    _, report = select(load(args.before), research, load(args.reference), current, today)
    # Shadow only until signed but unapplied evidence can be renewed safely.
    # Do not write approved.json or any public data, even when validated.
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps({"research": research, "preflight": report},
                                      ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print("Private geographic preflight complete; no approval written.")


if __name__ == "__main__":
    main()
