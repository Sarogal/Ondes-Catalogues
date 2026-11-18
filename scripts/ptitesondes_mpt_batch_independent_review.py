"""Batch MPT Montpellier listing -> independent source + IGN proof preview.

This is an OPTIONAL one-shot read-only composition of #360 and #362 drafts.
It never writes leads, approval records, patches, files or published content.
A discovery lead is never its own official, geographic or approval evidence.
"""
from datetime import date
from copy import deepcopy

from ptitesondes_mpt_listing_discovery import (
    discover_listing, MAX_PAGES, MAX_HTML_BYTES, trusted_detail,
)
from ptitesondes_mpt_family_independent_preflight import (
    independent_family_preview, MAX_LEADS,
)
from ptitesondes_family_national_source_preflight import canonical_sha256
from merge_policy import byid

SCHEMA = "ptitesondes.mpt_batch_independent_source_geo_preview.v1"


def _empty_independent_summary(catalogue):
    return {
        "curated_geographic_venues_with_live_recheck": 0,
        "eligible_for_independent_source_preflight": 0,
        "official_source_cues_passed": 0,
        "held_before_source_preflight": {},
        "held_by_independent_source_preflight": {},
        "public_catalogue_preserved": len(catalogue["events"]),
        "catalogue_unchanged": True,
    }


def review_official_listing_batch(listing_html, catalogue, today, *,
                                  detail_get, geocoder_get, page_limit=24):
    """Review all bounded listing occurrences; hold excess transparently.

    detail_get and geocoder_get must be separate clients with
    independent security boundaries. This code cannot invent their trust.
    Only strict municipal detail URLs can reach detail_get;
    the geo callback receives URLs solely from curated registry, never leads.

    Returns anonymous counters only, NO leads, identities, raw HTML or URLs.
    """
    if (type(today) is not date or not callable(detail_get)
            or not callable(geocoder_get) or not isinstance(catalogue, dict)
            or type(page_limit) is not int
            or not 1 <= page_limit <= MAX_PAGES):
        raise ValueError("invalid_mpt_batch_preview_inputs")
    byid(catalogue)
    before = deepcopy(catalogue)
    pin = canonical_sha256(catalogue)

    cache = {}
    def get_official(url):
        if not trusted_detail(url):
            raise ValueError("untrusted_listing_detail")
        if url not in cache:
            raw = detail_get(url)
            if (not isinstance(raw, str)
                    or not 50 <= len(raw.encode("utf-8")) <= MAX_HTML_BYTES):
                raise ValueError("invalid_mpt_official_detail")
            cache[url] = raw
        return cache[url]

    # Do not use title/age/venue copied from a listing card as publication proof.
    leads, discovery = discover_listing(
        listing_html, today=today, detail_get=get_official,
        page_limit=page_limit,
    )
    if discovery["held_unreadable_details"]:
        # Incomplete sample: do not claim a successful proof batch from an
        # arbitrarily missing official page.
        checked = _empty_independent_summary(catalogue)
        checked["held_before_source_preflight"] = {
            "discovery_incomplete_no_review": len(leads),
        }
        chosen = []
        over_limit = 0
    else:
        chosen = leads[:MAX_LEADS]
        over_limit = max(0, len(leads) - MAX_LEADS)
        checked = (independent_family_preview(
            chosen, catalogue, today, official_get=get_official,
            geocoder_get=geocoder_get)
            if chosen else _empty_independent_summary(catalogue))
    if catalogue != before or canonical_sha256(catalogue) != pin:
        raise ValueError("catalogue_changed_during_mpt_batch_review")

    result = {
        "schema": SCHEMA,
        "mode": "bounded_official_listing_and_independent_geo_readonly",
        "listing_unique_detail_urls": discovery["listed_unique_detail_urls"],
        "detail_pages_selected": discovery["selected_detail_pages"],
        "detail_pages_readable": discovery["readable_detail_pages"],
        "unreadable_detail_pages_held": discovery["held_unreadable_details"],
        "discovered_occurrences": discovery["explicit_dated_occurrences"],
        "classified_family_occurrences": discovery["classified_family_occurrences"],
        "eligible_for_structural_review": discovery[
            "structurally_plausible_for_independent_review"],
        "selected_for_independent_review": len(chosen),
        "held_by_source_batch_limit": over_limit,
        "sample_only_not_full_agenda": True,
        "only_current_listing_page_checked": True,
        "detail_selection_truncated": discovery[
            "selected_details_are_sample_only"],
        "primary_official_detail_requests_distinct": len(cache),
        "venue_points_external_ign_rechecked": checked[
            "curated_geographic_venues_with_live_recheck"],
        "independent_source_cues_passed": checked[
            "official_source_cues_passed"],
        "held_before_independent_checks": checked[
            "held_before_source_preflight"],
        "held_in_independent_checks": checked[
            "held_by_independent_source_preflight"],
        "input_catalogue_events_preserved": len(catalogue["events"]),
        "catalogue_unchanged": True,
        "organizer_identity_not_authenticated": True,
        "private_approvals_checked": False,
        "publication_ready": False,
        "approval_granted_to_publisher": False,
        "published_events": 0,
        "public_writes": 0,
        "candidate_identity_excluded_from_report": True,
    }
    if (result["independent_source_cues_passed"] > len(chosen)
            or result["detail_pages_readable"]
            + result["unreadable_detail_pages_held"]
            != result["detail_pages_selected"]
            or result["selected_for_independent_review"]
               + result["held_by_source_batch_limit"]
               != (0 if discovery["held_unreadable_details"] else len(leads))):
        raise ValueError("unreconciled_mpt_batch_accounting")
    return result
