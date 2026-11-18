#!/usr/bin/env python3
"""Strict, private-only persistence gate for the aggregated OA v2 agenda census.

Do not persist a case file, agenda UID, slug, URL, title, response, exception
or credential. Only a hard-coded schema with numeric counters can be stored.
This is DIAGNOSTIC ONLY: never signs or publishes an event.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

SCHEMA = "ptitesondes.oa2.agenda_census.v1"
MODE = "manual_oa2_identity_inventory_not_owner_attestation"
COUNTERS = {
    "api_identity_mismatch",
    "api_identity_concordant",
    "api_official_indicator_only",
    "api_self_declared_external_reference",
    "api_private_or_restricted",
    "api_unavailable_or_unverified",
}
BASE = {
    "schema", "mode", "configured_agendas", "counts",
    "independently_confirmed_owners", "organizer_sessions_attested",
    "licences_reviewed", "publisher_connected", "approval_granted",
    "public_writes", "contains_identifiers_or_private_candidate_data",
}
MAX_SIZE = 4000


def guarded(report):
    if not isinstance(report, dict) or set(report) != BASE:
        raise ValueError("Unexpected census fields")
    if report.get("schema") != SCHEMA or report.get("mode") != MODE:
        raise ValueError("Unexpected census identity or status")
    count = report.get("configured_agendas")
    if type(count) is not int or not 1 <= count <= 100:
        raise ValueError("Invalid source count")
    values = report.get("counts")
    if (not isinstance(values, dict) or set(values) - COUNTERS
            or any(type(v) is not int or v < 0 or v > count
                   for v in values.values())):
        raise ValueError("Invalid or unbounded counter")
    # Every configured agenda gets exactly one exclusive identity outcome.
    identity = sum(values.get(k, 0) for k in (
        "api_identity_mismatch", "api_identity_concordant",
        "api_unavailable_or_unverified",
    ))
    if identity != count:
        raise ValueError("Incomplete or doubled identity inventory")
    good = values.get("api_identity_concordant", 0)
    for k in ("api_official_indicator_only", "api_self_declared_external_reference",
              "api_private_or_restricted"):
        if values.get(k, 0) > good:
            raise ValueError("Optional count exceeds concordant identities")
    for k in ("independently_confirmed_owners", "organizer_sessions_attested",
              "licences_reviewed", "public_writes"):
        if type(report.get(k)) is not int or report[k] != 0:
            raise ValueError("A census cannot attest event publication")
    for k in ("publisher_connected", "approval_granted",
              "contains_identifiers_or_private_candidate_data"):
        if report.get(k) is not False:
            raise ValueError("Census contains forbidden publication authority")
    # Canonical defensive copy; reject unexpected nested types and metadata.
    return {
        "schema": SCHEMA, "mode": MODE, "configured_agendas": count,
        "counts": {k: values[k] for k in sorted(values)},
        "independently_confirmed_owners": 0,
        "organizer_sessions_attested": 0,
        "licences_reviewed": 0, "publisher_connected": False,
        "approval_granted": False, "public_writes": 0,
        "contains_identifiers_or_private_candidate_data": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        if not 0 < args.input.stat().st_size <= MAX_SIZE:
            raise ValueError("Oversized census")
        data = json.loads(args.input.read_text(encoding="utf-8"))
        safe = guarded(data)
        # Even a configured source cannot smuggle arbitrary metadata.
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(safe, sort_keys=True,
                                          ensure_ascii=True, indent=2) + "\n",
                               encoding="utf-8")
    except (OSError, UnicodeError, TypeError, ValueError):
        raise SystemExit("Census private report rejected without storing source data") from None
    print("PRIVATE_OA2_CENSUS: redacted counters only; no approval or publication")


if __name__ == "__main__":
    main()
