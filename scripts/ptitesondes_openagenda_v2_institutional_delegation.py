"""First-party institutional OpenAgenda ROOT calendar reference, read-only.

One independently approved official website may link directly to an OpenAgenda
agenda root. This corroborates a link between institution and *calendar*; it
does NOT prove calendar ownership, event occurrences, reuse rights, audience,
venue, organizer consent, or authorization to publish. Each event still needs
its own direct OpenAgenda API and evidence checks.

Zero HTTP, credentials, private URLs in public diagnostics, patch or publisher.
"""
from html.parser import HTMLParser
import re
from urllib.parse import urlsplit

from ptitesondes_family_national_source_preflight import norm_text
from ptitesondes_openagenda_v2_direct_evidence import (
    _calendar_review, SLUG,
)
from ptitesondes_openagenda_v2_geo_bridge import _url
from ptitesondes_openagenda_v2_organizer_index import _VisibleAnchors

SCHEMA = "ptitesondes.oa2.institutional_root_agenda_reference.v1"
MAX_HTML = 500_000
MAX_LINKS = 2400
CUE = re.compile(r"\b(?:agenda|evenements?|programm(?:es?|ation)|calendrier|sorties)\b")
SAFE_REASONS = frozenset((
    "unreviewed_institutional_agenda",
    "institutional_page_unavailable",
    "no_visible_exact_root_link",
    "visible_root_link_observed_not_ownership",
))


def _result(reason="unreviewed_institutional_agenda"):
    return {
        "schema": SCHEMA,
        "reason": reason,
        "institutional_root_link_observed": False,
        "independently_attested_owner": False,
        "event_session_verified": False,
        "rights_reviewed": False,
        "age_access_fully_verified": False,
        "approval_granted": False,
        "publisher_connected": False,
        "public_writes": 0,
    }


def _root_link(target, slug):
    """Reject event, share, redirect, locale spoof or parameterized OA URLs."""
    if not isinstance(target, str) or len(target) > 1200:
        return False
    try:
        p = urlsplit(target)
        if (p.scheme != "https" or p.hostname != "openagenda.com"
                or p.port not in (None, 443) or p.username or p.password
                or p.query or p.fragment):
            return False
        path = p.path.strip("/").split("/")
        if path and path[0] in ("fr", "en"):
            path = path[1:]
        return len(path) == 1 and path[0] == slug
    except ValueError:
        return False


def inspect_institutional_agenda_page(reviewed_source, fetched_page):
    """Check exact separately pinned official page visibly links OA ROOT.

    A link to an event on openagenda.com is not proof of delegation of an
    entire agenda; href must be the canonical agenda root. The textual cue
    must be visible on the page, on that exact anchor.
    """
    if (not isinstance(reviewed_source, dict)
            or set(reviewed_source) != {
                "institution_host", "exact_page_url",
                "agenda_slug", "agenda_uid", "timezone"}
            or not isinstance(fetched_page, dict)
            or set(fetched_page) != {"url", "html"}):
        return _result()
    host = reviewed_source.get("institution_host")
    exact_url = reviewed_source.get("exact_page_url")
    reviewed_agenda = {
        k: reviewed_source.get(k)
        for k in ("agenda_slug", "agenda_uid", "timezone")
    }
    if (not isinstance(host, str) or _url(exact_url, host=host) is None
            or not _calendar_review(reviewed_agenda)
            or fetched_page.get("url") != exact_url):
        return _result()
    html = fetched_page.get("html")
    if not isinstance(html, str) or not 50 <= len(html) <= MAX_HTML:
        return _result("institutional_page_unavailable")
    parser = _VisibleAnchors()
    try:
        parser.feed(html)
        parser.close()
    except (TypeError, ValueError):
        return _result("institutional_page_unavailable")
    for target, label in parser.links:
        if (isinstance(label, str) and len(label) <= 500
                and CUE.search(norm_text(label))
                and _root_link(target, reviewed_agenda["agenda_slug"])):
            return dict(
                _result("visible_root_link_observed_not_ownership"),
                institutional_root_link_observed=True,
            )
    return _result("no_visible_exact_root_link")


def redacted_agenda_reference(result):
    """Do not expose institution, URL, slug, UID or arbitrary input reasons."""
    reason = result.get("reason") if isinstance(result, dict) else None
    return {
        "schema": SCHEMA,
        "reason": reason if reason in SAFE_REASONS
                  else "unreviewed_institutional_agenda",
        "contains_private_identifiers": False,
        "institutional_root_link_observed": (
            isinstance(result, dict)
            and result.get("institutional_root_link_observed") is True),
        "independently_attested_owner": False,
        "event_session_verified": False,
        "approval_granted": False,
        "publisher_connected": False,
        "public_writes": 0,
    }


def diagnose_delegated_calendar_candidate(case, reviewed_source,
                                          fetched_institution_page, today,
                                          trusted_api_context=None):
    """Separately verify the institutional link, geo and direct OA event.

    Crucial: this is NOT the existing session proof. A calendar hyperlink
    alone does NOT independently authenticate a particular session, even
    if a v2 API record exists and agrees with the candidate.
    """
    from datetime import date
    from ptitesondes_openagenda_v2_geo_bridge import review_independent_geo
    from ptitesondes_openagenda_v2_direct_evidence import review_direct_v2

    base = {
        "schema": "ptitesondes.oa2.calendar_reference_joined_readonly.v1",
        "stage": "invalid_case",
        "institutional_calendar_link_observed": False,
        "venue_verified": False,
        "direct_source_verified": False,
        "organizer_ownership_attested": False,
        "independent_event_session_verified": False,
        "approval_granted": False,
        "publisher_connected": False,
        "public_writes": 0,
        "outstanding_gates": [
            "institutional_ownership", "event_session_independent_proof",
            "rights_and_reuse", "audience_age_and_access",
            "historical_deduplication", "editorial_category",
            "final_private_approval", "publisher_and_visibility",
        ],
    }
    expected = frozenset({
        "lead", "api_event", "reviewed_venue_source", "venue_page",
        "geocoder_request_url", "geojson",
    })
    if (type(today) is not date or not isinstance(case, dict)
            or set(case) != expected or not isinstance(reviewed_source, dict)):
        return base
    link = inspect_institutional_agenda_page(
        reviewed_source, fetched_institution_page)
    if link["institutional_root_link_observed"] is not True:
        return dict(base, stage="institutional_agenda_link_not_confirmed")
    # The standalone OA API body does not independently attest which URL
    # was used to fetch it. A separately trusted private reader must bind
    # its successful exact GET /v2/agendas/{agendaUID}/events/{eventUID}.
    # The intake candidate must NEVER manufacture this context.
    from ptitesondes_openagenda_v2_direct_evidence import API_ORIGIN, _uid
    lead_uid = case.get("lead", {}).get("external_id")
    selected_agenda_uid = reviewed_source.get("agenda_uid")
    if (not isinstance(trusted_api_context, dict)
            or set(trusted_api_context) != {
                "agenda_uid", "event_uid", "response_url",
                "method", "status", "key_kind"}
            or not _uid(trusted_api_context.get("agenda_uid"))
            or not _uid(trusted_api_context.get("event_uid"))
            or str(trusted_api_context["agenda_uid"]) != str(selected_agenda_uid)
            or str(trusted_api_context["event_uid"]) != str(lead_uid)
            or trusted_api_context.get("response_url") != (
                API_ORIGIN + "/v2/agendas/" + str(selected_agenda_uid)
                + "/events/" + str(lead_uid))
            or trusted_api_context.get("method") != "GET"
            or type(trusted_api_context.get("status")) is not int
            or trusted_api_context["status"] != 200
            or trusted_api_context.get("key_kind") != "public_read_only"):
        return dict(base, stage="direct_api_request_not_independently_bound",
                    institutional_calendar_link_observed=True)
    try:
        geo = review_independent_geo(
            case["lead"], case["api_event"], case["reviewed_venue_source"],
            case["venue_page"], case["geocoder_request_url"], case["geojson"])
        if geo.get("geo_evidence_consistent") is not True:
            return dict(base, stage="independent_venue_not_verified",
                        institutional_calendar_link_observed=True)
        reviewed_agenda = {
            k: reviewed_source[k]
            for k in ("agenda_slug", "agenda_uid", "timezone")
        }
        direct = review_direct_v2(
            case["lead"], case["api_event"], reviewed_agenda,
            geo["registered_venue"], today)
        if direct.get("source_evidence_structurally_valid") is not True:
            return dict(
                base, stage="direct_openagenda_event_not_verified",
                institutional_calendar_link_observed=True,
                venue_verified=True)
        if direct.get("event_kind") != "single_explicit_dated_occurrence":
            return dict(
                base, stage="multi_day_grouping_required",
                institutional_calendar_link_observed=True,
                venue_verified=True, direct_source_verified=True)
        return dict(
            base, stage="calendar_referenced_but_event_proof_pending",
            institutional_calendar_link_observed=True,
            venue_verified=True, direct_source_verified=True)
    except (TypeError, ValueError, KeyError, OverflowError, OSError):
        return dict(base, stage="invalid_case")
