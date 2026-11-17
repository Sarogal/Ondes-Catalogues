"""Read-only, all-or-nothing municipal batch ATTESTATION + sync rehearsal.

Stacks #337 (owner/source/geo receipt), #335 (in-memory dry-run),
#334 (batch/duplicate gate) and #332 (single private approval).
It is NEVER a publisher. No collector-declared source/GPS dates qualify as
independent evidence; #335's dates below are only artificial model inputs.
The external GPS provider is NOT re-fetched by #337.
"""
from collections import Counter
from copy import deepcopy
from datetime import date

from ptitesondes_municipal_appendonly_dryrun import canonical_sha256
from ptitesondes_municipal_batch_readiness import (
    MAX_OCCURRENCES, _pinned_catalogues, _record_identity,
    inspect_municipal_batch,
)
from ptitesondes_municipal_source_geo_attestation import (
    SCHEMA as ATTESTATION_SCHEMA, inspect_source_geo_attestation,
)
from ptitesondes_municipal_sync_rehearsal import (
    SCHEMA as REHEARSAL_SCHEMA, simulate_municipal_sync,
)
from ptitesondes_municipal_admission import (
    read_official, github_read, verified_location,
)

SCHEMA = "ptitesondes.municipal_attested_batch_rehearsal.v1"
_FIELDS = frozenset({"review", "access", "manifest", "receipt"})
_FORBIDDEN = frozenset({
    "events", "additions", "patch", "patch.v1", "updated_catalogue",
    "catalogue", "publication_payload", "approved_events",
})


def inspect_attested_municipal_sync(
    reference, current, bundles, today, *, reference_sha256,
    current_sha256, token=None, source_get=read_official,
    github_get=github_read, geo_check=verified_location,
    registry=None, now=None,
):
    """Recheck the exact pinned snapshot; return only aggregated diagnostics.

    Every bundle is an individual private review + access decision + manifest
    + owner-attested receipt. No partial result can reach the modelled sync.
    Receipt validation is executed against the CURRENT catalogue, not an old
    reference or a previously computed attestation boolean.
    """
    if type(today) is not date:
        raise ValueError("invalid_attested_batch_day")
    if (not isinstance(bundles, list)
            or not 1 <= len(bundles) <= MAX_OCCURRENCES):
        raise ValueError("invalid_attested_batch_size")
    reference_before, current_before = deepcopy(reference), deepcopy(current)
    # Validates the two SHA pins, unique catalogue IDs, and exact historical
    # prefix before performing any source or private API requests.
    _pinned_catalogues(reference, current, reference_sha256, current_sha256)

    dossiers, receipts, candidates = [], [], []
    for bundle in bundles:
        if not isinstance(bundle, dict) or set(bundle) != _FIELDS:
            raise ValueError("invalid_attested_bundle_structure")
        dossier = {field: bundle[field] for field in (
            "review", "access", "manifest"
        )}
        candidate = _record_identity(dossier)
        dossiers.append(dossier)
        receipts.append(bundle["receipt"])
        candidates.append(candidate)

    def assert_unchanged():
        if (reference != reference_before or current != current_before
                or canonical_sha256(reference) != reference_sha256
                or canonical_sha256(current) != current_sha256):
            raise ValueError("attested_rehearsal_catalogue_mutated")

    # #334 always runs first, reexecuting #332, official and private checks
    # against ONE pinned current snapshot. Any failed item blocks the lot.
    batch = inspect_municipal_batch(
        reference, current, dossiers, today,
        reference_sha256=reference_sha256, current_sha256=current_sha256,
        token=token, source_get=source_get, github_get=github_get,
        geo_check=geo_check,
    )
    assert_unchanged()
    if (batch.get("schema") != "ptitesondes.municipal_batch_readiness.v1"
            or batch.get("publication_ready") is not False
            or batch.get("approval_granted_to_publisher") is not False
            or batch.get("public_writes") != 0
            or batch.get("publisher_wired") is not False
            or batch.get("catalogues_unchanged") is not True
            or batch.get("reference_sha256") != reference_sha256
            or batch.get("current_sha256") != current_sha256):
        raise ValueError("untrusted_upstream_batch_contract")

    blocked = set()
    reasons = Counter()
    n = len(dossiers)
    batch_passed = (
        batch.get("input_dossiers") == n
        and batch.get("isolated_diagnostic_passes") == n
        and batch.get("blocked_occurrences") == 0
    )
    if not batch_passed:
        blocked.add("municipal_batch_incomplete")
        for reason, count in (batch.get("blocked_reason_counts") or {}).items():
            if isinstance(reason, str) and type(count) is int and count > 0:
                reasons[reason] += count

    attested = False
    if batch_passed:
        all_attested = True
        # Inspect EVERY occurrence; don't rely on a single lot-level receipt,
        # a cached true flag, or a collector's claim of verified timestamps.
        for dossier, receipt in zip(dossiers, receipts):
            try:
                result = inspect_source_geo_attestation(
                    current, dossier["review"], dossier["access"],
                    dossier["manifest"], receipt, today,
                    token=token, source_get=source_get,
                    github_get=github_get, geo_check=geo_check,
                    registry=registry, now=now,
                )
                safe = (
                    result.get("schema") == ATTESTATION_SCHEMA
                    and result.get("authenticated_private_attestation_passed")
                    is True
                    and result.get("blockers") == []
                    and result.get("publication_ready") is False
                    and result.get("approval_granted_to_publisher") is False
                    and result.get("public_writes") == 0
                    and result.get("historical_records_modified") == 0
                    and result.get("historical_records_deleted") == 0
                    and result.get("geo_provider_not_refetched") is True
                )
                if not safe:
                    all_attested = False
                    for reason in result.get("blockers") or [
                        "attestation_contract_refused"
                    ]:
                        if isinstance(reason, str):
                            reasons[reason] += 1
            except (KeyError, TypeError, ValueError, OSError, UnicodeError):
                all_attested = False
                reasons["private_attestation_unverifiable"] += 1
            assert_unchanged()
        attested = all_attested
        if not all_attested:
            blocked.add("one_or_more_private_attestations_invalid")

    hypothetical = 0
    rehearsal_passed = False
    if batch_passed and attested:
        # Planning placeholders required by #335 for a model run; generated
        # internally, NOT accepted from a collector or used as official proof.
        # Release requires a separate fresh geo-provider verification.
        model_stamps = {
            candidate["review_id"]: {
                "source_checked_on": today.isoformat(),
                "geo_checked_on": today.isoformat(),
            }
            for candidate in candidates
        }
        try:
            model = simulate_municipal_sync(
                reference, current, dossiers, today,
                reference_sha256=reference_sha256,
                current_sha256=current_sha256,
                planning_stamps=model_stamps, token=token,
                source_get=source_get, github_get=github_get,
                geo_check=geo_check,
            )
            safe_model = (
                model.get("schema") == REHEARSAL_SCHEMA
                and model.get("simulation_blockers") == []
                and model.get("batch_readiness_confirmed") is True
                and model.get("hypothetical_in_memory_additions") == n
                and model.get("historical_prefix_unchanged") is True
                and model.get("current_catalogue_unchanged") is True
                and model.get("production_category_policy_unchanged") is True
                and model.get("planning_stamps_are_not_signed_proof") is True
                and model.get("publication_ready") is False
                and model.get("approval_granted_to_publisher") is False
                and model.get("public_writes") == 0
            )
            if safe_model and not (_FORBIDDEN & set(model)):
                rehearsal_passed = True
                hypothetical = n
            else:
                blocked.add("in_memory_rehearsal_refused")
                reasons.update({
                    item: 1 for item in model.get("simulation_blockers", [])
                    if isinstance(item, str)
                })
        except (KeyError, TypeError, ValueError, OSError, UnicodeError):
            blocked.add("in_memory_rehearsal_unverifiable")
        assert_unchanged()

    assert_unchanged()
    if not rehearsal_passed:
        hypothetical = 0
    return {
        "schema": SCHEMA,
        "mode": "isolated_all_or_nothing_attested_diagnostic_only",
        "reference_sha256": reference_sha256,
        "current_sha256": current_sha256,
        "reference_events_preserved": len(reference["events"]),
        "current_events_preserved": len(current["events"]),
        "input_dossiers": n,
        "municipal_batch_passed": batch_passed,
        "all_private_source_geo_attestations_passed": attested,
        "in_memory_rehearsal_passed": rehearsal_passed,
        "hypothetical_in_memory_additions": hypothetical,
        "simulation_blockers": sorted(blocked),
        "blocked_reason_counts": dict(sorted(reasons.items())),
        "historical_prefix_unchanged": True,
        "catalogues_unchanged": True,
        "planning_dates_are_not_evidence": True,
        "gps_provider_not_refetched": True,
        "owner_comment_sha256_is_not_a_digital_signature": True,
        "production_category_policy_unchanged": True,
        "municipal_publisher_not_connected": True,
        "publication_ready": False,
        "approval_granted_to_publisher": False,
        "historical_records_modified": 0,
        "historical_records_deleted": 0,
        "public_writes": 0,
    }
