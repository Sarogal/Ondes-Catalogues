#!/usr/bin/env python3
"""Bounded private editorial review with independent Publisher exact-delta check."""
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

from automation.concerts import editorial_genre_reconciliation as evidence
from automation.concerts.approval_preflight import atomic_store
from scripts import concert_editorial_exclusion_contract as contract
from scripts import concert_published_lineup_contract as lineup
from scripts import concerts_cloud_sync as sync

MAX_SCAN = 8


def select(previous, reference, current, today, *, slot=0,
           fetch=lineup.network_fetch, publisher=sync.merge):
    report = {"status": "no_changes", "eligible": 0, "examined": 0,
              "held": 0, "validatedByPublisher": False, "applied": False}
    contract.require(previous.get("schema") == sync.SCHEMA
                     and isinstance(previous.get("approvals"), list)
                     and isinstance(previous.get(contract.KEY, []), list),
                     "invalid prior ledger")
    original = copy.deepcopy(previous)
    rows = {a["event"]["id"]: a for a in previous["approvals"]
            if isinstance(a, dict) and isinstance(a.get("event"), dict)
            and isinstance(a["event"].get("id"), str)}
    excluded = {r["originalEvent"]["id"] for r in previous.get(contract.KEY, [])}
    lineup_ids = {r["eventId"] for r in previous.get("lineupCorrections", [])}
    immutable = {e["id"] for e in reference["events"]}
    venues = {v["id"]: v for v in current["venues"]}
    eligible = []
    for event in current["events"]:
        eid = event["id"]
        if (eid in excluded or eid in lineup_ids or eid in immutable
                or eid not in rows or event["date"] < today.isoformat()):
            continue
        venue = venues.get(event["venueId"])
        try:
            evidence.source(rows[eid], event, venue)
        except (ValueError, TypeError, KeyError, AttributeError):
            continue
        eligible.append((event, venue))
    report["eligible"] = len(eligible)
    if not eligible:
        return previous, report
    offset = (today.toordinal() * MAX_SCAN + slot * MAX_SCAN) % len(eligible)
    baseline = None
    for event, venue in (eligible[offset:] + eligible[:offset])[:MAX_SCAN]:
        report["examined"] += 1
        try:
            proof = evidence.verify(rows[event["id"]], event, venue, today, fetch=fetch)
            row = contract.signed_proposal(event, proof)
            contract.plan(row, rows[event["id"]], venue, today)
            if baseline is None:
                baseline = publisher(reference, current, previous, today)
            before, counts_before = baseline
            contract.require(any(e == event for e in before["events"]),
                             "target changed by another operation")
            proposed = copy.deepcopy(previous)
            proposed.setdefault(contract.KEY, []).append(row)
            after, counts_after = publisher(reference, current, proposed, today)
            expected = copy.deepcopy(before)
            expected["events"] = [e for e in expected["events"]
                                  if e["id"] != event["id"]]
            expected.setdefault(contract.RECEIPTS, []).append(
                contract.plan(row, rows[event["id"]], venue, today)["receipt"])
            expected_counts = dict(counts_before)
            expected_counts["editorialExclusions"] = expected_counts.get("editorialExclusions", 0) + 1
            expected_counts.setdefault("deferredEditorialCorrections", 0)
            ignored = {"updatedAt", "edition"}
            contract.require(
                {k: v for k, v in after.items() if k not in ignored} ==
                {k: v for k, v in expected.items() if k not in ignored}
                and counts_after == expected_counts and previous == original,
                "publisher did not emit exactly the proposed editorial exclusion")
        except (ValueError, TypeError, KeyError, OSError, TimeoutError):
            report["held"] += 1
            continue
        report.update(status="validated", validatedByPublisher=True,
                      eventId=event["id"])
        return proposed, report
    if report["held"]:
        report["status"] = "held"
    return previous, report


def main():
    parser = argparse.ArgumentParser()
    for name in ("before", "reference", "catalogue", "report"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--slot", type=int, required=True, choices=(0, 1, 2))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    def load(path):
        return json.loads(path.read_text(encoding="utf-8"))
    today = dt.datetime.now(ZoneInfo("Europe/Paris")).date()
    previous = load(args.before)
    proposed, report = select(previous, load(args.reference), load(args.catalogue),
                              today, slot=args.slot)
    if args.apply and report["validatedByPublisher"]:
        atomic_store(args.before, proposed)
        report["applied"] = True
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print("Private editorial preflight complete; see private report.")


if __name__ == "__main__":
    main()
