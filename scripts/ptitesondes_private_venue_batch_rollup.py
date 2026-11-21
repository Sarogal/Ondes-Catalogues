#!/usr/bin/env python3
"""Fail-closed rollup for disjoint PRIVATE venue research batch reports.

No network, API token, publisher or catalogue reader. Input reports never
leave the caller's private filesystem. Output contains COUNTS ONLY:
no venue names, UIDs, coordinates, source URLs or raw records.
"""
import argparse
from datetime import date
import json
import os
from pathlib import Path
import tempfile

from proof import norm
from ptitesondes_generic_venue_osm_preflight import MAX_PER_RUN, SCHEMA as BATCH_SCHEMA

SCHEMA = "ptitesondes.private_venue_batch_rollup.v1"
MAX_BATCHES = 400
MAX_REPORT_BYTES = 1_000_000


def _natural(value):
    return type(value) is int and value >= 0


def rollup_private_batches(reports):
    if not isinstance(reports, list) or not 1 <= len(reports) <= MAX_BATCHES:
        raise ValueError("invalid_private_batch_collection")
    baseline = reports[0]
    same = ("day", "total_backlog", "unknown_venue_leads",
            "unknown_candidate_sessions", "duplicate_collector_or_repeated_leads",
            "unknown_unique_venues", "batch_count")
    if not isinstance(baseline, dict):
        raise ValueError("invalid_private_batch_schema")
    try:
        day = date.fromisoformat(baseline["day"])
    except (KeyError, ValueError, TypeError):
        raise ValueError("invalid_private_batch_day")
    if day.isoformat() != baseline["day"]:
        raise ValueError("invalid_private_batch_day")
    expected = baseline.get("batch_count")
    total = baseline.get("unknown_unique_venues")
    if (not _natural(total) or total == 0
            or not _natural(expected) or expected !=
            (total + MAX_PER_RUN - 1) // MAX_PER_RUN
            or len(reports) != expected):
        raise ValueError("incomplete_private_batch_set")
    for key in same[1:]:
        if not _natural(baseline.get(key)):
            raise ValueError("invalid_private_batch_totals")
    if baseline["unknown_candidate_sessions"] > baseline["unknown_venue_leads"]:
        raise ValueError("invalid_private_session_count")
    if (baseline["unknown_venue_leads"] -
            baseline["unknown_candidate_sessions"] !=
            baseline["duplicate_collector_or_repeated_leads"]):
        raise ValueError("invalid_private_duplicate_count")
    batches = set()
    venues = set()
    seen_leads = seen_sessions = scanned = hints = proof_places = 0
    proofs_sessions = hinted_sessions = related_sessions = 0
    for report in reports:
        if not isinstance(report, dict) or any(
                report.get(k) != baseline[k] for k in same):
            raise ValueError("incompatible_private_batch")
        if (report.get("schema") != BATCH_SCHEMA
                or report.get("mode") != "private_osm_hints_no_publisher_access"
                or report.get("publication_ready") is not False
                or report.get("gps_verified") is not False
                or report.get("official_venue_verified") is not False
                or report.get("public_writes") != 0
                or report.get("verified_venue_leads") != 0):
            raise ValueError("private_batch_not_read_only")
        i = report.get("batch_index")
        if not _natural(i) or i >= expected or i in batches:
            raise ValueError("private_batch_duplicate_or_out_of_range")
        batches.add(i)
        rows = report.get("records")
        selected = report.get("selected_venues")
        queried = report.get("queried_venues")
        if (not isinstance(rows, list) or not _natural(selected)
                or selected != len(rows)
                or selected != min(MAX_PER_RUN, total - i * MAX_PER_RUN)
                or not _natural(queried) or queried not in (0, selected)):
            raise ValueError("invalid_private_batch_cardinality")
        scanned += queried
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("invalid_private_batch_record")
            city, venue = norm(row.get("city")), norm(row.get("venue"))
            name_key = (city, venue)
            if not city or not venue or name_key in venues:
                raise ValueError("repeated_or_invalid_private_venue")
            venues.add(name_key)
            occurrences = row.get("lead_count")
            sessions = row.get("unique_candidate_sessions")
            if (not _natural(occurrences) or occurrences < 1
                    or not _natural(sessions) or not 1 <= sessions <= occurrences):
                raise ValueError("invalid_private_venue_session_count")
            seen_leads += occurrences
            seen_sessions += sessions
            proof = row.get("shared_location_proof_private_review") is True
            hint = row.get("unnumbered_named_venue_hint", {})
            if not isinstance(hint, dict):
                raise ValueError("invalid_private_unnumbered_hint")
            hinted = (hint.get("official_name_correlated") is True
                      and hint.get("osm_geometry_correlated") is True)
            for details in (hint, row.get("official_page", {}),
                            row.get("official_geocode", {})):
                if (not isinstance(details, dict)
                        or details.get("publication_ready") is True
                        or details.get("public_writes", 0) != 0):
                    raise ValueError("private_evidence_contains_public_write")
            if proof:
                proof_places += 1
                proofs_sessions += sessions
            if hinted:
                hints += 1
                hinted_sessions += sessions
            if proof or hinted:
                related_sessions += sessions
        if (report.get("private_reusable_location_proofs") != sum(
                1 for row in rows
                if row.get("shared_location_proof_private_review") is True)
                or report.get("candidate_sessions_with_private_reusable_proof")
                != sum(row["unique_candidate_sessions"] for row in rows
                       if row.get("shared_location_proof_private_review") is True)
                or report.get("unnumbered_named_venue_private_hints")
                != sum(1 for row in rows
                       if isinstance(row.get("unnumbered_named_venue_hint"),dict)
                       and row["unnumbered_named_venue_hint"].get(
                           "official_name_correlated") is True
                       and row["unnumbered_named_venue_hint"].get(
                           "osm_geometry_correlated") is True)
                or report.get("candidate_sessions_with_unnumbered_private_hint")
                != sum(row["unique_candidate_sessions"] for row in rows
                       if isinstance(row.get("unnumbered_named_venue_hint"),dict)
                       and row["unnumbered_named_venue_hint"].get(
                           "official_name_correlated") is True
                       and row["unnumbered_named_venue_hint"].get(
                           "osm_geometry_correlated") is True)):
            raise ValueError("inconsistent_private_evidence_counters")
    if (len(batches) != expected or len(venues) != total
            or seen_leads != baseline["unknown_venue_leads"]
            or seen_sessions != baseline["unknown_candidate_sessions"]):
        raise ValueError("private_batch_coverage_or_totals_mismatch")
    return {
        "schema": SCHEMA, "day": day.isoformat(),
        "mode": "private_only_counts_without_publication_attestation",
        "total_backlog_entries": baseline["total_backlog"],
        "unknown_venue_entries": seen_leads,
        "unknown_distinct_candidate_sessions": seen_sessions,
        "duplicate_or_repeated_entries": seen_leads - seen_sessions,
        "unknown_unique_venues": len(venues),
        "batches_complete": True, "batches_examined": len(batches),
        "live_venues_queried": scanned,
        "full_live_scan": scanned == len(venues),
        "reusable_location_proof_venues_private": proof_places,
        "candidate_sessions_on_proven_places_not_published": proofs_sessions,
        "unnumbered_named_venue_hints_private": hints,
        "candidate_sessions_on_unnumbered_hints_not_published": hinted_sessions,
        "candidate_sessions_with_any_geo_signal_not_published": related_sessions,
        "gps_verified_for_publisher": False,
        "event_sessions_verified": False,
        "publication_ready": False, "public_writes": 0,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reports", nargs="+", type=Path, required=True)
    parser.add_argument("--output-private-summary", type=Path, required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    target = args.output_private_summary
    # The generated summary must not be written into the public checkout.
    if (target.resolve().is_relative_to(repo) or
            not target.parent.is_dir() or target.parent.is_symlink()):
        raise ValueError("private_summary_path_invalid")
    reports = []
    for path in args.reports:
        if (path.resolve().is_relative_to(repo) or
                path.is_symlink() or not path.is_file()
                or path.stat().st_size > MAX_REPORT_BYTES):
            raise ValueError("private_report_path_invalid")
        reports.append(json.loads(path.read_text(encoding="utf-8")))
    summary = rollup_private_batches(reports)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
                "w", dir=target.parent, prefix=".ptitesondes-summary-",
                suffix=".tmp", encoding="utf-8", delete=False) as out:
            temp_path = Path(out.name)
            json.dump(summary, out, ensure_ascii=False, indent=2)
            out.write("\n")
        os.replace(temp_path, target)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()
    # Counts only; never a venue name, UID, coordinate, URI or input path.
    print(json.dumps({
        "batches_complete": summary["batches_complete"],
        "unknown_unique_venues": summary["unknown_unique_venues"],
        "unknown_distinct_candidate_sessions":
            summary["unknown_distinct_candidate_sessions"],
        "full_live_scan": summary["full_live_scan"],
        "publication_ready": False, "public_writes": 0,
    }))


if __name__ == "__main__":
    main()
