"""Private-only read-only OA2 identity bridge from an independently curated institution.

This module performs actual exact HTTP reads through the already hardened
official-page and OA2 readers. It never treats API metadata, an ODS mirror,
the candidate's links or a mere municipal hyperlink as proof of ownership,
session, licence, audience, geometry, or permission to publish.

Only the private trusted caller may supply the reviewed institution registry.
The report exposes fixed reason codes and booleans, never event, URL, UID,
key, or HTTP exception details. No publisher, output file or webhook.
"""
from ptitesondes_openagenda_v2_direct_evidence import (
    _source_parts, _uid, _norm, _fr, API_ORIGIN, read_direct_v2,
)
from ptitesondes_openagenda_v2_geo_fetch import fetch_official_page
from ptitesondes_openagenda_v2_institutional_delegation import (
    _registry_by_slug, _legacy_mirror_slug,
    inspect_institutional_agenda_page,
    diagnose_legacy_ods_authenticated_mapping,
)

SCHEMA = "ptitesondes.oa2.live_pinned_bridge_readonly.v1"


def _result(stage="invalid_candidate_or_registry", link=False, verified=False):
    return {
        "schema": SCHEMA,
        "stage": stage,
        "institutional_root_link_observed": link is True,
        "api_identity_bound_for_review": verified is True,
        "institution_owner_attested": False,
        "independent_event_session_verified": False,
        "independent_venue_verified": False,
        "age_access_verified": False,
        "rights_reviewed": False,
        "approval_granted": False,
        "publisher_connected": False,
        "public_writes": 0,
        "contains_private_identifiers": False,
    }


def _lead_identity(lead):
    """Return (mode, agenda slug, event UID) or None; never trust source host."""
    if not isinstance(lead, dict):
        return None
    uid = lead.get("external_id")
    if not isinstance(uid, str) or not _uid(uid):
        return None
    strict = _source_parts(lead.get("source_url"))
    if strict is not None:
        if strict[1] == uid:
            return ("strict", strict[0], uid)
        return None
    legacy = _legacy_mirror_slug(lead.get("source_url"))
    if legacy is not None and lead.get("collector") == "opendatasoft-index":
        return ("legacy", legacy, uid)
    return None


def _same_title_and_place(lead, event):
    """Identity concordance only, not independent evidence of venue location."""
    if not isinstance(event, dict) or not _uid(event.get("uid")):
        return False
    if not _norm(lead.get("title")) or (
            _norm(_fr(event, "title")) != _norm(lead.get("title"))):
        return False
    place = event.get("location")
    return (
        isinstance(place, dict)
        and bool(_norm(lead.get("city")))
        and bool(_norm(lead.get("venue")))
        and _norm(place.get("adminLevel4")) == _norm(lead.get("city"))
        and _norm(place.get("name")) == _norm(lead.get("venue"))
    )


def diagnose_live_pinned_agenda(
        lead, independently_reviewed_sources, public_read_key,
        institution_opener=None, api_opener=None):
    """Verify an institution's OA root link, then bind one direct OA2 response.

    A candidate can never select or populate the reviewed registry.
    A link to the OA agenda is only an independently observed *reference*;
    it does not prove ownership of that agenda or individual sessions.
    The official-page opener is restricted by fetch_official_page; the event
    opener is restricted by read_direct_v2. Test openers are for fixtures only.
    """
    identity = _lead_identity(lead)
    if identity is None:
        return _result()
    mode, slug, uid = identity
    try:
        registry = _registry_by_slug(independently_reviewed_sources)
    except (ValueError, TypeError, KeyError):
        return _result("invalid_candidate_or_registry")
    matches = registry.get(slug, [])
    if not matches:
        return _result("no_independently_curated_institution")
    if len(matches) != 1:
        return _result("ambiguous_independently_curated_institution")
    pin = matches[0]
    try:
        page = fetch_official_page({
            "approved_host": pin["institution_host"],
            "exact_url": pin["exact_page_url"],
        }, opener=institution_opener)
        link = inspect_institutional_agenda_page(pin, page)
    except (ValueError, TypeError, OSError, KeyError):
        return _result("independent_institutional_page_unavailable")
    if link.get("institutional_root_link_observed") is not True:
        return _result("institutional_root_link_not_confirmed")

    # Direct reader owns URL construction, GET, HTTP 200, redirect refusal and
    # public read-only key. Never construct a receipt from untrusted input.
    try:
        event = read_direct_v2(
            pin["agenda_uid"], uid, public_read_key, opener=api_opener)
    except (ValueError, TypeError, OSError, TimeoutError):
        return _result("trusted_api_direct_read_unavailable", link=True)
    if (not isinstance(event, dict) or not _uid(event.get("uid"))
            or str(event["uid"]) != uid):
        return _result("direct_event_uid_mismatch", link=True)
    if not _same_title_and_place(lead, event):
        return _result("direct_event_identity_not_concordant", link=True)

    if mode == "legacy":
        # Internal receipt exists solely because read_direct_v2 just
        # completed the exact GET. It is not accepted from the candidate.
        receipt = {
            "agenda_uid": pin["agenda_uid"],
            "event_uid": uid,
            "response_url": (API_ORIGIN + "/v2/agendas/"
                             + str(pin["agenda_uid"]) + "/events/" + uid),
            "method": "GET",
            "status": 200,
            "key_kind": "public_read_only",
        }
        legacy = diagnose_legacy_ods_authenticated_mapping(
            lead, pin, event, receipt)
        if legacy.get("api_event_identity_bound_for_review") is not True:
            return _result("legacy_api_mapping_not_concordant", link=True)
        return _result(
            "legacy_api_identity_bound_other_gates_pending",
            link=True, verified=True)
    return _result(
        "strict_api_identity_bound_other_gates_pending",
        link=True, verified=True)
