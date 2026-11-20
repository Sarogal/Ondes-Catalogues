"""Read-only non-musical HTML admission *routing*, never admission itself.

Source-index pin and venue/history registries come from a trusted caller and
must not be built from candidate values. The result contains only stable,
anonymous reason codes and no payload. A private factual draft is inspected
in memory and discarded; this module cannot publish, create a patch, approve
rights, register a source or emit an event into a queue.

The existing music/OpenAgenda publisher remains entirely unchanged.
"""
from ptitesondes_family_national_scope import FAMILY_TYPES, LEGACY_MUSICAL
from ptitesondes_factual_reuse_preflight import prepare_private_html_factual_draft
from ptitesondes_html_first_party_session_proof import corroborate_first_party_session
from ptitesondes_html_access_conditions import triage_html_access_conditions
from ptitesondes_html_family_age import triage_html_family_age
from ptitesondes_html_registry_history_triage import triage_independent_context

SCHEMA = "ptitesondes.nonmusical_html_gate_router_readonly.v1"
STAGES = frozenset({
    "session_source_unverified", "nonmusical_scope_unrecognized",
    "family_audience_unconfirmed", "access_terms_unreadable",
    "access_terms_conflicting", "source_facts_not_structured",
    "historical_duplicate", "historical_collision_ambiguous",
    "historical_snapshot_unchecked", "reviewed_venue_missing",
    "reviewed_venue_ambiguous", "reviewed_venue_untrusted",
    "reviewed_venue_unchecked", "independent_geo_rights_review_required",
})
ACTIONS = {
    "session_source_unverified": "recheck_exact_pinned_session",
    "nonmusical_scope_unrecognized": "review_family_taxonomy",
    "family_audience_unconfirmed": "check_official_audience",
    "access_terms_unreadable": "recheck_official_access",
    "access_terms_conflicting": "resolve_official_access_conflict",
    "source_facts_not_structured": "review_source_factual_fields",
    "historical_duplicate": "do_not_republish_duplicate",
    "historical_collision_ambiguous": "review_series_and_clock_collision",
    "historical_snapshot_unchecked": "refresh_trusted_historical_snapshot",
    "reviewed_venue_missing": "register_independent_venue",
    "reviewed_venue_ambiguous": "resolve_reviewed_venue_identity",
    "reviewed_venue_untrusted": "audit_independent_venue_registry",
    "reviewed_venue_unchecked": "load_independent_venue_registry",
    "independent_geo_rights_review_required":
        "run_venue_geo_organizer_rights_and_publisher_review",
}
# These cannot be inferred from first-party HTML, collector hints or a
# candidate's "verified" flag. Even a successful source-only route is held.
REMAINING_INDEPENDENT_GATES = (
    "current_official_organizer_ownership",
    "fresh_independent_venue_gps",
    "origin_database_and_fact_reuse_policy",
    "live_public_catalogue_duplicate_check",
    "nonmusical_publisher_schema_and_proof_contract",
)

def _result(stage, *, venue="not_checked", history="not_checked",
            child_session=False, family=False, access=False,
            source_factual_draft=False):
    return {
        "schema": SCHEMA,
        "mode": "read_only_structural_triage_no_promotion",
        "stage": stage,
        "next_private_review_action": ACTIONS[stage],
        "source_exact_session_confirmed": child_session,
        "source_family_audience_confirmed": family,
        "source_access_terms_noncontradictory": access,
        "source_only_factual_draft_possible": source_factual_draft,
        "venue_registry_status": venue,
        "historical_snapshot_status": history,
        # On all routes the independent gates remain required, even if
        # the diagnostic has positive source data.
        "remaining_independent_checks": list(REMAINING_INDEPENDENT_GATES),
        "rights_reviewed": False,
        "organizer_independently_attested": False,
        "fresh_geo_independently_verified": False,
        "live_duplicates_independently_checked": False,
        "publisher_schema_approved": False,
        "can_submit_to_publisher": False,
        "publication_ready": False,
        "approval_granted": False,
        "public_writes": 0,
        "contains_candidate_fields": False,
    }


def route_nonmusical_html_session(lead, page, trusted_index, child_prefix,
                                  independent_context):
    """Classify *one* session using verified source + curated context.

    The trusted caller MUST fetch the current official child page via the
    already-reviewed index/host adapter; merely passing a candidate-provided
    URL, fake context or arbitrary HTML is not independent evidence.
    """
    try:
        corroboration = corroborate_first_party_session(
            lead, page, trusted_index, child_prefix)
    except (ValueError, KeyError, TypeError):
        corroboration = {}
    if corroboration.get("visible_exact_session") is not True:
        return _result("session_source_unverified")
    exact = True
    if (not isinstance(lead, dict)
            or not isinstance(lead.get("category"), str)
            or lead.get("category") not in FAMILY_TYPES
            or lead.get("category") in LEGACY_MUSICAL):
        return _result("nonmusical_scope_unrecognized", child_session=exact)

    # Source text may confirm an audience but never the right to publish.
    audience = triage_html_family_age(lead, page, trusted_index, child_prefix)
    if (audience.get("reason") != "visible_first_party_family_age_terms_only"
            or not audience.get("explicit_first_party_family_audience")
            or audience.get("family_or_age_review_pending") is not False):
        return _result("family_audience_unconfirmed", child_session=exact)
    access = triage_html_access_conditions(lead, page, trusted_index, child_prefix)
    if access.get("reason") != "visible_first_party_access_terms_only":
        return _result("access_terms_unreadable", child_session=exact, family=True)
    if access.get("price_state") == "conflicting" or access.get(
            "registration_state") == "conflicting":
        return _result("access_terms_conflicting", child_session=exact, family=True)
    if (access.get("price_state") not in (
            "free_disclosed", "free_with_mandatory_membership",
            "paid_disclosed", "paid_amount_unknown", "unknown")
            or access.get("registration_state") not in (
                "required", "explicit_not_required", "unknown")):
        return _result("access_terms_unreadable", child_session=exact, family=True)

    proposal = prepare_private_html_factual_draft(
        lead, page, trusted_index, child_prefix)
    # A producer-supplied "draft" or "verified" boolean is never an input to
    # this router. The parser recomputes the evidence from the source.
    if (proposal.get("status") != "private_draft_for_rights_review"
            or not isinstance(proposal.get("draft"), dict)
            or proposal["draft"].get("safe_to_publish") is not False):
        return _result("source_facts_not_structured",
                       child_session=exact, family=True, access=True)

    context = triage_independent_context(lead, independent_context)
    venue = context.get("venue_status", "not_checked")
    history = context.get("history_status", "not_checked")
    kwargs = dict(venue=venue, history=history, child_session=exact,
                  family=True, access=True, source_factual_draft=True)
    # Historical collisions take priority over creating fresh candidates.
    if history == "duplicate":
        return _result("historical_duplicate", **kwargs)
    if history == "ambiguous":
        return _result("historical_collision_ambiguous", **kwargs)
    if history != "clear":
        return _result("historical_snapshot_unchecked", **kwargs)
    if venue == "missing":
        return _result("reviewed_venue_missing", **kwargs)
    if venue == "ambiguous":
        return _result("reviewed_venue_ambiguous", **kwargs)
    if venue == "untrusted":
        return _result("reviewed_venue_untrusted", **kwargs)
    if venue != "matched":
        return _result("reviewed_venue_unchecked", **kwargs)
    # This is the furthest a source-only, static-registry diagnostic can go.
    # The existing bounded IGN/BAN probe and rights review are separate.
    return _result("independent_geo_rights_review_required", **kwargs)


def aggregate_html_review_routes(reports):
    """Strict redaction for public runner summaries: fixed counts only."""
    if not isinstance(reports, list) or len(reports) > 100:
        raise ValueError("invalid_route_report_batch")
    counts = {stage: 0 for stage in sorted(STAGES)}
    for report in reports:
        if (not isinstance(report, dict)
                or set(report) != set(_result("session_source_unverified"))
                or report.get("schema") != SCHEMA
                or report.get("stage") not in STAGES
                or report.get("mode") != "read_only_structural_triage_no_promotion"
                or report.get("next_private_review_action")
                   != ACTIONS[report["stage"]]
                or report.get("remaining_independent_checks")
                   != list(REMAINING_INDEPENDENT_GATES)
                or report.get("contains_candidate_fields") is not False
                or any(report.get(key) is not False for key in (
                    "rights_reviewed", "organizer_independently_attested",
                    "fresh_geo_independently_verified",
                    "live_duplicates_independently_checked",
                    "publisher_schema_approved", "can_submit_to_publisher",
                    "publication_ready", "approval_granted"))
                or report.get("public_writes") != 0
                or any(type(report.get(key)) is not bool for key in (
                    "source_exact_session_confirmed",
                    "source_family_audience_confirmed",
                    "source_access_terms_noncontradictory",
                    "source_only_factual_draft_possible"))
                or report.get("venue_registry_status") not in (
                    "not_checked", "matched", "missing", "ambiguous", "untrusted")
                or report.get("historical_snapshot_status") not in (
                    "not_checked", "clear", "duplicate", "ambiguous")):
            raise ValueError("unsafe_or_unverified_route_report")
        counts[report["stage"]] += 1
    return {
        "schema": "ptitesondes.nonmusical_html_routes_public_counts.v1",
        "checked": len(reports),
        "stage_counts": counts,
        "rights_reviewed": False,
        "publisher_connected": False,
        "publication_ready": False,
        "approval_granted": False,
        "public_writes": 0,
        "candidate_identifiers_present": False,
    }
