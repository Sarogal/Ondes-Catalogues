"""Append-only municipal synchronization REHEARSAL, never a publisher.

The isolated #334 batch validator authenticates private human decisions
against live municipal evidence; this module models a possible future
municipal-only merge IN MEMORY on a copy of the current catalogue.

Not installed in merge_policy, not a patch writer, no file/network writes.
It intentionally cannot generate or return event rows, additions, a patch,
a modified catalogue, or trusted verification timestamps. A real public
release needs a distinct, reviewed publisher and independently attested
source/GPS verification dates bound to the private approval manifest.
"""
from copy import deepcopy
from datetime import date

from merge_policy import byid, valid
from ptitesondes_municipal_batch_readiness import (
    _record_identity, inspect_municipal_batch,
)
from ptitesondes_municipal_admission import (
    explicit_municipal_category_valid, read_official, github_read,
    verified_location,
)
from ptitesondes_municipal_appendonly_dryrun import (
    _event_from_proposal, _overlaps_publication, canonical_sha256,
)

SCHEMA = "ptitesondes.municipal_sync_rehearsal.v1"
MAX_AGE_DAYS = 14


def _fresh_planning_stamps(stamps, today):
    """Dates are planning inputs only; NOT independent signed GPS/source proof."""
    if not isinstance(stamps, dict) or set(stamps) != {
        "source_checked_on", "geo_checked_on",
    }:
        return False
    for value in stamps.values():
        if not isinstance(value, str):
            return False
        try:
            d = date.fromisoformat(value)
        except (TypeError, ValueError):
            return False
        if d.isoformat() != value or not 0 <= (today - d).days <= MAX_AGE_DAYS:
            return False
    return True


def simulate_municipal_sync(
    reference, current, dossiers, today, *, reference_sha256,
    current_sha256, planning_stamps=None, token=None,
    source_get=read_official, github_get=github_read,
    geo_check=verified_location,
):
    """All-or-nothing, in-memory QA; return only non-sensitive aggregates.

    The planning date map is NEVER treated as a real release attestation.
    Even success here always means publication_ready=False and public_writes=0.
    """
    if type(today) is not date:
        raise ValueError("invalid_simulation_day")
    before_ref = deepcopy(reference)
    before_current = deepcopy(current)
    # This call REEXECUTES official HTML checks, private authenticated decision
    # checks, location registry, cross-source duplicates and catalogue pins.
    report = inspect_municipal_batch(
        reference, current, dossiers, today,
        reference_sha256=reference_sha256,
        current_sha256=current_sha256,
        token=token, source_get=source_get,
        github_get=github_get, geo_check=geo_check,
    )
    expected = len(dossiers)
    guards = []
    if (report.get("schema") != "ptitesondes.municipal_batch_readiness.v1"
            or report.get("publisher_wired") is not False
            or report.get("publication_ready") is not False
            or report.get("approval_granted_to_publisher") is not False
            or report.get("public_writes") != 0):
        raise ValueError("upstream_batch_not_readonly")
    if (report.get("input_dossiers") != expected
            or report.get("isolated_diagnostic_passes") != expected
            or report.get("blocked_occurrences") != 0):
        guards.append("batch_evidence_or_approval_incomplete")
    if (not isinstance(planning_stamps, dict)
            or len(planning_stamps) != expected):
        guards.append("missing_planning_verification_dates")

    if not guards:
        copy_doc = deepcopy(current)
        current_ix = byid(current)
        reference_ix = byid(reference)
        seen_ids = set(current_ix)
        fields = set().union(*(set(row) for row in reference_ix.values()))
        historical_categories = {
            item.get("category") for item in reference["events"]
        }
        for dossier in dossiers:
            candidate = _record_identity(dossier)
            rid = candidate["review_id"]
            stamps = planning_stamps.get(rid)
            if not _fresh_planning_stamps(stamps, today):
                guards.append("missing_or_stale_planning_stamp")
                break
            event = _event_from_proposal(
                candidate, stamps["source_checked_on"], stamps["geo_checked_on"]
            )
            # Neither new categories nor municipal origin are installed in
            # current merge_policy: a direct production call MUST reject.
            real_ok, reason = valid(event, historical_categories, fields, today)
            if real_ok or reason != "catégorie inconnue":
                guards.append("production_category_boundary_changed")
                break
            model_ok, reason = explicit_municipal_category_valid(
                event, reference, today
            )
            if not model_ok:
                guards.append("municipal_explicit_schema_rejected")
                break
            if rid in seen_ids or _overlaps_publication(
                event, copy_doc["events"]
            ):
                guards.append("duplicate_already_staged_or_published")
                break
            # NO modifications to current: this copy never leaves this scope.
            copy_doc["events"].append(event)
            seen_ids.add(rid)
        if not guards:
            if (copy_doc["events"][:len(current["events"])]
                    != current["events"]):
                raise ValueError("in_memory_historical_prefix_changed")
            if copy_doc["updated_at"] != current["updated_at"]:
                raise ValueError("simulation_timestamp_changed")
            if len(copy_doc["events"]) != len(current["events"]) + expected:
                raise ValueError("simulation_addition_count_mismatch")

    if (before_ref != reference or before_current != current
            or canonical_sha256(reference) != reference_sha256
            or canonical_sha256(current) != current_sha256):
        raise ValueError("source_catalogue_mutated")
    # All-or-nothing: never present a partial model as ready.
    hypothetical = expected if not guards else 0
    return {
        "schema": SCHEMA,
        "mode": "in_memory_all_or_nothing_no_patch_no_publication",
        "reference_sha256": reference_sha256,
        "current_sha256": current_sha256,
        "historical_prefix_unchanged": True,
        "current_catalogue_unchanged": True,
        "reference_events_preserved": len(reference["events"]),
        "current_events_preserved": len(current["events"]),
        "input_dossiers": expected,
        "hypothetical_in_memory_additions": hypothetical,
        "hypothetical_in_memory_total": len(current["events"]) + hypothetical,
        "batch_readiness_confirmed": not (
            "batch_evidence_or_approval_incomplete" in guards
        ),
        "simulation_blockers": sorted(set(guards)),
        "planning_stamps_are_not_signed_proof": True,
        "requires_independent_source_and_gps_attestation": True,
        "production_category_policy_unchanged": True,
        "municipal_publisher_not_connected": True,
        "publication_ready": False,
        "approval_granted_to_publisher": False,
        "historical_records_modified": 0,
        "historical_records_deleted": 0,
        "public_writes": 0,
    }
