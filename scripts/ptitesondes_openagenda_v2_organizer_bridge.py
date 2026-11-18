"""Generic, read-only first-party organizer session cross-check for OA v2.

Inputs MUST be from distinct trust domains:
- OpenAgenda v2 event and source proof from the OA API;
- independently reviewed organizer host + exact official URL in a registry;
- HTML fetched from that exact URL without redirects by a trusted caller.

This neither approves nor writes an event. An institutional HTML page can prove
an exact dated session even if it does not link to the root OA agenda; this
avoids per-event allowlist exceptions while preserving evidence requirements.
"""
from datetime import date
import re
from urllib.parse import urlsplit

from ptitesondes_family_national_source_preflight import (
    _session_pair_on_official_page, _source_cues, official_host, norm_text,
)

SCHEMA = "ptitesondes.oa2.independent_organizer_session.v1"
OA_SOURCE_SCHEMA = "ptitesondes.openagenda_v2_direct_source_evidence.v1"
FORBIDDEN_HOSTS = frozenset((
    "openagenda.com", "www.openagenda.com", "api.openagenda.com",
    "public.opendatasoft.com",
))
# A child-looking title must NEVER outweigh an explicit first-party
# adult-only statement. Check visible text, not hidden HTML/script noise.
ADULT_ONLY = re.compile(
    r"\b(?:reserve aux adultes|adultes? uniquement|public adultes?"
    r"|interdit aux enfants|sans enfants|18 ans et plus"
    r"|a partir de 18 ans)\b"
)



def _safe_url(url):
    if not isinstance(url, str) or len(url) > 1800:
        return None
    try:
        p = urlsplit(url)
        if (p.scheme != "https" or not p.hostname or p.username or p.password
                or p.port not in (None, 443) or p.fragment):
            return None
        return p
    except ValueError:
        return None


def check_independent_session(lead, api_event, direct_proof, reviewed_organizer,
                              fetched_official_page):
    """Return structural first-party concordance, never organizer *ownership*.

    reviewed_organizer must come from a separately maintained host registry,
    NOT the event, the lead, OpenAgenda rights or a search result alone.
    exact_url is a link actually reviewed under that trusted host. Caller
    must fetch it with bounded size, no redirects, and no API credentials.
    """
    result = {
        "schema": SCHEMA, "mode": "read_only_organizer_session_preflight",
        "official_session_evidence_consistent": False,
        "organizer_ownership_attested": False,
        "rights_reviewed": False, "age_access_fully_verified": False,
        "publisher_connected": False, "approval_granted": False,
        "public_writes": 0, "reason": "missing_or_untrusted_inputs",
    }
    def fail(reason):
        return dict(result, reason=reason)

    if (not isinstance(lead, dict) or not isinstance(api_event, dict)
            or not isinstance(direct_proof, dict)
            or direct_proof.get("schema") != OA_SOURCE_SCHEMA
            or direct_proof.get("source_evidence_structurally_valid") is not True
            or direct_proof.get("event_kind") != "single_explicit_dated_occurrence"
            or direct_proof.get("approval_granted") is not False
            or direct_proof.get("public_writes") != 0):
        return fail("no_verified_direct_single_day_evidence")
    if (not isinstance(reviewed_organizer, dict)
            or set(reviewed_organizer) != {"approved_host", "exact_url"}
            or not isinstance(fetched_official_page, dict)
            or set(fetched_official_page) != {"url", "html"}):
        return fail("missing_independent_organizer_registry")
    source = _safe_url(reviewed_organizer["exact_url"])
    approved_host = reviewed_organizer["approved_host"]
    if (source is None or not isinstance(approved_host, str)
            or not approved_host or approved_host in FORBIDDEN_HOSTS
            or approved_host.endswith(".openagenda.com")
            or approved_host.endswith(".opendatasoft.com")
            or source.hostname != approved_host
            or official_host(reviewed_organizer["exact_url"]) != approved_host
            or fetched_official_page["url"] != reviewed_organizer["exact_url"]):
        return fail("official_url_not_pinned_to_reviewed_organizer")
    html = fetched_official_page.get("html")
    if not isinstance(html, str) or not 50 <= len(html) <= 500_000:
        return fail("official_page_missing_or_oversized")

    from ptitesondes_family_national_source_preflight import _VisibleText
    visible_parser = _VisibleText()
    try:
        visible_parser.feed(html)
        visible_parser.close()
    except (ValueError, TypeError):
        return fail("official_page_unreadable")
    if ADULT_ONLY.search(norm_text(" ".join(visible_parser.words))):
        return fail("organizer_explicit_adult_only")

    # Exact OA identity/title/venue/timezone is already checked in direct_proof.
    # The first-party source must corroborate each distinct local session time
    # on the selected day, rather than mixing times from different paragraphs.
    times = direct_proof.get("explicit_local_times_for_candidate_day")
    if (not isinstance(times, list) or not 1 <= len(times) <= 20
            or len(set(times)) != len(times)
            or not all(isinstance(t, str) and len(t) == 5 and
                       t[2] == ":" and t[:2].isdigit() and t[3:].isdigit()
                       and 0 <= int(t[:2]) <= 23 and 0 <= int(t[3:]) <= 59
                       for t in times)):
        return fail("unsupported_session_time_count_or_format")
    day = lead.get("date_start")
    try:
        if (not isinstance(day, str)
                or date.fromisoformat(day).isoformat() != day
                or lead.get("date_end") != day):
            return fail("invalid_candidate_day")
    except ValueError:
        return fail("invalid_candidate_day")
    try:
        for clock in times:
            scope = {
                "title": lead["title"], "city": lead["city"],
                "venue": lead["venue"], "date_start": day,
                # Do not conflate exact event metadata age with an organizer
                # confirmation of the same bounds. Age is a separate gate.
                "age_min": None, "age_max": None,
                # Access remains unknown here; explicitly labelled fields
                # are checked separately, never silently interpreted as free.
                "price_evidence": "not_stated",
                "registration_evidence": "not_stated",
            }
            source_row = {"start_local": clock}
            if _source_cues(scope, source_row, html):
                return fail("organizer_title_date_venue_audience_or_status_mismatch")
            if not _session_pair_on_official_page(html, scope, clock):
                return fail("date_and_time_not_confirmed_in_same_visible_block")
    except (KeyError, ValueError, TypeError):
        return fail("source_evidence_malformed")
    return dict(result, official_session_evidence_consistent=True,
                confirmed_local_start_times_count=len(times),
                reason="organizer_session_confirmed_other_gates_pending")


def dry_run_first_party_fallback(ods_state, lead, api_event, direct_proof,
                                 agenda_identity, grouping, reviewed_organizer,
                                 fetched_official_page, historic_uid_exists=None):
    """One read-only bundle: independent first-party proof + ODS-missing route.

    Computes the first-party evidence freshly against the SAME lead and event;
    does not accept a caller-provided 'organizer_verified=True' assertion.
    No admission, publisher patch or website writes can occur here.
    """
    from ptitesondes_openagenda_v2_preintegration import ods_fallback_preflight
    organizer = check_independent_session(
        lead, api_event, direct_proof, reviewed_organizer,
        fetched_official_page,
    )
    return ods_fallback_preflight(
        ods_state, direct_proof, agenda_identity, grouping,
        historic_uid_exists=historic_uid_exists,
        independently_linked=False,
        first_party_session_evidence=organizer,
    )
