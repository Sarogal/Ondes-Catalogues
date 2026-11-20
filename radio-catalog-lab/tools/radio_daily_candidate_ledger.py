#!/usr/bin/env python3
"""Append-only *candidate evidence* ledger, never a radio publication manifest.

An absent station on one day is not a reason to remove an existing station
(or even its candidate observation). No entry can become automatically approved.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import uuid
from pathlib import Path

MAX_ROWS = 15000
MAX_DAYS = 14


def _uuid(value: object) -> str:
    try:
        if not isinstance(value, str):
            raise ValueError("not a string")
        return str(uuid.UUID(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError("Invalid candidate UUID") from exc


def _day(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Invalid observation date")
    parsed = dt.date.fromisoformat(value)
    if value != parsed.isoformat():
        raise ValueError("Non-canonical observation date")
    return value


def update_ledger(scan: dict, previous: dict | None = None) -> dict:
    if not isinstance(scan, dict) or scan.get("schemaVersion") != 1 or (
        scan.get("publicationAllowed") is not False
    ) or not isinstance(scan.get("candidates"), list):
        raise ValueError("Untrusted or invalid discovery report")
    day = _day(scan.get("scanDate"))
    rows = scan["candidates"]
    if len(rows) > MAX_ROWS:
        raise ValueError("Too many scan rows")
    prior: dict[str, dict] = {}
    if previous is not None:
        if not isinstance(previous, dict) or previous.get("schemaVersion") != 1 or (
            previous.get("publicationAllowed") is not False
        ) or not isinstance(previous.get("records"), list):
            raise ValueError("Invalid preceding candidate ledger")
        if len(previous["records"]) > MAX_ROWS:
            raise ValueError("Previous ledger too large")
        for item in previous["records"]:
            if not isinstance(item, dict):
                raise ValueError("Malformed previous candidate")
            uid = _uuid(item.get("stationuuid"))
            if uid in prior:
                raise ValueError("Duplicate previous UUID")
            prev_last = _day(item.get("lastSeen"))
            prev_first = _day(item.get("firstSeen"))
            days = item.get("seenDays")
            if prev_last > day or prev_first > prev_last or (
                not isinstance(days, int) or isinstance(days, bool) or days < 1
            ):
                raise ValueError("Invalid or future candidate evidence")
            prior[uid] = {
                "stationuuid": uid,
                "firstSeen": prev_first,
                "lastSeen": prev_last,
                "seenDays": days,
                "name": str(item.get("name", ""))[:240],
                "lastStatus": str(item.get("lastStatus", ""))[:60],
                "duplicateRisk": bool(item.get("duplicateRisk", False)),
            }

    observed_ids: set[str] = set()
    reobserved = 0
    fresh = 0
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Malformed candidate")
        uid = _uuid(row.get("stationuuid"))
        if uid in observed_ids:
            raise ValueError("Duplicate UUID in scan")
        observed_ids.add(uid)
        status = str(row.get("status", ""))
        if status not in {
            "candidate_requires_qualification", "needs_stream_check",
            "needs_duplicate_review",
        }:
            raise ValueError("Unexpected candidate status")
        if uid not in prior:
            prior[uid] = {
                "stationuuid": uid, "firstSeen": day, "lastSeen": day,
                "seenDays": 1, "name": str(row.get("name", ""))[:240],
                "lastStatus": status,
                "duplicateRisk": bool(row.get("duplicateIdentityRisk", False)),
            }
            fresh += 1
        else:
            old = prior[uid]
            if old["lastSeen"] != day:
                old["seenDays"] += 1
            old["lastSeen"] = day
            old["lastStatus"] = status
            old["name"] = str(row.get("name", ""))[:240]
            old["duplicateRisk"] = bool(row.get("duplicateIdentityRisk", False))
            reobserved += 1
    if len(prior) > MAX_ROWS:
        raise ValueError("Candidate ledger capacity exceeded; require maintenance")

    # Recurrence only means this UUID was observed on two distinct dates.
    # It is NEVER sufficient to authorize a stream, a logo or publication.
    records = []
    for uid in sorted(prior):
        item = prior[uid].copy()
        item["repeatedObservation"] = (
            item["seenDays"] >= 2
            and item["lastSeen"] == day
            and item["lastStatus"] == "candidate_requires_qualification"
            and not item["duplicateRisk"]
        )
        records.append(item)
    return {
        "schemaVersion": 1,
        "scanDate": day,
        "publicationAllowed": False,
        "automaticallyApprovedCount": 0,
        "newCandidateCount": fresh,
        "reobservedCandidateCount": reobserved,
        "notSeenTodayCount": len(prior) - len(observed_ids),
        "records": records,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scan", type=Path, required=True)
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    scan = json.loads(args.scan.read_text(encoding="utf-8"))
    previous = json.loads(args.previous.read_text(encoding="utf-8")) if args.previous else None
    ledger = update_ledger(scan, previous)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print("RADIO_CANDIDATE_LEDGER_ONLY"
          f" date={ledger['scanDate']} fresh={ledger['newCandidateCount']}"
          f" reobserved={ledger['reobservedCandidateCount']}"
          f" retained_unseen={ledger['notSeenTodayCount']} published=false")
    return 0


if __name__ == "__main__":
    sys.exit(main())
