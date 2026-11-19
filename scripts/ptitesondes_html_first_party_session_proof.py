"""First-party HTML event/session corroboration: read-only, not independent admission.

The event HTML comes from an exact pinned official-index child fetch.  This
module deliberately does NOT claim organizer ownership, fresh venue/GPS proof,
commercial rights, clear access conditions, age suitability, or approval.
It reuses the existing official-page visible-cues and same-block time proof.
"""
from urllib.parse import urlsplit

from ptitesondes_family_national_source_preflight import (
    _session_pair_on_official_page, _source_cues, official_host,
    TIME_PATTERN,
)

SCHEMA = "ptitesondes.html_first_party_session_corroboration.v1"
SOURCE_REASONS = frozenset({
    "official_html_unreadable",
    "official_title_venue_city_mismatch",
    "official_dated_occurrence_not_confirmed",
    "official_local_start_time_not_confirmed",
    "cancelled_full_or_postponed",
    "official_family_audience_not_confirmed",
    "exact_age_bounds_not_confirmed",
    "explicit_free_claim_not_on_official_page",
    "explicit_price_claim_not_on_official_page",
    "registration_required_claim_not_on_official_page",
    "no_registration_claim_not_on_official_page",
    "unresolved_access_contradiction",
})
HARD_REASONS = frozenset({
    "official_html_unreadable",
    "official_title_venue_city_mismatch",
    "official_dated_occurrence_not_confirmed",
    "official_local_start_time_not_confirmed",
    "cancelled_full_or_postponed",
})
AUDIENCE_REASONS = frozenset({
    "official_family_audience_not_confirmed",
    "exact_age_bounds_not_confirmed",
})
ACCESS_REASONS = SOURCE_REASONS - HARD_REASONS - AUDIENCE_REASONS


def corroborate_first_party_session(lead, fetched_page, trusted_index, child_prefix):
    """Only fixed categorical results; never return first-party page contents."""
    out = {
        "schema": SCHEMA,
        "visible_exact_session": False,
        "source_identity_consistent": False,
        "family_audience_source_cues_present": False,
        "access_claims_consistent": False,
        "access_needs_review": True,
        "status": "source_unverified",
        "source_is_not_independent_corroboration": True,
        "independent_organizer_verified": False,
        "independent_venue_gps_verified": False,
        "rights_reviewed": False,
        "approval_granted": False,
        "publication_ready": False,
        "public_writes": 0,
    }
    if (not isinstance(lead, dict) or not isinstance(fetched_page, dict)
            or set(fetched_page) != {"url", "html"}
            or not isinstance(trusted_index, dict)
            or set(trusted_index) != {"approved_host", "exact_index_url"}
            or not isinstance(child_prefix, str)
            or not child_prefix.startswith("/")
            or not child_prefix.endswith("/")):
        return out
    host = trusted_index.get("approved_host")
    if (not isinstance(host, str) or host != official_host(trusted_index.get("exact_index_url"))
            or not isinstance(lead.get("source_url"), str)
            or fetched_page.get("url") != lead["source_url"]
            or official_host(lead["source_url"]) != host):
        return out
    try:
        child = urlsplit(lead["source_url"])
        if (not child.path.startswith(child_prefix)
                or len(child.path) <= len(child_prefix)
                or child.query or child.fragment):
            return out
    except ValueError:
        return out
    clock = lead.get("start_local")
    if not isinstance(clock, str) or not TIME_PATTERN.fullmatch(clock):
        return out
    html = fetched_page.get("html")
    source = {"start_local": clock}
    scope = {
        "title": lead.get("title"),
        "city": lead.get("city"),
        "venue": lead.get("venue"),
        "date_start": lead.get("date_start"),
        "age_min": None,
        "age_max": None,
        "price_evidence": lead.get("price_evidence"),
        "registration_evidence": lead.get("registration_evidence"),
    }
    if (any(not isinstance(scope[k], str) or not scope[k].strip()
            for k in ("title", "city", "venue", "date_start"))
            or not isinstance(html, str)
            or scope["price_evidence"] not in (
                "explicit_free", "explicit_price", "not_stated",
                "ambiguous", "contradictory")
            or scope["registration_evidence"] not in (
                "explicit_required", "explicit_not_required", "not_stated",
                "ambiguous", "contradictory")):
        return out
    try:
        issues = _source_cues(scope, source, html)
        if not isinstance(issues, set) or not issues <= SOURCE_REASONS:
            return out
        if issues & HARD_REASONS:
            return dict(out, status="identity_date_status_or_clock_mismatch")
        pair = _session_pair_on_official_page(html, scope, clock)
        if not pair:
            return dict(out, status="same_block_date_and_clock_not_visible")
    except (ValueError, TypeError, KeyError):
        return out
    access = not bool(issues & ACCESS_REASONS)
    audience = not bool(issues & AUDIENCE_REASONS)
    # "not stated" is not equivalent to free admission or registration waived.
    known_access = (scope["price_evidence"] in ("explicit_free", "explicit_price")
                    and scope["registration_evidence"]
                    in ("explicit_required", "explicit_not_required"))
    access_needs_review = not (access and known_access)
    return dict(
        out,
        status=("first_party_visible_session_access_pending"
                if access_needs_review or not audience
                else "first_party_visible_session_all_cues"),
        visible_exact_session=True,
        source_identity_consistent=True,
        family_audience_source_cues_present=audience,
        access_claims_consistent=access,
        access_needs_review=access_needs_review,
    )
