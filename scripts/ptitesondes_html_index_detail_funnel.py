"""Read-only source-index -> exact detail -> child-session -> scope funnel.

Reuses the official HTML link reader (#420), the already-existing MPT detail
parser, and the generic family scope diagnostic. It does not turn unreviewed
venues, dates, source rights or API data into independent evidence.

No publisher, no private queue writes, no API key and no catalogue mutation.
Only a separately maintained trusted caller may supply a source pin. This
file never builds a pin from candidate fields or a search result.
"""
from collections import Counter
from datetime import date
from urllib.parse import urlsplit

from ptitesondes_official_html_index_discovery import (
    discover_live_html_event_pages,
)
from ptitesondes_openagenda_v2_geo_fetch import fetch_official_page
from ptitesondes_real_family_source_adapters import (
    parse_montpellier_mpt_detail, scope_proposals, MPT_HOST,
)

SCHEMA = "ptitesondes.html_index_detail_funnel_readonly.v1"
MAX_DETAILS = 30
# Registry is an adapter contract (one site family), NOT per event.
READ_ONLY_ADAPTERS = {
    "montpellier_mpt": {
        "host": MPT_HOST, "child_path": "/evenement/",
        "parser": parse_montpellier_mpt_detail,
    },
}


def _empty(stage="invalid_trusted_pilot_configuration"):
    return {
        "schema": SCHEMA, "stage": stage,
        "index_visible_anchors": 0,
        "index_routed_links": 0,
        "child_pages_matching_contract": 0,
        "child_pages_selected": 0,
        "child_pages_skipped_by_limit": 0,
        "child_pages_read": 0,
        "child_pages_held": 0,
        "child_pages_without_future_child_session": 0,
        "future_child_occurrences": 0,
        "structurally_plausible_for_independent_review": 0,
        "scope_blocked_reason_counts": {},
        "independent_institution_owner_attested": False,
        "independent_venue_verified": False,
        "independent_age_access_rights_verified": False,
        "independent_event_session_verified": False,
        "independent_gps_refetched": False,
        "publisher_connected": False,
        "publication_ready": False,
        "approval_granted": False,
        "public_writes": 0,
        "candidate_details_redacted": True,
    }


def diagnose_html_index_detail_funnel(
        independently_pinned_index, adapter_id, today,
        *, max_details=12, index_opener=None, detail_opener=None):
    """Sample one approved official index and independently fetch child pages.

    A positive scope diagnostic only means a candidate has the *shape* of a
    dated family outing. It is not verification of the source, age, venue,
    geo data, rights or approval. Do not pass these results to the publisher.
    """
    if (type(today) is not date or type(max_details) is not int
            or not 1 <= max_details <= MAX_DETAILS
            or not isinstance(independently_pinned_index, dict)
            or set(independently_pinned_index)
            != {"approved_host", "exact_index_url"}
            or not isinstance(adapter_id, str)
            or adapter_id not in READ_ONLY_ADAPTERS):
        return _empty()
    contract = READ_ONLY_ADAPTERS[adapter_id]
    if independently_pinned_index["approved_host"] != contract["host"]:
        return _empty()
    # The GET reader checks exact HTTPS URL, host, media type, size and
    # redirects. An index HTML response is never trusted as a registered
    # organisation or source rights.
    index = discover_live_html_event_pages(
        independently_pinned_index, opener=index_opener)
    if index.get("stage") != "routing_suggestions_only":
        return _empty("trusted_index_fetch_or_parse_held")

    result = _empty("sampled_child_sessions_unverified")
    result["index_visible_anchors"] = index["counts"]["visible_index_anchors"]
    result["index_routed_links"] = index["counts"]["same_host_child_pages"]
    children = []
    for item in index["private_routing_proposals"]:
        raw_url = item["url"]
        try:
            p = urlsplit(raw_url)
            if (p.hostname == contract["host"]
                    and p.path.startswith(contract["child_path"])
                    and len(p.path) > len(contract["child_path"])
                    and not p.query and not p.fragment):
                children.append(raw_url)
        except ValueError:
            continue
    # Bound and deterministic. A sample is NOT a comprehensive collection.
    children = sorted(set(children))
    result["child_pages_matching_contract"] = len(children)
    selected = children[:max_details]
    result["child_pages_selected"] = len(selected)
    result["child_pages_skipped_by_limit"] = len(children) - len(selected)

    for child in selected:
        try:
            page = fetch_official_page({
                "approved_host": contract["host"], "exact_url": child,
            }, opener=detail_opener)
            leads = contract["parser"](page["html"], child, today)
            if not isinstance(leads, list):
                raise ValueError("unexpected_adapter_result")
        except (ValueError, TypeError, OSError, TimeoutError, KeyError):
            result["child_pages_held"] += 1
            continue
        result["child_pages_read"] += 1
        if not leads:
            result["child_pages_without_future_child_session"] += 1
            continue
        result["future_child_occurrences"] += len(leads)
        try:
            scopes = scope_proposals(leads, today)
            result["structurally_plausible_for_independent_review"] += sum(
                int(batch["structurally_plausible_for_independent_review"])
                for batch in scopes
            )
            reasons = Counter(result["scope_blocked_reason_counts"])
            for batch in scopes:
                reasons.update(batch.get("blocked_reason_counts", {}))
            result["scope_blocked_reason_counts"] = dict(sorted(reasons.items()))
        except (ValueError, KeyError, TypeError):
            # All items remain unapproved; scope failures are not successes.
            result["scope_blocked_reason_counts"]["scope_contract_held"] = (
                result["scope_blocked_reason_counts"].get("scope_contract_held", 0)
                + len(leads)
            )
    return result


def redact_detail_funnel_report(report):
    """Fixed-schema dashboard; even forged reports cannot insert private data."""
    empty = _empty()
    if not isinstance(report, dict) or report.get("schema") != SCHEMA:
        report = empty
    allowed_counts = tuple(k for k, v in empty.items()
                           if type(v) is int and k != "public_writes")
    out = _empty("aggregate_report_without_private_identifiers")
    for key in allowed_counts:
        n = report.get(key)
        out[key] = n if type(n) is int and 0 <= n <= 100_000 else 0
    # Do not copy dynamic reason keys from untrusted reports into public logs.
    known = frozenset((
        "unknown_record_kind", "missing_place_or_title",
        "source_url_shape_unverified",
        "explicit_family_audience_claim_missing_or_invalid",
        "access_evidence_state_missing_or_invalid",
        "nonmusical_category_not_in_explicit_contract",
        "legacy_musical_pipeline_unchanged",
        "dated_occurrence_unverified_or_expired",
        "category_label_mismatch", "scope_contract_held",
    ))
    counts = report.get("scope_blocked_reason_counts")
    out["scope_blocked_reason_counts"] = {
        key: value
        for key, value in sorted(counts.items())
        if key in known and type(value) is int and 0 <= value <= 100_000
    } if isinstance(counts, dict) else {}
    return out
