"""Read-only source-index -> exact detail -> child-session -> scope funnel.

Reuses the official HTML link reader (#420), the already-existing MPT detail
parser, and the generic family scope diagnostic. It does not turn unreviewed
venues, dates, source rights or API data into independent evidence.

No publisher, no private queue writes, no API key and no catalogue mutation.
Only a separately maintained trusted caller may supply a source pin. This
file never builds a pin from candidate fields or a search result.
"""
from collections import Counter
from datetime import date, datetime, time, timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
import re

from ptitesondes_official_html_index_discovery import (
    discover_live_html_event_pages,
)
from ptitesondes_openagenda_v2_geo_fetch import fetch_official_page
from ptitesondes_real_family_source_adapters import (
    parse_montpellier_mpt_detail, scope_proposals, classify, norm, MPT_HOST,
    has_explicit_musical_theme,
)
from ptitesondes_family_national_scope import FAMILY_TYPES
from ptitesondes_html_registry_history_triage import triage_independent_context
from ptitesondes_html_first_party_session_proof import (
    corroborate_first_party_session,
)
from ptitesondes_html_independent_venue_geo import (
    diagnose_html_independent_venue,
)
from ptitesondes_html_access_conditions import triage_html_access_conditions

SCHEMA = "ptitesondes.html_index_detail_funnel_readonly.v1"
MAX_DETAILS = 30
_FAMILY_SLUG_HINT = re.compile(
    r"\b(enfant|enfants|bebe|bebes|famille|familles|"
    r"petit|petits|jeunesse|motricite|atelier|cirque|spectacle)\b"
)
# Registry is an adapter contract (one site family), NOT per event.
READ_ONLY_ADAPTERS = {
    "montpellier_mpt": {
        "host": MPT_HOST, "child_path": "/evenement/",
        "timezone": "Europe/Paris",
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
        "unclassified_occurrences_held": 0,
        "explicit_musical_occurrences_held": 0,
        "unclassified_nonmusical_occurrences_held": 0,
        "duplicate_child_sessions_held": 0,
        "already_started_sessions_held": 0,
        "exact_local_clock_cutoff_applied": False,
        "structurally_plausible_for_independent_review": 0,
        "registry_location_exact_matches": 0,
        "registry_location_missing": 0,
        "registry_location_ambiguous": 0,
        "registry_location_untrusted": 0,
        "registry_location_not_checked": 0,
        "historical_exact_duplicates_held": 0,
        "historical_ambiguous_collisions_held": 0,
        "historical_no_collision_found": 0,
        "historical_not_checked": 0,
        "first_party_visible_exact_sessions": 0,
        "first_party_source_sessions_held": 0,
        "first_party_missing_same_block": 0,
        "first_party_audience_cues_missing": 0,
        "first_party_access_review_pending": 0,
        "first_party_all_visible_cues": 0,
        "access_first_party_free_with_required_membership": 0,
        "access_first_party_free_without_required_membership": 0,
        "access_first_party_paid_declared": 0,
        "access_first_party_paid_without_amount": 0,
        "access_first_party_unknown_or_conflicting": 0,
        "access_first_party_price_not_stated": 0,
        "access_first_party_price_conflicting": 0,
        "access_first_party_scan_held": 0,
        "access_first_party_registration_required": 0,
        "access_first_party_registration_not_required": 0,
        "access_first_party_registration_unknown_or_conflicting": 0,
        "access_first_party_registration_not_stated": 0,
        "access_first_party_registration_conflicting": 0,
        "access_first_party_source_review_required": 0,
        "geo_distinct_venues_probed": 0,
        "geo_independent_ban_registry_concordant": 0,
        "geo_official_address_unstructured": 0,
        "geo_ban_housenumber_unverified": 0,
        "geo_ban_registry_conflict": 0,
        "geo_other_unverified": 0,
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


def _sample_priority(url):
    """URL text helps choose a diverse DIAGNOSTIC sample, never prove content."""
    slug = urlsplit(url).path.rsplit("/", 1)[-1].replace("-", " ")
    return (classify(slug) is None,
            _FAMILY_SLUG_HINT.search(norm(slug)) is None,
            url)


def _diverse_probe_order(children):
    """Spread fixed-cap probes over distinct URL families *for sampling only*.

    Numeric URL suffixes may be real separate sessions. No child link is
    discarded or declared a duplicate; all remain available when the sample
    limit grows. Cross-page session identity is checked separately.
    """
    selected, later, stems = [], [], set()
    for url in sorted(set(children), key=_sample_priority):
        slug = urlsplit(url).path.rsplit("/", 1)[-1]
        stem = re.sub(r"-[0-9]{1,3}$", "", slug)
        if stem in stems:
            later.append(url)
        else:
            stems.add(stem)
            selected.append(url)
    return selected + later


def diagnose_html_index_detail_funnel(
        independently_pinned_index, adapter_id, today,
        *, max_details=12, as_of=None, index_opener=None,
        detail_opener=None, independent_context=None,
        geo_probe_limit=0, geo_venue_reader=None, geo_ban_reader=None):
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
            or adapter_id not in READ_ONLY_ADAPTERS
            or type(geo_probe_limit) is not int
            or not 0 <= geo_probe_limit <= 3
            or (geo_venue_reader is None) != (geo_ban_reader is None)
            or (geo_venue_reader is not None and
                (not callable(geo_venue_reader) or not callable(geo_ban_reader)))):
        return _empty()
    contract = READ_ONLY_ADAPTERS[adapter_id]
    if independently_pinned_index["approved_host"] != contract["host"]:
        return _empty()
    # An exact local-time cutoff comes only from the trusted caller. Without
    # it, dates are checked by day only and the report says so explicitly.
    source_timezone = ZoneInfo(contract["timezone"])
    as_of_local = None
    if as_of is not None:
        if (type(as_of) is not datetime or as_of.tzinfo is None
                or as_of.utcoffset() is None):
            return _empty("invalid_trusted_local_clock")
        as_of_local = as_of.astimezone(source_timezone)
        if as_of_local.date() != today:
            return _empty("trusted_local_clock_day_mismatch")
    # The GET reader checks exact HTTPS URL, host, media type, size and
    # redirects. An index HTML response is never trusted as a registered
    # organisation or source rights.
    index = discover_live_html_event_pages(
        independently_pinned_index, opener=index_opener)
    if index.get("stage") != "routing_suggestions_only":
        return _empty("trusted_index_fetch_or_parse_held")

    result = _empty("sampled_child_sessions_unverified")
    result["exact_local_clock_cutoff_applied"] = as_of_local is not None
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
    # Bound, coverage-biased and deterministic. A URL slug only changes
    # diagnostic reading order; it never supplies category or age evidence.
    children = _diverse_probe_order(children)
    result["child_pages_matching_contract"] = len(children)
    selected = children[:max_details]
    result["child_pages_selected"] = len(selected)
    result["child_pages_skipped_by_limit"] = len(children) - len(selected)

    seen_sessions = set()
    probed_geo_venues = set()
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
        if as_of_local is not None:
            kept = []
            for row in leads:
                try:
                    d = date.fromisoformat(row["date_start"])
                    t = time.fromisoformat(row["start_local"])
                    event_local = datetime.combine(d, t, tzinfo=source_timezone)
                    # Explicit offsets are needed for ambiguous DST folds;
                    # never silently infer which occurrence is intended.
                    ambiguous = (event_local.replace(fold=1).utcoffset()
                                 != event_local.utcoffset())
                    restored = event_local.astimezone(timezone.utc).astimezone(
                        source_timezone)
                    nonexistent = (restored.date() != d or
                                   restored.replace(tzinfo=None).time() != t)
                    if (ambiguous or nonexistent or
                            event_local.astimezone(timezone.utc) <=
                            as_of_local.astimezone(timezone.utc)):
                        result["already_started_sessions_held"] += 1
                        continue
                except (ValueError, TypeError, KeyError, OverflowError):
                    result["already_started_sessions_held"] += 1
                    continue
                kept.append(row)
            leads = kept
        if not leads:
            result["child_pages_without_future_child_session"] += 1
            continue
        # Different official URLs can represent the SAME occurrence.
        # Compare venue + title + city + exact day/start clock, never URL
        # suffixes or event title alone; separate hours remain separate.
        deduplicated = []
        for row in leads:
            signature = (norm(row.get("title")), norm(row.get("city")),
                         norm(row.get("venue")), row.get("date_start"),
                         row.get("start_local"))
            if signature in seen_sessions:
                result["duplicate_child_sessions_held"] += 1
            else:
                seen_sessions.add(signature)
                deduplicated.append(row)
        leads = deduplicated
        result["future_child_occurrences"] += len(leads)
        # The adapter may recognize a real child session whose topic is not
        # yet one of the independently reviewed family categories. Never
        # silently count that session as approved or in-scope.
        unclassified = [
            row for row in leads if row.get("category") not in FAMILY_TYPES
        ]
        musical = sum(
            has_explicit_musical_theme(row.get("title", ""))
            for row in unclassified
        )
        result["unclassified_occurrences_held"] += len(unclassified)
        result["explicit_musical_occurrences_held"] += musical
        result["unclassified_nonmusical_occurrences_held"] += (
            len(unclassified) - musical
        )
        # Context is separately supplied by the caller from reviewed place
        # registries and a pinned historical snapshot. A match is NOT a new
        # geocoder request or proof of this event. Never return individual
        # candidate data from this diagnostic.
        for row in leads:
            if row.get("category") not in FAMILY_TYPES:
                continue
            corroboration = corroborate_first_party_session(
                row, page, independently_pinned_index, contract["child_path"])
            if corroboration["visible_exact_session"]:
                result["first_party_visible_exact_sessions"] += 1
                if not corroboration["family_audience_source_cues_present"]:
                    result["first_party_audience_cues_missing"] += 1
                if corroboration["access_needs_review"]:
                    result["first_party_access_review_pending"] += 1
                if corroboration["status"] == "first_party_visible_session_all_cues":
                    result["first_party_all_visible_cues"] += 1
            else:
                result["first_party_source_sessions_held"] += 1
                if corroboration["status"] == "same_block_date_and_clock_not_visible":
                    result["first_party_missing_same_block"] += 1
            if corroboration["visible_exact_session"]:
                access = triage_html_access_conditions(
                    row, page, independently_pinned_index, contract["child_path"])
                key = {
                    "free_with_mandatory_membership":
                        "access_first_party_free_with_required_membership",
                    "free_disclosed":
                        "access_first_party_free_without_required_membership",
                    "paid_disclosed": "access_first_party_paid_declared",
                    "paid_amount_unknown": "access_first_party_paid_without_amount",
                    "unknown": "access_first_party_unknown_or_conflicting",
                    "conflicting": "access_first_party_unknown_or_conflicting",
                }[access["price_state"]]
                result[key] += 1
                if access["price_state"] == "unknown":
                    result["access_first_party_price_not_stated"] += 1
                elif access["price_state"] == "conflicting":
                    result["access_first_party_price_conflicting"] += 1
                if access["reason"] != "visible_first_party_access_terms_only":
                    result["access_first_party_scan_held"] += 1
                key = {
                    "required": "access_first_party_registration_required",
                    "explicit_not_required":
                        "access_first_party_registration_not_required",
                    "unknown": "access_first_party_registration_unknown_or_conflicting",
                    "conflicting": "access_first_party_registration_unknown_or_conflicting",
                }[access["registration_state"]]
                result[key] += 1
                if access["registration_state"] == "unknown":
                    result["access_first_party_registration_not_stated"] += 1
                elif access["registration_state"] == "conflicting":
                    result["access_first_party_registration_conflicting"] += 1
                if access["first_party_source_access_review_pending"]:
                    result["access_first_party_source_review_required"] += 1
            triage = triage_independent_context(row, independent_context)
            venue = triage["venue_status"]
            history = triage["history_status"]
            result[{
                "matched": "registry_location_exact_matches",
                "missing": "registry_location_missing",
                "ambiguous": "registry_location_ambiguous",
                "untrusted": "registry_location_untrusted",
                "not_checked": "registry_location_not_checked",
            }[venue]] += 1
            result[{
                "duplicate": "historical_exact_duplicates_held",
                "ambiguous": "historical_ambiguous_collisions_held",
                "clear": "historical_no_collision_found",
                "not_checked": "historical_not_checked",
            }[history]] += 1
            # Only a bounded, independently reviewed *unique building* is
            # probed. An event's claimed coordinates and URL never create the
            # registry pin. This is a read-only venue-only diagnostic.
            if (geo_probe_limit and venue == "matched" and
                    history == "clear" and
                    corroboration["visible_exact_session"]):
                key = (norm(row.get("city")), norm(row.get("venue")))
                if (key not in probed_geo_venues and
                        len(probed_geo_venues) < geo_probe_limit):
                    probed_geo_venues.add(key)
                    kwargs = {}
                    if geo_venue_reader is not None:
                        kwargs = {
                            "venue_reader": geo_venue_reader,
                            "ban_reader": geo_ban_reader,
                        }
                    geo = diagnose_html_independent_venue(
                        row, independent_context, **kwargs)
                    result["geo_distinct_venues_probed"] += 1
                    if geo["geometry_evidence_consistent"]:
                        result["geo_independent_ban_registry_concordant"] += 1
                    elif geo["reason"] == "official_venue_address_not_structured":
                        result["geo_official_address_unstructured"] += 1
                    elif geo["reason"] == "ban_housenumber_missing_or_ambiguous":
                        result["geo_ban_housenumber_unverified"] += 1
                    elif geo["reason"] == "ban_conflicts_with_reviewed_venue":
                        result["geo_ban_registry_conflict"] += 1
                    else:
                        result["geo_other_unverified"] += 1
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
    out["exact_local_clock_cutoff_applied"] = (
        report.get("exact_local_clock_cutoff_applied") is True
    )
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
