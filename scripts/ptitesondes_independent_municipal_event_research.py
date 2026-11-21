"""PRIVATE corroboration: OpenAgenda + DILA-attested municipality + new source.

A visible municipal link alone is NOT an event citation, and a second host
alone is NOT independent provenance. Require that the DILA-attested municipal
page visibly link to the new source AND independently publish JSON-LD Event
records for exact showtimes. Re-read the OA API and third-party source via
the existing isolated verifier before recording matching *claims*.

The municipality may syndicate OpenAgenda. Therefore the result is never an
attestation of independent authorship, organizer ownership, reuse rights,
age/access, geometry or publishability. No curated host/venue/organizer list.
"""
from datetime import date
from urllib.parse import urlsplit

from ptitesondes_dila_municipal_domains import (
    approved_municipal_page_host, fetch_dila,
)
from ptitesondes_dynamic_municipal_source_links import (
    _safe_url, scan_municipal_page, SCHEMA as LINKS_SCHEMA,
)
from ptitesondes_open_world_municipal_bootstrap import _safe_research_lead
from ptitesondes_unlisted_exact_session_research import (
    _structured_source_sessions, _interval, review_unlisted_exact_sessions,
)
from ptitesondes_openagenda_v2_direct_evidence import _valid_public_read_key
from ptitesondes_unlisted_source_safe_recheck import read_unknown_https

SCHEMA = "ptitesondes.municipal_triple_claims_research.v1"
MAX_MUNICIPAL_LINK_BATCHES = 75  # 3000 explicit links / 40 per source page


def _blank(status):
    return {
        "schema": SCHEMA, "status": status,
        "municipal_program_exact_claims_count": 0,
        "third_party_exact_claims_count": 0,
        "triple_corresponding_session_count": 0,
        "triple_corresponding_sessions_private": [],
        "municipal_source_link_confirmed": False,
        "municipal_page_host_correlated_with_live_dila": False,
        "organizer_domain_independently_owned": False,
        "source_authors_proved_independent": False,
        "source_rights_reviewed": False,
        "family_access_verified": False,
        "venue_geography_verified": False,
        "editorial_scope_verified": False,
        "publication_ready": False, "publisher_connected": False,
        "approval_granted": False, "public_writes": 0,
    }


def _municipal_links_candidate(city, directory, page_url, html, candidate):
    """Full bounded scan, not just first 40 anchors on the official page."""
    cursor = None
    checked = 0
    found = None
    while checked < MAX_MUNICIPAL_LINK_BATCHES:
        page = scan_municipal_page(
            city, directory, {"url": page_url, "html": html},
            cursor=cursor)
        if page["status"] != "private_source_link_research_only":
            return None
        checked += 1
        for item in page["source_candidates"]:
            if item["url"] == candidate:
                found = item
        cursor = page["next_cursor"]
        if cursor is None:
            break
    if cursor is not None or found is None:
        return None
    return {
        "schema": LINKS_SCHEMA,
        "status": "private_source_link_research_only",
        "municipal_domain_confirmed_by_dila": True,
        "candidate_domains_officially_approved": False,
        "source_candidates": [found],
    }


def corroborate_municipal_event_claims(
        lead, municipality_page, discovered_url, oa_public_key, today, *,
        directory_reader=fetch_dila,
        municipal_html_reader=read_unknown_https,
        external_html_reader=read_unknown_https,
        oa_agenda_reader=None, oa_event_reader=None):
    """Compare exact OA start/end against TWO web pages, without admission."""
    unverified = _blank("unverified_or_incomplete_research_source")
    if (not _safe_research_lead(lead, today)
            or not _valid_public_read_key(oa_public_key)
            or not isinstance(lead.get("city_unverified"), str)
            or not _safe_url(municipality_page)
            or not _safe_url(discovered_url)
            or urlsplit(municipality_page).hostname
               == urlsplit(discovered_url).hostname
            or not all(callable(x) for x in (
                directory_reader, municipal_html_reader,
                external_html_reader))
            or (oa_agenda_reader is not None
                and not callable(oa_agenda_reader))
            or (oa_event_reader is not None
                and not callable(oa_event_reader))):
        return unverified
    city = lead["city_unverified"]
    try:
        directory = directory_reader(city)
    except (OSError, ValueError, TypeError, KeyError, TimeoutError):
        return _blank("municipal_directory_unavailable")
    if approved_municipal_page_host(
            municipality_page, city, directory) is None:
        return _blank("municipal_page_not_correlated_with_dila")
    try:
        html = municipal_html_reader(municipality_page)
        links = _municipal_links_candidate(
            city, directory, municipality_page, html, discovered_url)
    except (OSError, ValueError, TypeError, KeyError, TimeoutError,
            UnicodeError, RecursionError):
        return _blank("municipal_program_page_unavailable")
    if links is None:
        return _blank("municipal_page_no_exact_source_link")
    out = _blank("municipal_reference_link_only")
    out["municipal_page_host_correlated_with_live_dila"] = True
    out["municipal_source_link_confirmed"] = True
    pairs = [(i["begin"], i["end"])
             for i in lead["explicit_source_session_intervals"]]
    if (len(pairs) != len(set(pairs))
            or any(_interval(i) is None
                   for i in lead["explicit_source_session_intervals"])):
        return _blank("invalid_private_source_sessions")
    try:
        municipal_claims = _structured_source_sessions(
            html, lead, pairs)
    except (ValueError, TypeError, KeyError, RecursionError):
        return _blank("invalid_municipal_program_evidence")
    municipal_intervals = {
        (x["begin"], x["end"])
        for x in municipal_claims["exact_source_session_intervals"]}
    out["municipal_program_exact_claims_count"] = len(municipal_intervals)
    if not municipal_intervals:
        out["status"] = "municipal_link_but_no_exact_program_session"
        return out

    review_kwargs = {
        "source_reader": external_html_reader,
    }
    if oa_agenda_reader is not None:
        review_kwargs["agenda_reader"] = oa_agenda_reader
    if oa_event_reader is not None:
        review_kwargs["event_reader"] = oa_event_reader
    source = review_unlisted_exact_sessions(
        lead, links, discovered_url, oa_public_key, today, **review_kwargs)
    out["third_party_exact_claims_count"] = (
        source["source_exact_session_count"])
    if source["status"] != "structured_source_exact_sessions_research_only":
        out["status"] = "oa_or_third_party_claims_not_current"
        return out
    external_intervals = {
        (x["begin"], x["end"])
        for x in source["source_sessions_claimed_not_independent"]}
    triple = municipal_intervals & external_intervals
    out["triple_corresponding_sessions_private"] = [
        {"begin": a, "end": b} for a, b in pairs if (a, b) in triple]
    out["triple_corresponding_session_count"] = len(triple)
    out["status"] = (
        "three_sites_same_exact_session_claims_research_only"
        if triple else "no_shared_exact_claimed_session")
    return out


def public_redacted_municipal_event_summary(result):
    """Only counts and fixed statuses, never named organizers or showtimes."""
    allowed = {
        "unverified_or_incomplete_research_source",
        "municipal_directory_unavailable",
        "municipal_page_not_correlated_with_dila",
        "municipal_program_page_unavailable",
        "municipal_page_no_exact_source_link",
        "municipal_reference_link_only",
        "invalid_private_source_sessions",
        "invalid_municipal_program_evidence",
        "municipal_link_but_no_exact_program_session",
        "oa_or_third_party_claims_not_current",
        "three_sites_same_exact_session_claims_research_only",
        "no_shared_exact_claimed_session",
    }
    if (not isinstance(result, dict) or result.get("schema") != SCHEMA
            or result.get("status") not in allowed
            or result.get("publisher_connected") is not False
            or result.get("publication_ready") is not False
            or result.get("public_writes") != 0
            or type(result.get("triple_corresponding_session_count"))
               is not int
            or not 0 <= result["triple_corresponding_session_count"] <= 800
            or result.get("organizer_domain_independently_owned") is not False
            or result.get("source_authors_proved_independent") is not False
            or result.get("source_rights_reviewed") is not False):
        raise ValueError("invalid_private_municipal_claims_report")
    return {
        "schema": SCHEMA + ".aggregate", "status": result["status"],
        "claim_matches": result["triple_corresponding_session_count"],
        "publisher_connected": False, "publication_ready": False,
        "public_writes": 0,
    }
