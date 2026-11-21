"""Open-world PRIVATE publication-readiness diagnostics, NOT a publisher.

Wires three-source exact-session RESEARCH (#597) to the existing factory-only
geographic proof, including public squares and streets without house numbers
(#541), and open editorial proposals. No city, venue, organizer, agenda, host,
format or category whitelist is used at discovery or triage. A proposed
category is *never* a prerequisite to researching a new activity.

Even after all recorded claims and coordinates match, authorship, reuse
rights, attendee access, trusted deduplication and editorial approval remain
distinct gates. This module writes no data, creates no patch and cannot mint
any geographic proof from caller-supplied flags or coordinates.
"""
from collections import Counter
from datetime import date, datetime
import math

from proof import norm
from ptitesondes_candidate_promotion import category_for
from ptitesondes_family_activity_classification import (
    ADULT_ONLY, AUDIENCE, propose_family_activity,
)
from ptitesondes_independent_municipal_event_research import (
    corroborate_municipal_event_claims, SCHEMA as TRIPLE_SCHEMA,
)
from ptitesondes_unlisted_exact_session_research import _interval
from ptitesondes_openagenda_v2_direct_evidence import (
    read_direct_v2,
)
from ptitesondes_openagenda_national_event_research import _french_text
from ptitesondes_shared_venue_location_evidence import (
    location_from_proof,
)
from ptitesondes_open_world_municipal_bootstrap import _safe_research_lead
from ptitesondes_openagenda_reuse_rights import review_event_rights

SCHEMA = "ptitesondes.open_world_admission_diagnostics.v1"
MAX_CATALOGUE_ROWS = 100000
MAX_SESSIONS = 800

def _blank(reason):
    return {
        "schema": SCHEMA, "status": reason,
        "live_source_rechecked": False,
        "geography_status": "location_independent_proof_pending",
        "editorial_status": "editorial_scope_review_pending",
        "editorial_category_proposal": None,
        "source_family_audience_explicit": False,
        "source_claimed_adults_only": False,
        "private_session_diagnostics": [],
        "source_catalogue_duplicate_hints": 0,
        "organizer_independently_identified": False,
        "organizer_authorship_proven": False,
        "source_reuse_rights_verified": False,
        # OA's per-event Etalab license is actionable only for factual fields,
        # not for unknown author / image / descriptive text permissions.
        "oa_factual_reuse_open_license": False,
        "oa_licensor_attribution": None,
        "oa_source_updated_at": None,
        "oa_attribution_display": None,
        "public_attendance_verified": False,
        "independent_cancellation_watch_active": False,
        "historical_duplicate_check_authoritative": False,
        "final_editorial_admission_authorized": False,
        "publication_ready": False,
        "publisher_connected": False,
        "public_writes": 0,
    }


def _live_coords(event):
    if not isinstance(event, dict):
        return None
    loc = event.get("location")
    if not isinstance(loc, dict):
        return None
    lat, lon = loc.get("latitude"), loc.get("longitude")
    if (type(lat) not in (float, int) or type(lon) not in (float, int)
            or not math.isfinite(lat) or not math.isfinite(lon)
            or not -90 <= lat <= 90 or not -180 <= lon <= 180):
        return None
    return lat, lon


def _possible_duplicates(lead, intervals, published_snapshot):
    """Untrusted read-only hint. Never certify absence of duplicates.

    Conservative title/city/venue/day match because older public events may
    combine several times in one daily or range record. A distinct time is
    NOT assumed free merely because the historic time field differs.
    """
    if (not isinstance(published_snapshot, list)
            or len(published_snapshot) > MAX_CATALOGUE_ROWS):
        return set()
    expected = (norm(lead["title"]), norm(lead.get("city_unverified")),
                norm(lead.get("venue_unverified")))
    if not all(expected):
        return set()
    dates = {datetime.fromisoformat(item["begin"]).date()
             for item in intervals}
    possible = set()
    for record in published_snapshot:
        if not isinstance(record, dict):
            continue
        record_identity = (
            norm(record.get("title")), norm(record.get("city")),
            norm(record.get("venue")))
        if record_identity != expected:
            continue
        try:
            first = date.fromisoformat(record["date_start"])
            last = date.fromisoformat(record.get("date_end", record["date_start"]))
        except (TypeError, KeyError, ValueError):
            continue
        if first <= last:
            possible.update(d for d in dates if first <= d <= last)
    return possible


def inspect_open_world_candidate(
        lead, municipality_url, organizer_url, public_oa_key, today, *,
        location_proof=None, public_catalogue_snapshot=None,
        oa_event_reader=read_direct_v2, oa_agenda_reader=None,
        dila_reader=None, municipal_html_reader=None,
        organizer_html_reader=None):
    """Re-execute authoritative reads, preserve each exact local session.

    All domain and event evidence is revalidated via the #597 provider path.
    Location is accepted ONLY as an in-memory, factory-minted proof; no
    JSON/dictionary or source-provided 'verified' boolean is trusted.
    """
    if (not _safe_research_lead(lead, today)
            or type(today) is not date
            or not callable(oa_event_reader)
            or (public_catalogue_snapshot is not None and
                (not isinstance(public_catalogue_snapshot, list)
                 or len(public_catalogue_snapshot) > MAX_CATALOGUE_ROWS))):
        return _blank("invalid_private_candidate")
    intervals = lead["explicit_source_session_intervals"]
    pairs = [(item["begin"], item["end"]) for item in intervals]
    if (len(pairs) > MAX_SESSIONS
            or len(set(pairs)) != len(pairs)
            or any(_interval(slot) is None for slot in intervals)):
        return _blank("invalid_private_candidate_sessions")
    captured = []

    def read_live_event(uid, eid, key):
        event = oa_event_reader(uid, eid, key)
        captured.append(event)
        return event

    kwargs = {"oa_event_reader": read_live_event}
    if oa_agenda_reader is not None:
        kwargs["oa_agenda_reader"] = oa_agenda_reader
    if dila_reader is not None:
        kwargs["directory_reader"] = dila_reader
    if municipal_html_reader is not None:
        kwargs["municipal_html_reader"] = municipal_html_reader
    if organizer_html_reader is not None:
        kwargs["external_html_reader"] = organizer_html_reader

    # Even a forged triple-source report supplied by intake cannot cross the
    # boundary: re-fetch OA/DILA/municipal/third-party live from here.
    claims = corroborate_municipal_event_claims(
        lead, municipality_url, organizer_url, public_oa_key, today, **kwargs)
    if (not isinstance(claims, dict) or
            claims.get("schema") != TRIPLE_SCHEMA or
            claims.get("publication_ready") is not False or
            claims.get("public_writes") != 0):
        return _blank("invalid_private_cross_source_evidence")
    result = _blank("private_cross_source_admission_diagnostic_only")
    result["live_source_rechecked"] = bool(captured)
    result["cross_source_status"] = claims["status"]
    event = captured[-1] if captured else None
    if (not isinstance(event, dict)
            or type(event.get("uid")) is not int
            or event["uid"] != lead["event_uid"]):
        return dict(result, status="live_oa_event_not_verified")

    rights = review_event_rights(event, today)
    if rights["licensed_factual_reuse_confirmed"]:
        result["oa_factual_reuse_open_license"] = True
        result["oa_licensor_attribution"] = rights["licensor_attribution"]
        result["oa_source_updated_at"] = rights["source_updated_at"]
        result["oa_attribution_display"] = rights["attribution_display"]

    title = _french_text(event, "title")
    description = (_french_text(event, "description") + " "
                   _french_text(event, "longDescription")).strip()
    body = norm(title + " " + description)
    result["source_claimed_adults_only"] = bool(ADULT_ONLY.search(body))
    result["source_family_audience_explicit"] = (
        bool(AUDIENCE.search(body)) and
        not result["source_claimed_adults_only"])
    musical = category_for(title, description)
    family = propose_family_activity(title, description)
    category = (musical if musical else
                ((family["category_proposal"],
                  family["category_label_proposal"])
                 if family["category_proposal"] else None))
    if result["source_claimed_adults_only"]:
        result["editorial_status"] = "explicit_adult_only_not_family"
    elif category is not None:
        result["editorial_category_proposal"] = {
            "category": category[0], "label": category[1]}
        result["editorial_status"] = "recognized_activity_proposal_not_admission"
    else:
        result["editorial_status"] = "new_activity_needs_editorial_research"

    source_point = _live_coords(event)
    if source_point is not None and location_proof is not None:
        # Prevent fake provenance: only VenueLocationProof with the internal
        # minting seal is accepted; ALSO require independent OA point agreement.
        loc = location_from_proof(
            location_proof, lead.get("city_unverified"),
            lead.get("venue_unverified"), today, source_point)
        result["geography_status"] = (
            "independent_named_location_correlated"
            if loc is not None else
            "location_proof_missing_stale_or_conflicting")

    triples = {(item["begin"], item["end"]) for item in
               claims.get("triple_corresponding_sessions_private", [])
               if (isinstance(item, dict)
                   and isinstance(item.get("begin"), str)
                   and isinstance(item.get("end"), str))}
    possible = _possible_duplicates(
        lead, intervals, public_catalogue_snapshot)
    result["source_catalogue_duplicate_hints"] = len(possible)
    for slot in intervals:
        key = (slot["begin"], slot["end"])
        matches = key in triples
        blockers = [
            "organizer_identity_and_authorship_unproven",
            "source_reuse_rights_unreviewed",
            "family_access_and_age_not_independently_verified",
            "no_authoritative_public_deduplication",
            "final_editorial_admission_not_granted",
            "no_publisher_bridge",
        ]
        if not matches:
            blockers.append("exact_cross_source_session_not_confirmed")
        if result["geography_status"] != "independent_named_location_correlated":
            blockers.append("independent_location_research_needed")
        if result["editorial_status"] != "recognized_activity_proposal_not_admission":
            blockers.append("editorial_activity_requires_review")
        if result["source_claimed_adults_only"]:
            blockers.append("source_explicitly_adult_only")
        if datetime.fromisoformat(slot["begin"]).date() in possible:
            blockers.append("potential_public_duplicate_requires_recheck")
        result["private_session_diagnostics"].append({
            "begin": key[0], "end": key[1],
            "three_source_exact_claims": matches,
            "independently_correlated_location": (
                result["geography_status"] ==
                "independent_named_location_correlated"),
            "publication_blockers": sorted(set(blockers)),
            "publication_ready": False,
            "public_writes": 0,
        })
    return result


def public_redacted_admission_summary(results):
    """Only fixed status codes and counts, never title, URL or session date."""
    if not isinstance(results, list) or len(results) > 100:
        raise ValueError("invalid_private_admission_reports")
    statuses = Counter()
    sessions = 0
    for item in results:
        if (not isinstance(item, dict) or item.get("schema") != SCHEMA
                or item.get("publication_ready") is not False
                or item.get("publisher_connected") is not False
                or item.get("public_writes") != 0
                or item.get("organizer_authorship_proven") is not False
                or item.get("source_reuse_rights_verified") is not False
                or item.get("final_editorial_admission_authorized") is not False
                or item.get("status") not in {
                    "invalid_private_candidate",
                    "invalid_private_candidate_sessions",
                    "invalid_private_cross_source_evidence",
                    "private_cross_source_admission_diagnostic_only",
                    "live_oa_event_not_verified"}):
            raise ValueError("invalid_admission_report")
        n = len(item.get("private_session_diagnostics", []))
        if n > MAX_SESSIONS:
            raise ValueError("invalid_private_session_count")
        sessions += n
        statuses[item["status"]] += 1
    return {
        "schema": SCHEMA + ".aggregate",
        "candidates": len(results), "sessions_examined": sessions,
        "status_counts": dict(sorted(statuses.items())),
        "publication_ready": False, "publisher_connected": False,
        "public_writes": 0,
    }
