"""Generic non-musical family catalogue SHAPE REHEARSAL, read-only.

This is not a publisher, a pre-approval, an event attestation or patch.v1.
The inputs may be untrusted even when named trusted: the rehearsal merely
tests the shape of a hypothetical append-only nonmusical catalogue against
the existing production schema without modifying production code or content.

Each event's exact source, family audience and access are rerun through the
HTML gate router. Venue coordinates are taken only from the *separate* curated
venue registry, and region/department/source_label from a separately supplied
administrative pin. None is considered fresh independent verification.

No event, candidate, URLs, coordinates, approval flags or patch data escape
in output. Every route always remains publication_ready=False.
"""
from copy import deepcopy
from datetime import date
import hashlib
import json
import re
from urllib.parse import urlsplit

from merge_policy import byid, valid
from official_organizer_proof import canonical_event_title
from proof import norm
from ptitesondes_family_national_scope import FAMILY_TYPES, LEGACY_MUSICAL
from ptitesondes_factual_reuse_preflight import prepare_private_html_factual_draft
from ptitesondes_html_independent_venue_geo import _trusted_exact_venue
from ptitesondes_nonmusical_html_gate_router import (
    route_nonmusical_html_session, STAGES,
)

SCHEMA = "ptitesondes.nonmusical_catalogue_shape_dryrun.v1"
MAX_CANDIDATES = 30
MAX_CATALOGUE = 100_000
CLOCK = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d\Z")
ADMIN_KEYS = frozenset(("city", "department", "region", "source_label"))
PACKET_KEYS = frozenset((
    "lead", "page", "trusted_index", "child_prefix",
    "independent_context", "admin_pin",
))
HOLD_CODES = frozenset((
    "invalid_catalogue_or_input",
    "historical_snapshot_not_current",
    "admin_pin_unreviewed_or_invalid",
    "venue_coordinates_not_curated",
    "factual_draft_not_confirmed",
    "schema_structure_incompatible",
    "historical_exact_duplicate",
    "historical_ambiguous_cross_source_collision",
    "hypothetical_shape_valid_but_all_release_proofs_missing",
))
# A route can have a valid structural skeleton even when source usage rights
# are PENDING, EXPIRED, or separately reviewed. This never means admittable.
SHAPE_STAGES = frozenset((
    "institutional_source_policy_pending",
    "institutional_source_policy_expired",
    "institutional_source_policy_restricted",
    "independent_geo_rights_review_required",
))


def _hash(doc):
    return hashlib.sha256(json.dumps(
        doc, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")).hexdigest()


def _private_string(value, maxlen):
    return (
        type(value) is str and value == value.strip()
        and 1 <= len(value) <= maxlen
        and re.search(r"[\x00-\x1f\x7f<>]", value) is None
    )


def _valid_admin(pin, lead):
    return (
        type(pin) is dict and set(pin) == ADMIN_KEYS
        and all(_private_string(pin.get(key), 120) for key in ADMIN_KEYS)
        and norm(pin["city"]) == norm(lead.get("city"))
    )


def _same_day_interval(old, day):
    """Fail closed on malformed historical dates, never guess intervals."""
    if not isinstance(old, dict):
        return None
    a, b = old.get("date_start"), old.get("date_end", old.get("date_start"))
    if not isinstance(a, str) or not isinstance(b, str):
        return None
    try:
        first, last = date.fromisoformat(a), date.fromisoformat(b)
    except ValueError:
        return None
    if (first.isoformat() != a or last.isoformat() != b or first > last):
        return None
    return first <= day <= last


def _collision(proposed, public_and_staged):
    """Exact identity differs from an ambiguous series/organizer collision.

    A *different* confirmed time might be a legitimate second session.
    Until a separate release-stage session replay exists, do not silently
    admit it; hold for explicit verification rather than discard it.
    """
    day = date.fromisoformat(proposed["date_start"])
    for old in public_and_staged:
        if not isinstance(old, dict):
            return "historical_ambiguous_cross_source_collision"
        if old.get("id") == proposed["id"]:
            return "historical_exact_duplicate"
        overlaps = _same_day_interval(old, day)
        if overlaps is None:
            return "historical_ambiguous_cross_source_collision"
        if not overlaps:
            continue
        same_site_event = old.get("source_url") == proposed["source_url"]
        same_place_title = (
            canonical_event_title(old) == canonical_event_title(proposed)
            and norm(old.get("city")) == norm(proposed["city"])
            and norm(old.get("venue")) == norm(proposed["venue"])
        )
        if not same_site_event and not same_place_title:
            continue
        old_clock = old.get("time")
        if (same_place_title and type(old_clock) is str
                and CLOCK.fullmatch(old_clock)
                and old_clock == proposed["time"]):
            return "historical_exact_duplicate"
        # Multi-slot pages, long-running series and duplicate aggregates.
        # Same place/title with a different clock could be a distinct slot,
        # but this model never grants permission from similarity alone.
        return "historical_ambiguous_cross_source_collision"
    return None


def _prototype(lead, page, index, prefix, context, admin, today):
    """Memory-only catalogue shape, not signed source/GPS timestamps."""
    if not _valid_admin(admin, lead):
        return None, "admin_pin_unreviewed_or_invalid"
    venue = _trusted_exact_venue(lead, context)
    if venue is None:
        return None, "venue_coordinates_not_curated"
    draft = prepare_private_html_factual_draft(lead, page, index, prefix)
    if draft.get("status") != "private_draft_for_rights_review":
        return None, "factual_draft_not_confirmed"
    private = draft["draft"]
    category = private["category"]
    if category not in FAMILY_TYPES or category in LEGACY_MUSICAL:
        return None, "schema_structure_incompatible"
    day, clock = private["date_start"], private["start_local"]
    if type(clock) is not str or CLOCK.fullmatch(clock) is None:
        return None, "schema_structure_incompatible"

    identity = [
        private["source_url"], lead["title"], private["city"],
        private["venue"], day, clock,
    ]
    stable_id = hashlib.sha256(json.dumps(
        identity, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")).hexdigest()[:24]
    event = {
        "id": "html-" + stable_id,
        "title": lead["title"],
        "category": category,
        "category_label": FAMILY_TYPES[category][0],
        "date_start": day, "date_end": day, "time": clock,
        "city": private["city"],
        "department": admin["department"], "region": admin["region"],
        "venue": private["venue"],
        "source_url": private["source_url"],
        "source_label": admin["source_label"],
        # ONLY from the separately reviewed static registry; live GPS proof
        # has NOT been obtained. This shape can never be released.
        "lat": venue["lat"], "lng": venue["lng"],
        "geo_precision": "venue",
        # Shape placeholders only: NEVER attested geo/source timestamps.
        "verified_at": today.isoformat(),
        "geo_verified_at": today.isoformat(),
        # No copied organizer prose or misleading free/no-booking promises.
        "description": "Voir la fiche de l'organisateur pour les conditions.",
        "price": "Voir conditions",
    }
    lo, hi = private["age_min"], private["age_max"]
    if lo is None and hi is None:
        event["age_label"] = "En famille"  # only explicit family evidence
    else:
        if not all(
            (v is None or
             (type(v) in (int, float) and 0 <= v <= 17))
            for v in (lo, hi)
        ) or (lo is not None and hi is not None and lo > hi):
            return None, "schema_structure_incompatible"
        if lo is not None:
            event["age_min"] = lo
        if hi is not None:
            event["age_max"] = hi
        if lo is not None and hi is not None:
            event["age_label"] = f"De {lo} à {hi} ans"
        elif lo is not None:
            event["age_label"] = f"Dès {lo} ans"
        else:
            event["age_label"] = f"Jusqu’à {hi} ans"
    return event, None


def simulate_nonmusical_catalogue_shape(packets, current, today,
                                        *, expected_snapshot_sha256):
    """Strictly in memory, no patch, no event/URL output, no publication.

    The caller must independently fetch its current catalogue snapshot, and
    supply a SHA pin. Equality here only checks consistency of this input;
    it does NOT prove that input is the live public catalogue.
    """
    counters = {k: 0 for k in sorted(HOLD_CODES | STAGES)}
    report = {
        "schema": SCHEMA,
        "mode": "hypothetical_in_memory_structure_only_no_release",
        "input_candidates": 0,
        "current_catalogue_records": 0,
        "hypothetical_structural_matches_only": 0,
        "hypothetical_catalogue_total_if_all_other_gates_existed": 0,
        "blockers": counters,
        "unknown_ages_remain_unasserted": True,
        "unknown_price_is_never_free": True,
        "no_publisher_patch_constructed": True,
        "requires_independently_fetched_live_catalogue": True,
        "expected_catalogue_sha_is_consistency_only": True,
        "planning_timestamps_are_not_signed_proof": True,
        "current_catalogue_unchanged": True,
        "existing_music_publisher_unchanged": True,
        "rights_reviewed": False,
        "source_organizer_independently_attested": False,
        "fresh_independent_gps_verified": False,
        "publisher_schema_approved": False,
        "publisher_connected": False,
        "publication_ready": False,
        "approval_granted": False,
        "public_writes": 0,
        "private_event_fields_exposed": False,
    }
    if (type(today) is not date
            or not isinstance(packets, list)
            or not 0 <= len(packets) <= MAX_CANDIDATES
            or type(expected_snapshot_sha256) is not str
            or re.fullmatch(r"[a-f0-9]{64}", expected_snapshot_sha256) is None):
        report["blockers"]["invalid_catalogue_or_input"] += 1
        return report
    report["input_candidates"] = len(packets)
    if (not isinstance(current, dict)
            or current.get("version") != 3
            or not isinstance(current.get("events"), list)
            or not 100 <= len(current["events"]) <= MAX_CATALOGUE
            or not isinstance(current.get("updated_at"), str)):
        report["blockers"]["invalid_catalogue_or_input"] += len(packets) or 1
        return report
    before = _hash(current)
    if before != expected_snapshot_sha256:
        report["blockers"]["historical_snapshot_not_current"] += len(packets) or 1
        return report
    try:
        published = byid(current)
        # Strictly forbid mutation and copy any staging to local memory.
        staging = []
        baseline_fields = set().union(*(set(e) for e in published.values()))
        categories = {e["category"] for e in published.values()}
        report["current_catalogue_records"] = len(published)
        for packet in packets:
            if type(packet) is not dict or set(packet) != PACKET_KEYS:
                counters["invalid_catalogue_or_input"] += 1
                continue
            lead = packet["lead"]
            context = packet["independent_context"]
            if (not isinstance(lead, dict)
                    or not isinstance(context, dict)
                    or not isinstance(context.get("historical_catalogue"), dict)
                    or _hash(context["historical_catalogue"]) != before):
                counters["historical_snapshot_not_current"] += 1
                continue
            route = route_nonmusical_html_session(
                lead, packet["page"], packet["trusted_index"],
                packet["child_prefix"], context, today)
            state = route.get("stage")
            if state not in SHAPE_STAGES:
                counters[state if state in STAGES else "invalid_catalogue_or_input"] += 1
                continue
            event, blocker = _prototype(
                lead, packet["page"], packet["trusted_index"],
                packet["child_prefix"], context, packet["admin_pin"], today)
            if blocker:
                counters[blocker] += 1
                continue
            if (not set(event) <= baseline_fields
                    or not set(FAMILY_TYPES).isdisjoint(LEGACY_MUSICAL)):
                counters["schema_structure_incompatible"] += 1
                continue
            ok, _ = valid(event, categories | set(FAMILY_TYPES),
                          baseline_fields, today)
            if not ok:
                counters["schema_structure_incompatible"] += 1
                continue
            conflict = _collision(event, [*published.values(), *staging])
            if conflict:
                counters[conflict] += 1
                continue
            # Staged in a local list only, to simulate duplicate prevention
            # between incoming proposals. No event rows leave this function.
            staging.append(event)
            counters["hypothetical_shape_valid_but_all_release_proofs_missing"] += 1
    except (KeyError, ValueError, TypeError, OverflowError):
        # Unexpected registry/document corruption cannot produce a pass.
        counters["invalid_catalogue_or_input"] += len(packets) or 1
        staging = []
    if _hash(current) != before:
        raise ValueError("source_catalogue_mutated_during_dryrun")
    report["hypothetical_structural_matches_only"] = len(staging)
    report["hypothetical_catalogue_total_if_all_other_gates_existed"] = (
        report["current_catalogue_records"] + len(staging)
    )
    return report
