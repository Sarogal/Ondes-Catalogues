#!/usr/bin/env python3
"""Retire only independently repaired, unreferenced historical artist IDs.

This separate private preflight never changes an ordinary event approval or
lineup correction. The real Publisher must independently reproduce the exact
delta, with all unrelated new events, rooms and held decisions preserved.
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
from scripts import concert_retired_artist_identity as retirement
from scripts import concerts_cloud_sync as sync


def select(previous, reference, current, today, *, publisher=sync.merge):
    report = {"status": "no_changes", "eligible": 0, "examined": 0,
              "held": 0, "validatedByPublisher": False, "applied": False}
    original = copy.deepcopy(previous)
    authorized = retirement.selected(previous, today)
    restored, already = retirement.restore(reference, current, previous, today)
    retirement.require(already.issubset(authorized),
                       "historical receipt without private authorization")
    eligible = retirement.candidates(reference, restored, previous, today)
    targets = sorted(set(eligible) - authorized)
    report["eligible"] = len(targets)
    if not targets:
        return previous, report
    # Complete any separately signed retirement first. Do not couple it to
    # a new correction or alter the outcome of a pending event approval.
    if authorized - already:
        report["status"] = "deferred_prior_retirement"
        return previous, report
    try:
        before, before_counts = publisher(reference, current, previous, today)
    except (ValueError, TypeError, KeyError, OSError, TimeoutError):
        report["status"] = "held"
        return previous, report
    for aid in targets[:4]:
        report["examined"] += 1
        try:
            retirement.require(any(a == eligible[aid] for a in before["artists"]),
                               "candidate changed by another operation")
            proposed = copy.deepcopy(previous)
            proposed.setdefault(retirement.LEDGER, []).append({
                "artistId": aid, "reviewDecision": "approved",
                "reviewedBy": retirement.REVIEWER,
                "reviewedAt": today.isoformat(),
            })
            after, after_counts = publisher(reference, current, proposed, today)
            expected = copy.deepcopy(before)
            expected["artists"] = [a for a in expected["artists"] if a["id"] != aid]
            expected[retirement.KEY] = sorted(set(before.get(retirement.KEY, [])) | {aid})
            counts = dict(before_counts)
            counts["retiredArtists"] = counts.get("retiredArtists", 0) + 1
            ignored = {"updatedAt", "edition"}
            retirement.require(
                {k: v for k, v in after.items() if k not in ignored} ==
                {k: v for k, v in expected.items() if k not in ignored}
                and counts == after_counts and previous == original,
                "retirement changes an unrelated approved publication")
        except (ValueError, TypeError, KeyError, OSError, TimeoutError):
            report["held"] += 1
            continue
        report.update(status="validated", validatedByPublisher=True, artistId=aid)
        return proposed, report
    if report["held"]:
        report["status"] = "held"
    return previous, report


def main():
    parser = argparse.ArgumentParser()
    for name in ("before", "reference", "catalogue", "report"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    def load(path):
        return json.loads(path.read_text(encoding="utf-8"))
    today = dt.datetime.now(ZoneInfo("Europe/Paris")).date()
    previous = load(args.before)
    proposed, report = select(previous, load(args.reference), load(args.catalogue), today)
    if args.apply and report["validatedByPublisher"]:
        atomic_store(args.before, proposed)
        report["applied"] = True
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print("Private artist identity retirement preflight complete.")


if __name__ == "__main__":
    main()
