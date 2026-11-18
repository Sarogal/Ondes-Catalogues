"""Joined OpenAgenda v2 + institutional GPS + first-party session DIAGNOSTIC.

The caller obtains independently reviewed venue and organizer pins OUTSIDE the
candidate and OpenAgenda payload, then fetches their exact pages without a
redirect. This pure module never promotes a source, decides reuse rights,
bypasses historical deduplication, emits a patch or contacts a publisher.

A structurally verified candidate is *not* an approved candidate.
"""
from collections import Counter
from datetime import date

from ptitesondes_openagenda_v2_geo_bridge import review_independent_geo
from ptitesondes_openagenda_v2_direct_evidence import review_direct_v2
from ptitesondes_openagenda_v2_organizer_bridge import check_independent_session
from ptitesondes_openagenda_v2_structured_organizer import (
    check_structured_organizer_session,
)

SCHEMA = "ptitesondes.oa2.joined_independent_evidence.v1"
BATCH_SCHEMA = "ptitesondes.oa2.joined_independent_evidence_batch.v1"
MAX_BATCH = 60
REQUIRED_CASE = frozenset({
    "lead", "api_event", "reviewed_agenda",
    "reviewed_venue_source", "venue_page",
    "geocoder_request_url", "geojson",
    "reviewed_organizer", "organizer_page",
})
# These gates are deliberately NOT inferred from a source or from API flags.
REMAINING_GATES = (
    "organizer_ownership",
    "reuse_rights",
    "age_and_access",
    "historic_deduplication",
    "editorial_category",
    "final_private_approval",
    "publisher_and_site_visibility",
)
SAFE_STAGES = (
    "invalid_case",
    "independent_venue_not_verified",
    "openagenda_identity_or_sessions_not_verified",
    "multi_day_grouping_required",
    "organizer_session_not_confirmed",
    "family_audience_not_independently_confirmed",
    "structural_evidence_complete_other_gates_pending",
)


def diagnose_candidate(case, today):
    """One UID/day candidate, reviewed pins supplied by a separate authority.

    The caller must never derive reviewed_* from lead, OpenAgenda, ODS,
    search snippets, or collected source metadata. The result intentionally
    excludes candidate identifiers, URLs, coordinates and raw reason strings.
    """
    base = {
        "schema": SCHEMA,
        "stage": "invalid_case",
        "venue_verified": False,
        "openagenda_direct_verified": False,
        "organizer_session_verified": False,
        "family_audience_confirmed": False,
        "source_evidence_structurally_complete": False,
        "outstanding_gates": list(REMAINING_GATES),
        "approval_granted": False,
        "publisher_connected": False,
        "public_writes": 0,
    }
    if (type(today) is not date or not isinstance(case, dict)
            or set(case) != REQUIRED_CASE
            or not all(isinstance(case.get(key), dict) for key in (
                "lead", "api_event", "reviewed_agenda",
                "reviewed_venue_source", "venue_page",
                "geojson", "reviewed_organizer", "organizer_page"))
            or not isinstance(case["geocoder_request_url"], str)):
        return base
    try:
        geo = review_independent_geo(
            case["lead"], case["api_event"], case["reviewed_venue_source"],
            case["venue_page"], case["geocoder_request_url"], case["geojson"])
        if geo.get("geo_evidence_consistent") is not True:
            return dict(base, stage="independent_venue_not_verified")
        direct = review_direct_v2(
            case["lead"], case["api_event"], case["reviewed_agenda"],
            geo["registered_venue"], today)
        if direct.get("source_evidence_structurally_valid") is not True:
            return dict(base, stage="openagenda_identity_or_sessions_not_verified",
                        venue_verified=True)
        if direct.get("event_kind") != "single_explicit_dated_occurrence":
            return dict(base, stage="multi_day_grouping_required",
                        venue_verified=True, openagenda_direct_verified=True)
        text = check_independent_session(
            case["lead"], case["api_event"], direct,
            case["reviewed_organizer"], case["organizer_page"])
        structured = check_structured_organizer_session(
            case["lead"], case["api_event"], direct,
            case["reviewed_organizer"], case["organizer_page"])
        if (text.get("official_session_evidence_consistent") is not True
                and structured.get("official_structured_sessions_concordant") is not True):
            return dict(base, stage="organizer_session_not_confirmed",
                        venue_verified=True, openagenda_direct_verified=True)
        if (direct.get("api_family_audience_confirmed") is not True
                and text.get("official_session_evidence_consistent") is not True
                and structured.get("official_structured_sessions_concordant") is not True):
            return dict(base, stage="family_audience_not_independently_confirmed",
                        venue_verified=True, openagenda_direct_verified=True,
                        organizer_session_verified=True)
        return dict(
            base, stage="structural_evidence_complete_other_gates_pending",
            venue_verified=True, openagenda_direct_verified=True,
            organizer_session_verified=True, family_audience_confirmed=True,
            source_evidence_structurally_complete=True)
    except (Exception):
        # No raw exception details: these often include private URLs or data.
        return base


def diagnose_batch(cases, today):
    """Bounded, anonymized aggregate only. No per-lead results leave this API."""
    if type(today) is not date or not isinstance(cases, list) or not 1 <= len(cases) <= MAX_BATCH:
        raise ValueError("invalid_joined_evidence_batch")
    reasons = Counter()
    for case in cases:
        stage = diagnose_candidate(case, today)["stage"]
        reasons[stage if stage in SAFE_STAGES else "invalid_case"] += 1
    return {
        "schema": BATCH_SCHEMA,
        "mode": "read_only_no_publication",
        "checked_leads": len(cases),
        "reason_counts": dict(sorted(reasons.items())),
        "contains_candidate_identifiers": False,
        "approval_granted": False,
        "publisher_connected": False,
        "public_writes": 0,
        "rights_reviewed": False,
        "historical_deduplication_checked": False,
        "remaining_gates": list(REMAINING_GATES),
    }
