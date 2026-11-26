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
from automation.concerts.approval_preflight import atomic_store
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
    latest = {row["venueId"]: row for row in previous.get(contract.KEY, [])}
    seen = set()
    baseline = None
    for proposal in report["proposals"][:4]:
        if not isinstance(proposal, dict):
            continue
        vid = proposal.get("venueId")
        if not isinstance(vid, str) or vid in seen:
            continue
        seen.add(vid)
        prior = latest.get(vid)
        # No duplicate attestation on the same day; only renew an unchanged
        # target which still needs publication.
        if prior is not None and prior.get("reviewedAt", "") >= today.isoformat():
            continue
        result["examined"] += 1
        try:
            row = contract.signed_proposal(proposal, today)
            plan = contract.plan(row, current, today)
            contract.require(not plan["already"], "no new geography change")
            if prior is not None:
                old_plan = contract.plan(prior, current, today)
                contract.require(plan["original"] == old_plan["original"]
                                 and plan["target"] == old_plan["target"],
                                 "renewal would alter the signed geographic state")
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
            if prior is not None:
                # The baseline still contains the original venue: its latest
                # attestation was deferred, and this successful renewal
                # removes exactly one deferred item.
                deferred = expected_counts.get("deferredGeoCorrections", 0)
                contract.require(type(deferred) is int and deferred >= 1,
                                 "prior attestation not independently deferred")
                if deferred == 1:
                    del expected_counts["deferredGeoCorrections"]
                else:
                    expected_counts["deferredGeoCorrections"] = deferred - 1
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
        result["renewal"] = prior is not None
        return proposed, result
    if result["held"]:
        result["status"] = "held"
    return previous, result


def main():
    parser = argparse.ArgumentParser()
    for name in ("before", "reference", "catalogue", "report"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--slot", type=int, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    def load(path):
        return json.loads(path.read_text(encoding="utf-8"))
    today = dt.datetime.now(ZoneInfo("Europe/Paris")).date()
    current = load(args.catalogue)
    # The previous private report is scheduling memory only; malformed or
    # absent data must never prevent fresh independent geographic research.
    prior = None
    try:
        saved = load(args.report)
        if isinstance(saved, dict):
            prior = saved.get("research")
    except (OSError, ValueError, TypeError):
        pass
    research = evidence.scan(current, today, slot=args.slot, prior=prior)
    previous = load(args.before)
    proposed, report = select(previous, research, load(args.reference), current, today)
    if args.apply and report["validatedByPublisher"]:
        atomic_store(args.before, proposed)
        report["applied"] = True
    # Never write public data. The separate trusted Publisher replays evidence.
    args.report.parent.mkdir(parents=True, exist_ok=True)
    atomic_store(args.report, {"research": research, "preflight": report})
    print("Private geographic preflight complete; see private report.")


if __name__ == "__main__":
    main()
