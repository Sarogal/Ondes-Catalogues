"""Municipal multi-occurrence reconciliation, strictly offline from the publisher.

This orchestrates the already-reviewed #332 single-occurrence independent
preflight and authenticated private approval. It never accepts a report's
`approved` or `technical_admission_diagnostic_passed` fields as input.

NO patch.v1, no `additions`, no resulting public catalogue and NO write path.
"""
from collections import Counter
from copy import deepcopy
from datetime import date
import re

from merge_policy import byid
from ptitesondes_municipal_admission import (
    inspect_municipal_admission, read_official, github_read, verified_location,
)
from ptitesondes_municipal_appendonly_dryrun import (
    _event_from_proposal, _overlaps_publication, canonical_sha256,
)

SCHEMA = "ptitesondes.municipal_batch_readiness.v1"
SHA256 = re.compile(r"[a-f0-9]{64}\Z")
MAX_OCCURRENCES = 100


def _pinned_catalogues(reference, current, reference_sha256, current_sha256):
    """Two independently supplied immutable SHA pins, not collector hints."""
    if (not isinstance(reference_sha256, str)
            or not SHA256.fullmatch(reference_sha256)
            or not isinstance(current_sha256, str)
            or not SHA256.fullmatch(current_sha256)):
        raise ValueError("missing_catalogue_sha_pins")
    ref_idx, cur_idx = byid(reference), byid(current)
    if (canonical_sha256(reference) != reference_sha256
            or canonical_sha256(current) != current_sha256):
        raise ValueError("catalogue_changed_since_private_review")
    if len(cur_idx) < len(ref_idx) or any(
        key not in cur_idx or cur_idx[key] != before
        for key, before in ref_idx.items()
    ):
        raise ValueError("historical_catalogue_modified_or_deleted")
    # New published events may legitimately be present. Every private review
    # must explicitly bind to the current pinned snapshot, NOT the old one.
    return len(ref_idx), len(cur_idx)


def _record_identity(dossier):
    if not isinstance(dossier, dict) or set(dossier) != {
        "review", "access", "manifest",
    }:
        raise ValueError("invalid_municipal_batch_item")
    review = dossier["review"]
    access = dossier["access"]
    manifest = dossier["manifest"]
    if (not isinstance(review, dict)
            or not isinstance(access, dict)
            or not isinstance(manifest, dict)
            or not isinstance(review.get("candidates"), list)
            or len(review["candidates"]) != 1
            or not isinstance(access.get("reviewed"), list)
            or len(access["reviewed"]) != 1):
        raise ValueError("malformed_municipal_batch_item")
    candidate = review["candidates"][0]
    condition = access["reviewed"][0]
    if not isinstance(candidate, dict) or not isinstance(condition, dict):
        raise ValueError("invalid_municipal_batch_candidate")
    rid = candidate.get("review_id")
    if (not isinstance(rid, str)
            or rid != manifest.get("review_id")
            or rid != condition.get("review_id")):
        raise ValueError("cross_dossier_identity_mismatch")
    return candidate


def inspect_municipal_batch(
    reference, current, dossiers, today, *,
    reference_sha256, current_sha256, token=None,
    source_get=read_official, github_get=github_read,
    geo_check=verified_location,
):
    """Inspect a bounded batch; return ONLY aggregate counters.

    One shared current catalogue snapshot is used for all approvals. Any
    newer publication or modified evidence requires a NEW authenticated
    review; this function cannot reauthorize an older snapshot.
    """
    if type(today) is not date:
        raise ValueError("invalid_batch_day")
    if (not isinstance(dossiers, list)
            or not 1 <= len(dossiers) <= MAX_OCCURRENCES):
        raise ValueError("invalid_batch_size")
    original_reference = deepcopy(reference)
    original_current = deepcopy(current)
    initial_ref, initial_current = _pinned_catalogues(
        reference, current, reference_sha256, current_sha256,
    )
    seen_ids = set()
    proposed_in_this_batch = []
    reason_counts = Counter()
    accepted_in_isolated_diagnostic = 0
    reviewed = 0

    for dossier in dossiers:
        candidate = _record_identity(dossier)
        rid = candidate["review_id"]
        if rid in seen_ids:
            # Duplicate dossier must not manufacture two admissions.
            reason_counts["duplicate_batch_review_id"] += 1
            continue
        seen_ids.add(rid)
        reviewed += 1
        reasons = set()
        try:
            preview = _event_from_proposal(
                candidate, today.isoformat(), today.isoformat(),
            )
            if (_overlaps_publication(preview, proposed_in_this_batch)
                    or _overlaps_publication(preview, current["events"])):
                reasons.add("duplicate_occurrence_within_batch_or_catalogue")
            # Keep a proposed identity for EACH candidate, even when it later
            # fails evidence/approval: don't promote a colliding second one.
            proposed_in_this_batch.append(preview)
        except (KeyError, TypeError, ValueError, OverflowError):
            reasons.add("invalid_candidate_projection")

        try:
            result = inspect_municipal_admission(
                current, dossier["review"], dossier["access"],
                dossier["manifest"], today, token=token,
                source_get=source_get, github_get=github_get,
                geo_check=geo_check,
            )
            if result.get("schema") != (
                "ptitesondes.municipal_admission_diagnostic.v1"
            ):
                reasons.add("unexpected_municipal_admission_contract")
            if result.get("catalogue_sha256") != current_sha256:
                reasons.add("admission_catalogue_not_pinned")
            if result.get("technical_admission_diagnostic_passed") is not True:
                reasons.update(result.get("blockers") or
                               ["single_occurrence_admission_unverified"])
            if (result.get("historical_unchanged") is not True
                    or result.get("publication_ready") is not False
                    or result.get("public_writes") != 0
                    or result.get("approval_granted_to_publisher") is not False):
                reasons.add("single_occurrence_output_not_readonly")
        except (ValueError, TypeError, KeyError, OSError, UnicodeError):
            reasons.add("unverifiable_municipal_dossier")

        if not reasons:
            accepted_in_isolated_diagnostic += 1
        else:
            reason_counts.update(sorted(reasons))

        # Detect any accidental or malicious mutation at each iteration.
        if (reference != original_reference or current != original_current
                or canonical_sha256(reference) != reference_sha256
                or canonical_sha256(current) != current_sha256):
            raise ValueError("catalogue_mutated_during_batch")

    if reference != original_reference or current != original_current:
        raise ValueError("catalogue_mutated_during_batch")
    return {
        "schema": SCHEMA,
        "mode": "batch_readonly_diagnostic_never_publish",
        "reference_sha256": reference_sha256,
        "current_sha256": current_sha256,
        "reference_historical_preserved": initial_ref,
        "current_historical_preserved": initial_current,
        "reviewed_unique_occurrences": reviewed,
        "input_dossiers": len(dossiers),
        "isolated_diagnostic_passes": accepted_in_isolated_diagnostic,
        "blocked_occurrences": len(dossiers) - accepted_in_isolated_diagnostic,
        "blocked_reason_counts": dict(sorted(reason_counts.items())),
        "catalogues_unchanged": True,
        "historical_records_modified": 0,
        "historical_records_deleted": 0,
        "public_writes": 0,
        "publisher_wired": False,
        "publication_ready": False,
        "approval_granted_to_publisher": False,
    }
