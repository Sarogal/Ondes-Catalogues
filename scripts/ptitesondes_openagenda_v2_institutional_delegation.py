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
            or set(case) != expected or not isinstance(reviewed_source, dict)
            or not isinstance(case.get("lead"), dict)
            or not isinstance(case.get("api_event"), dict)):
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


# Registry selection is by reviewed agenda SLUG, never by event title,
# claimed organizer, untrusted search snippet or candidate-supplied site URL.
MAX_REVIEWED_INSTITUTIONS = 500
MAX_BACKLOG = 4000


def _registry_by_slug(reviewed_sources):
    """Validate trusted pins. Never resolve a conflicting slug automatically."""
    if (not isinstance(reviewed_sources, list)
            or len(reviewed_sources) > MAX_REVIEWED_INSTITUTIONS):
        raise ValueError("invalid_trusted_institution_registry")
    registry = {}
    for source in reviewed_sources:
        if (not isinstance(source, dict) or set(source) != {
                "institution_host", "exact_page_url", "agenda_slug",
                "agenda_uid", "timezone"}):
            raise ValueError("invalid_trusted_institution_registry")
        agenda = {k: source[k] for k in (
            "agenda_slug", "agenda_uid", "timezone")}
        if (not isinstance(source["institution_host"], str)
                or _url(source["exact_page_url"],
                        host=source["institution_host"]) is None
                or not _calendar_review(agenda)):
            raise ValueError("invalid_trusted_institution_registry")
        slug = source["agenda_slug"]
        registry.setdefault(slug, []).append(source)
    return registry


def select_pinned_agenda_for_lead(lead, reviewed_sources):
    """Return a private registry pin, never an approval or public datum.

    A lead may identify the agenda by *its strict OA URL* but can never choose
    the institution host or an unofficial agenda. Duplicates/ambiguity HOLD.
    """
    from ptitesondes_openagenda_v2_direct_evidence import _source_parts
    registry = _registry_by_slug(reviewed_sources)
    return _select_indexed_lead(lead, registry)



def _legacy_mirror_slug(url):
    """Parse only exact https://openagenda.com/{slug}/events/{event-slug}.

    This is a discovery pointer, NEVER an OA direct-source proof. A legacy
    title slug has no immutable event UID in its path, so the client must
    authenticate the UID through the public OA v2 endpoint separately.
    """
    from urllib.parse import urlsplit
    from ptitesondes_openagenda_v2_direct_evidence import SLUG
    if not isinstance(url, str) or len(url) > 700:
        return None
    try:
        u = urlsplit(url)
        if (u.scheme != "https" or u.hostname != "openagenda.com"
                or u.port not in (None, 443) or u.username or u.password
                or u.query or u.fragment):
            return None
        parts = u.path.strip("/").split("/")
        if parts and parts[0] in ("fr", "en"):
            parts = parts[1:]
        if (len(parts) != 3 or parts[1] != "events"
                or SLUG.fullmatch(parts[0]) is None
                or SLUG.fullmatch(parts[2]) is None):
            return None
        if re.match(r"^[0-9]{1,12}_", parts[2]):
            return None
        return parts[0]
    except ValueError:
        return None


def _select_indexed_lead(lead, index):
    from ptitesondes_openagenda_v2_direct_evidence import _source_parts
    if not isinstance(lead, dict):
        return "lead_identity_invalid", None
    identity = _source_parts(lead.get("source_url"))
    raw_uid = lead.get("external_id")
    if identity is None:
        from ptitesondes_openagenda_v2_direct_evidence import _uid
        legacy = _legacy_mirror_slug(lead.get("source_url"))
        if (legacy is not None and _uid(raw_uid)
                and lead.get("collector") == "opendatasoft-index"):
            # Retain its exact original source URL. It is NOT an approved
            # source; a separately bound OA v2 API check is mandatory.
            return "legacy_ods_mirror_needs_authenticated_api_bridge", None
        return "lead_identity_invalid", None
    if not isinstance(raw_uid, str) or raw_uid != identity[1]:
        return "lead_identity_invalid", None
    rows = index.get(identity[0], [])
    if not rows:
        return "no_independently_curated_institution", None
    if len(rows) != 1:
        return "institution_registry_ambiguous", None
    return "institution_pin_selected_for_verification_only", rows[0]


def census_institution_pins_on_private_backlog(leads, reviewed_sources,
                                               today):
    """Read-only aggregate of which leads can reach institution-page checks.

    Intended for execution in a private trusted process, not for publishing
    raw lead data to public Actions. No network, selectors or approval flags.
    """
    from collections import Counter
    from datetime import date, timedelta
    if (type(today) is not date or not isinstance(leads, list)
            or len(leads) > MAX_BACKLOG):
        raise ValueError("invalid_private_backlog")
    index = _registry_by_slug(reviewed_sources)
    counts = Counter()
    # These are provided reviewed pins, NOT verified site ownership or licences.
    counts["reviewed_registry_rows_provided"] = len(reviewed_sources)
    counts["reviewed_registry_distinct_slugs"] = len(index)
    cutoff = today + timedelta(days=184)
    for lead in leads:
        counts["raw_rows"] += 1
        if not isinstance(lead, dict):
            counts["malformed_rows"] += 1
            continue
        day = lead.get("date_start")
        try:
            when = date.fromisoformat(day)
            if when.isoformat() != day:
                raise ValueError("noncanonical")
        except (ValueError, TypeError):
            counts["invalid_or_missing_date"] += 1
            continue
        if when < today:
            counts["expired_rows"] += 1
            continue
        if when > cutoff:
            counts["outside_horizon_rows"] += 1
            continue
        counts["future_in_window_rows"] += 1
        reason, _ = _select_indexed_lead(lead, index)
        counts[reason] += 1
        if reason == "legacy_ods_mirror_needs_authenticated_api_bridge":
            # The old mirror can be inventoried by slug, but cannot be
            # promoted until a trusted reader binds agenda and event UIDs.
            pins = index.get(_legacy_mirror_slug(lead.get("source_url")), ())
            if len(pins) == 1:
                counts["legacy_ods_single_pin_for_review_only"] += 1
            elif len(pins) > 1:
                counts["legacy_ods_ambiguous_pins_held"] += 1
            else:
                counts["legacy_ods_no_independent_pin"] += 1
    return {
        "schema": "ptitesondes.oa2.institution_pin_private_census.v1",
        "mode": "private_read_only_aggregate_no_source_approval",
        "counts": dict(sorted(counts.items())),
        "contains_private_identifiers": False,
        "institutional_ownership_attested": False,
        "official_session_proved": False,
        "rights_reviewed": False,
        "approval_granted": False,
        "publisher_connected": False,
        "public_writes": 0,
    }


def diagnose_legacy_ods_authenticated_mapping(lead, reviewed_source,
                                               api_event, trusted_api_context):
    """Bridge a slug-only ODS mirror to EXACT verified OA API identity only.

    Neither the mirror URL nor its slug is rewritten or offered to the
    publisher. It remains a candidate pointer until a separate, trusted
    API reader has fetched the event UID within the independently curated
    agenda UID. All source/venue/time/age/rights gates remain outstanding.
    """
    from ptitesondes_openagenda_v2_direct_evidence import (
        API_ORIGIN, _uid, _norm, _fr,
    )
    base = {
        "schema": "ptitesondes.oa2.legacy_ods_authenticated_identity.v1",
        "stage": "invalid_or_unreviewed_legacy_pointer",
        "api_event_identity_bound_for_review": False,
        "canonical_source_url_verified": False,
        "institutional_ownership_attested": False,
        "independent_venue_verified": False,
        "independent_event_sessions_verified": False,
        "rights_reviewed": False,
        "approval_granted": False,
        "publisher_connected": False,
        "public_writes": 0,
    }
    if (not isinstance(lead, dict)
            or lead.get("collector") != "opendatasoft-index"
            or not isinstance(reviewed_source, dict)
            or set(reviewed_source) != {
                "institution_host", "exact_page_url", "agenda_slug",
                "agenda_uid", "timezone"}
            or not isinstance(reviewed_source.get("institution_host"), str)
            or _url(reviewed_source.get("exact_page_url"),
                    host=reviewed_source["institution_host"]) is None
            or not _calendar_review({
                key: reviewed_source.get(key)
                for key in ("agenda_slug", "agenda_uid", "timezone")})
            or _legacy_mirror_slug(lead.get("source_url"))
            != reviewed_source["agenda_slug"]):
        return base
    source_uid = lead.get("external_id")
    if not _uid(source_uid):
        return base
    reviewed_uid = reviewed_source["agenda_uid"]
    if (not isinstance(trusted_api_context, dict)
            or set(trusted_api_context) != {
                "agenda_uid", "event_uid", "response_url",
                "method", "status", "key_kind"}
            or str(trusted_api_context.get("agenda_uid")) != str(reviewed_uid)
            or str(trusted_api_context.get("event_uid")) != str(source_uid)
            or trusted_api_context.get("response_url") != (
                API_ORIGIN + "/v2/agendas/" + str(reviewed_uid)
                + "/events/" + str(source_uid))
            or trusted_api_context.get("method") != "GET"
            or type(trusted_api_context.get("status")) is not int
            or trusted_api_context["status"] != 200
            or trusted_api_context.get("key_kind") != "public_read_only"):
        return dict(base, stage="api_event_request_not_independently_bound")
    if (not isinstance(api_event, dict)
            or not _uid(api_event.get("uid"))
            or str(api_event["uid"]) != str(source_uid)):
        return dict(base, stage="api_event_uid_not_concordant")
    if (not _norm(_fr(api_event, "title"))
            or _norm(_fr(api_event, "title")) != _norm(lead.get("title"))):
        return dict(base, stage="api_event_title_not_concordant")
    place = api_event.get("location")
    if (not isinstance(place, dict) or
            _norm(place.get("adminLevel4")) != _norm(lead.get("city")) or
            _norm(place.get("name")) != _norm(lead.get("venue")) or
            not _norm(lead.get("venue")) or not _norm(lead.get("city"))):
        return dict(base, stage="api_event_place_identity_not_concordant")
    return dict(
        base, stage="legacy_identity_api_bound_other_gates_pending",
        api_event_identity_bound_for_review=True)
