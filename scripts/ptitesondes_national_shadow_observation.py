#!/usr/bin/env python3
"""Manual, private-only OpenAgenda national observation orchestration.

This is NOT a publisher, scheduler or admission decision. Its inputs and all
evidence remain in an outside-checkout 0700 directory. It continues previously
captured index batches and discovers new ones without any source allowlist.
The caller alone is responsible for persisting that PRIVATE directory between
ephemeral GitHub runners; stdout contains counters only.
"""
import argparse
from datetime import date
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from time import monotonic

from ptitesondes_openagenda_public_agenda_index import (
    load_state as load_index_state,
    scan_index_pages, _write_new_report, _write_state_atomic,
    read_index_page, _validated_page, PAGE_SIZE, SCHEMA as INDEX_SCHEMA,
)
from ptitesondes_openagenda_national_event_research import (
    MAX_INDEX_BYTES, _private_directory, _private_input,
)
from ptitesondes_openagenda_v2_direct_evidence import _valid_public_read_key
from ptitesondes_private_national_event_campaign import (
    MAX_SEGMENT_BYTES, plan_campaign, run_campaign,
)
from ptitesondes_private_national_rotation_runner import (
    MAX_SEGMENTS_PER_RUN, run_all_discovered_segments,
    _write_atomic_private, _safe_existing_file,
)

CONTROLLER_SCHEMA = "ptitesondes.private_national_observation_control.v1"
INDEX_JOURNAL_SCHEMA = "ptitesondes.private_national_index_transaction.v1"
REPORT_RE = re.compile(r"index-(20[0-9]{2}-[0-9]{2}-[0-9]{2})-([a-zA-Z0-9_-]{1,70})\.json\Z")
BATCH_RE = re.compile(r"[a-zA-Z0-9_-]{1,70}\Z")
# Two scheduled observations per day: census is rerun once per day.
# This is a frequency limit, never a predefined source or agenda shortlist.
INDEX_EVERY_N_INVOCATIONS = 2
MAX_BATCHES_PER_RUN = 2
MAX_AGENDAS_PER_BATCH = 20
MAX_AGENDA_ROTATION_SECONDS = 600
AGENDA_SELECTOR_SCHEMA = "ptitesondes.private_national_agenda_rotation.v1"
MAX_CONTROL_BYTES = 4096
GEOGRAPHY_SCHEMA = "ptitesondes.private_geographic_index_rotation.v1"
# Geographic queries are discovery seeds, never agenda/venue allowlists.
# All unfiltered index lanes remain independent and continue to run.
# Start with the three regions with no published outings on 25 Nov 2026.
GEOGRAPHIC_TERMS = (
    "Guadeloupe", "Guyane", "Mayotte",
    "Martinique", "La Réunion", "Corse",
    "Auvergne-Rhône-Alpes", "Bourgogne-Franche-Comté", "Bretagne",
    "Centre-Val de Loire", "Grand Est", "Hauts-de-France",
    "Île-de-France", "Normandie", "Nouvelle-Aquitaine",
    "Occitanie", "Pays de la Loire", "Provence-Alpes-Côte d'Azur",
    "Polynésie française", "Nouvelle-Calédonie", "Wallis-et-Futuna",
    "Saint-Pierre-et-Miquelon", "Saint-Barthélemy", "Saint-Martin",
)
GEOGRAPHIC_QUERIES_PER_RUN = 3
SEGMENT_REPORT_RE = re.compile(r"agenda-[0-9]{1,8}-segment-[0-9]{1,8}\.json\Z")


def private_subdir(path):
    path = Path(path)
    if not path.exists():
        path.mkdir(mode=0o700)
    _private_directory(path)
    return path


def controller_read(path):
    if not path.exists():
        return {"schema": CONTROLLER_SCHEMA, "invocations": 0,
                "next_batch_index": 0}
    raw = _safe_existing_file(path, MAX_CONTROL_BYTES)
    data = json.loads(raw)
    if (not isinstance(data, dict)
            or set(data) != {"schema", "invocations", "next_batch_index"}
            or data["schema"] != CONTROLLER_SCHEMA
            or type(data["invocations"]) is not int
            or not 0 <= data["invocations"] < 10**9
            or type(data["next_batch_index"]) is not int
            or not 0 <= data["next_batch_index"] < 10**9):
        raise ValueError("untrusted_private_observation_controller")
    return data


def available_index_reports(index_dir):
    """Enumerate without opening candidates: a bad report must not starve others."""
    _private_directory(index_dir)
    reports = []
    for path in index_dir.iterdir():
        match = REPORT_RE.fullmatch(path.name)
        if match:
            try:
                scan_day = date.fromisoformat(match.group(1))
            except ValueError:
                scan_day = None   # Retain as held research, never silently drop.
            reports.append((path, scan_day))
    return sorted(reports, key=lambda pair: pair[0].name)


def geographic_index_sample(index_dir, reports_dir, day, batch_id, key, reader):
    """Discover new agenda identities with bounded geographic search queries.

    Search results do not establish their territory, organiser or eligibility.
    They join the exact same independent campaign, backlog and Publisher lanes.
    The relevance page is a supplemental sample, not an exhaustive census.
    """
    path = index_dir / "geographic-cursor.json"
    position = 0
    if path.exists() or path.is_symlink():
        state = json.loads(_safe_existing_file(path, MAX_CONTROL_BYTES))
        if (type(state) is not dict or set(state) != {"schema", "next_term"}
                or state["schema"] != GEOGRAPHY_SCHEMA
                or type(state["next_term"]) is not int
                or not 0 <= state["next_term"] < len(GEOGRAPHIC_TERMS)):
            raise ValueError("invalid_geographic_index_rotation")
        position = state["next_term"]
    known = set()
    for existing, _ in available_index_reports(reports_dir):
        try:
            doc = json.loads(_private_input(existing, MAX_INDEX_BYTES))
            if (doc.get("schema") != INDEX_SCHEMA
                    or doc.get("publication_ready") is not False
                    or doc.get("public_writes") != 0):
                continue
            known.update(row["agenda_uid"] for row in doc["new_agenda_candidates"]
                         if type(row) is dict and type(row.get("agenda_uid")) is int)
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            continue
    groups = []
    completed = failed = identities = 0
    for offset in range(GEOGRAPHIC_QUERIES_PER_RUN):
        term = GEOGRAPHIC_TERMS[(position + offset) % len(GEOGRAPHIC_TERMS)]
        try:
            data = reader(key, size=PAGE_SIZE, search=term)
            rows, _ = _validated_page(data, PAGE_SIZE, None)
        except (OSError, ValueError, TypeError, KeyError, TimeoutError):
            failed += 1
            continue
        completed += 1
        group = []
        groups.append(group)
        for row in rows:
            identities += 1
            uid = row["uid"]
            if uid in known:
                continue
            known.add(uid)
            group.append({
                "agenda_uid": uid, "agenda_slug": row["slug"],
                "agenda_title": row["title"], "source_identity_only": True,
                "owner_verified": False, "organiser_verified": False,
                "rights_reviewed": False, "publisher_enabled": False,
            })
    candidates = [group[offset] for offset in range(PAGE_SIZE)
                  for group in groups if offset < len(group)]
    report_path = None
    if candidates:
        suffix = sha256(batch_id.encode()).hexdigest()[:20]
        report_path = reports_dir / f"index-{day.isoformat()}-geo-{suffix}-{position}.json"
        if report_path.exists():
            raise ValueError("geographic_index_batch_already_exists")
        else:
            _write_new_report(report_path, {
                "schema": INDEX_SCHEMA,
                "mode": "private_index_readonly_discovery_not_admission",
                "counts": {"pages_read": completed,
                           "public_agenda_identifiers_seen": identities,
                           "new_index_agendas_unverified": len(candidates)},
                "new_agenda_candidates": candidates,
                "next_cursor": None, "index_pass_exhausted": False,
                "owner_independently_verified": False,
                "publisher_connected": False, "publication_ready": False,
                "public_writes": 0,
            })
    # Keep geographic failure isolated from national census progress.
    # A failed term is retried on the next complete geographic rotation;
    # successful first-page samples never become permanent exclusions.
    _write_atomic_private(path, (json.dumps({
        "schema": GEOGRAPHY_SCHEMA,
        "next_term": (position + GEOGRAPHIC_QUERIES_PER_RUN) % len(GEOGRAPHIC_TERMS),
    }, sort_keys=True) + "\n").encode())
    return report_path, completed, failed, len(candidates)


def _cursor_state(state, after, completed):
    return {"schema": state["schema"], "after": after,
            "completed_passes": completed}


def _index_cursor_path(index_dir, mode):
    if mode not in ("legacy", "recent"):
        raise ValueError("invalid_index_rotation_mode")
    return index_dir / ("cursor.json" if mode == "legacy"
                        else "recent-cursor.json")


def _pending_index_path(index_dir, mode="legacy"):
    if mode not in ("legacy", "recent"):
        raise ValueError("invalid_index_rotation_mode")
    return index_dir / ("pending-index-transaction.json" if mode == "legacy"
                        else "pending-recent-index-transaction.json")


def recover_pending_index(index_dir, reports_dir, *, mode="legacy"):
    """Finish an interrupted index/report commit, without skipping a page."""
    state_path = _index_cursor_path(index_dir, mode)
    pending = _pending_index_path(index_dir, mode)
    if not pending.exists():
        if pending.is_symlink():
            raise ValueError("unsafe_pending_index_transaction")
        return False
    raw = _safe_existing_file(pending, MAX_CONTROL_BYTES)
    tx = json.loads(raw)
    if (not isinstance(tx, dict)
            or set(tx) != {"schema", "report_name", "report_sha256",
                           "source_after", "source_passes",
                           "target_after", "target_passes"}
            or tx["schema"] != INDEX_JOURNAL_SCHEMA
            or not isinstance(tx["report_name"], str)
            or REPORT_RE.fullmatch(tx["report_name"]) is None
            or not isinstance(tx["report_sha256"], str)
            or re.fullmatch(r"[0-9a-f]{64}", tx["report_sha256"]) is None
            or type(tx["source_passes"]) is not int
            or type(tx["target_passes"]) is not int
            or tx["source_passes"] < 0
            or tx["target_passes"] not in (tx["source_passes"],
                                             tx["source_passes"] + 1)):
        raise ValueError("invalid_private_index_transaction")
    source = _cursor_state(load_index_state(state_path),
                           tx["source_after"], tx["source_passes"])
    target = _cursor_state(source, tx["target_after"], tx["target_passes"])
    report_path = reports_dir / tx["report_name"]
    current = load_index_state(state_path)
    if not report_path.exists():
        # Crash before writing report: no cursor advance is allowed.
        if current != source or report_path.is_symlink():
            raise ValueError("index_transaction_report_missing_or_untrusted")
        pending.unlink()
        return False
    report_raw = _private_input(report_path, MAX_INDEX_BYTES)
    if sha256(report_raw).hexdigest() != tx["report_sha256"]:
        raise ValueError("index_transaction_report_digest_mismatch")
    report = json.loads(report_raw)
    if (report.get("schema") != "ptitesondes.private_national_oa_index.v1"
            or report.get("next_cursor") != target["after"]
            or report.get("publication_ready") is not False
            or report.get("public_writes") != 0):
        raise ValueError("index_transaction_report_invalid")
    if current == source:
        _write_state_atomic(state_path, target)
    elif current != target:
        raise ValueError("index_transaction_cursor_conflict")
    pending.unlink()
    return True


def store_index_batch(index_dir, reports_dir, report_path, report, state,
                      *, mode="legacy"):
    """Write-ahead log protects the interval between report and index cursor."""
    state_path = _index_cursor_path(index_dir, mode)
    if report_path.exists() or report_path.is_symlink():
        raise ValueError("index_report_already_exists")
    target = _cursor_state(state, report["next_cursor"],
                           state["completed_passes"] +
                           int(report["index_pass_exhausted"]))
    encoded_report = (json.dumps(report, ensure_ascii=False, indent=2) +
                      "\n").encode("utf-8")
    if len(encoded_report) > MAX_INDEX_BYTES:
        raise ValueError("index_report_exceeds_resumable_capacity")
    journal = {
        "schema": INDEX_JOURNAL_SCHEMA,
        "report_name": report_path.name,
        "report_sha256": sha256(encoded_report).hexdigest(),
        "source_after": state["after"],
        "source_passes": state["completed_passes"],
        "target_after": target["after"],
        "target_passes": target["completed_passes"],
    }
    pending = _pending_index_path(index_dir, mode)
    if pending.exists() or pending.is_symlink():
        raise ValueError("index_transaction_pending")
    _write_atomic_private(pending, (json.dumps(
        journal, ensure_ascii=False, separators=(",", ":")) + "\n").encode())
    # These two writes are deliberately separate; recovery reconciles them.
    _write_new_report(report_path, report)
    _write_state_atomic(state_path, target)
    pending.unlink()


def summarize_private_segment_hints(campaign, digest, scan_day,
                                    event_keys, session_keys, venue_keys,
                                    territory_claims):
    """Measure discovery hints only; none proves admission or geography.

    A corrupt segment is held and cannot prevent other segments or batches
    from being counted. Dedupe by OpenAgenda agenda + event + EXACT interval.
    """
    invalid = 0
    for path in sorted(campaign.iterdir()):
        if SEGMENT_REPORT_RE.fullmatch(path.name) is None:
            continue
        local_events, local_sessions = set(), set()
        local_venues, local_claims = set(), set()
        try:
            obj = json.loads(_private_input(path, MAX_SEGMENT_BYTES))
            meta = obj.get("campaign_meta")
            if (not isinstance(meta, dict)
                    or meta.get("source_sha256") != digest
                    or meta.get("scan_day") != scan_day.isoformat()
                    or obj.get("schema") !=
                    "ptitesondes.private_oa_agenda_event_exploration.v1"
                    or obj.get("publication_ready") is not False
                    or obj.get("public_writes") != 0):
                raise ValueError("untrusted_national_segment_metrics")
            categorized = obj.get("event_leads")
            uncategorized = obj.get("unclassified_editorial_research_only")
            if not isinstance(categorized, list) or not isinstance(uncategorized, list):
                raise ValueError("invalid_candidate_lists")
            for item in categorized + uncategorized:
                if (not isinstance(item, dict)
                        or type(item.get("agenda_uid")) is not int
                        or type(item.get("event_uid")) is not int
                        or item.get("publication_ready") is not False
                        or item.get("public_writes") != 0):
                    raise ValueError("invalid_private_candidate_identity")
                identity = (item["agenda_uid"], item["event_uid"])
                local_events.add(identity)
                for timing in item.get("explicit_source_session_intervals") or []:
                    if (isinstance(timing, dict)
                            and isinstance(timing.get("begin"), str)
                            and isinstance(timing.get("end"), str)):
                        local_sessions.add(identity + (
                            timing["begin"], timing["end"]))
                city, venue = item.get("city_unverified"), item.get("venue_unverified")
                if (isinstance(city, str) and city.strip()
                        and isinstance(venue, str) and venue.strip()):
                    local_venues.add((city.strip().casefold(),
                                    venue.strip().casefold()))
                country = item.get("country_code_unverified")
                if isinstance(country, str) and len(country) == 2:
                    local_claims.add(country.upper())
            # Count only a FULLY trusted segment, never partial malformed data.
            event_keys.update(local_events)
            session_keys.update(local_sessions)
            venue_keys.update(local_venues)
            territory_claims.update(local_claims)
        except (OSError, ValueError, TypeError, AttributeError,
                UnicodeError):
            invalid += 1
    return invalid


AGENDA_DIAGNOSTIC_SCHEMA = "ptitesondes.private_agenda_research_diagnostic.v1"


def write_private_agenda_diagnostic(campaign_dir, idx, agenda_uid, digest,
                                    day, *, status, stage, reason):
    """Per-agenda private retry evidence. Never store raw exception messages."""
    path = campaign_dir / f"agenda-{idx:04d}-diagnostic.json"
    previous_count = 0
    if path.exists() or path.is_symlink():
        previous = json.loads(_safe_existing_file(path, MAX_CONTROL_BYTES))
        if (not isinstance(previous, dict)
                or set(previous) != {
                    "schema", "source_sha256", "agenda_uid", "scan_day",
                    "attempts", "last_status", "stage", "reason_code",
                    "publication_ready", "public_writes"}
                or previous["schema"] != AGENDA_DIAGNOSTIC_SCHEMA
                or previous["source_sha256"] != digest
                or previous["agenda_uid"] != agenda_uid
                or previous["scan_day"] != day.isoformat()
                or previous["publication_ready"] is not False
                or previous["public_writes"] != 0
                or type(previous["attempts"]) is not int
                or not 1 <= previous["attempts"] < 10**9):
            raise ValueError("untrusted_private_agenda_diagnostic")
        previous_count = previous["attempts"]
    record = {
        "schema": AGENDA_DIAGNOSTIC_SCHEMA,
        "source_sha256": digest,
        "agenda_uid": agenda_uid,
        "scan_day": day.isoformat(),
        "attempts": previous_count + 1,
        "last_status": status,
        "stage": stage,
        "reason_code": reason,
        "publication_ready": False, "public_writes": 0,
    }
    _write_atomic_private(path, (json.dumps(
        record, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")) + "\n").encode("utf-8"))


def _safe_failure_reason(exc):
    # No exception.message: external errors may contain URLs or credentials.
    if isinstance(exc, TimeoutError):
        return "source_timeout"
    if isinstance(exc, OSError):
        return "upstream_or_private_io_error"
    if isinstance(exc, KeyError):
        return "required_input_field_missing"
    if isinstance(exc, UnicodeError):
        return "source_encoding_invalid"
    if isinstance(exc, TypeError):
        return "invalid_input_type"
    return "invalid_or_conflicting_source_evidence"


INDEX_READ_ERROR_CODES = frozenset({
    "invalid_oa_index_request", "oa_index_unavailable",
    "unexpected_oa_index_endpoint", "oa_index_size_invalid",
    "oa_index_invalid_json", "invalid_oa_index_page",
    "invalid_oa_index_rows", "invalid_oa_index_cursor",
    "invalid_oa_index_item", "invalid_oa_index_identity",
    "invalid_oa_index_scan", "repeated_oa_agenda_in_cursor_scan",
    "invalid_oa_index_cursor_reuse", "untrusted_national_index_response",
})


def write_index_read_failure(index_dir, mode, day, exc):
    """Persist only fixed reason codes, never exception text or credentials."""
    reason = _safe_failure_reason(exc)
    if type(exc) is ValueError and len(exc.args) == 1:
        candidate = exc.args[0]
        if isinstance(candidate, str) and candidate in INDEX_READ_ERROR_CODES:
            reason = candidate
    record = {
        "schema": "ptitesondes.private_national_index_failure.v1",
        "mode": mode, "day": day.isoformat(), "reason_code": reason,
        "publication_ready": False, "public_writes": 0,
    }
    _write_atomic_private(index_dir / f"last-{mode}-read-failure.json",
                          (json.dumps(record, sort_keys=True) + "\n").encode())


def rotate_agendas_independently(index_doc, digest, scan_day, campaign_dir,
                                 rotation_dir, key, campaign_runner,
                                 segment_runner, *, clock=monotonic):
    """Keep each agenda's checkpoint and retry, independent of its neighbors.

    One unreachable agenda cannot pin a batch's single sequential checkpoint.
    All agendas, including unknown ones, enter a resumable round-robin.
    Bounded budgets are per invocation, never eligibility filters.
    """
    candidates = index_doc["new_agenda_candidates"]
    total = len(candidates)
    selector = campaign_dir / "agenda-selector.json"
    default = {"schema": AGENDA_SELECTOR_SCHEMA,
               "source_sha256": digest, "scan_day": scan_day.isoformat(),
               "next_index": 0}
    current = default
    if selector.exists() or selector.is_symlink():
        raw = _safe_existing_file(selector, MAX_CONTROL_BYTES)
        current = json.loads(raw)
        if (not isinstance(current, dict)
                or set(current) != set(default)
                or current["schema"] != AGENDA_SELECTOR_SCHEMA
                or current["source_sha256"] != digest
                or current["scan_day"] != scan_day.isoformat()
                or type(current["next_index"]) is not int
                or not 0 <= current["next_index"] < max(total, 1)):
            raise ValueError("invalid_private_agenda_selector")
    started = held = completed = examined_segments = examined_events = 0
    if not total:
        return {"agenda_attempts": 0, "agenda_advanced": 0,
                "agenda_finished": 0, "agenda_held": 0,
                "segments_examined": 0, "event_slots_examined": 0,
                "segment_holds": 0}
    start = current["next_index"]
    segment_holds = attempts = 0
    begun = clock()
    for step in range(min(total, MAX_AGENDAS_PER_BATCH)):
        # Protect the private checkpoint push from GitHub job timeout.
        # This is a time budget, NOT a closed list or permanent exclusion.
        if step and clock() - begun >= MAX_AGENDA_ROTATION_SECONDS:
            break
        attempts += 1
        idx = (start + step) % total
        stage, failure = "campaign", None
        observed_hold = False
        try:
            agenda_dir = private_subdir(campaign_dir / f"agenda-{idx:04d}")
            rotation_state = private_subdir(rotation_dir / f"agenda-{idx:04d}")
            single_doc = dict(index_doc, new_agenda_candidates=[candidates[idx]])
            single_digest = sha256(json.dumps(
                single_doc, sort_keys=True, ensure_ascii=False,
                separators=(",", ":")).encode("utf-8")).hexdigest()
            plan = plan_campaign(single_doc, single_digest, scan_day, agenda_dir)
            result = campaign_runner(plan, public_key=key)
            if (result.get("public_writes") != 0
                    or result.get("publication_ready") is not False):
                raise ValueError("unsafe_private_individual_campaign")
            started += 1
            completed += int(result["finished_index_batch"])
            stage = "segment_rotation"
            rotated = segment_runner(
                agenda_dir, rotation_state, scan_day,
                execute_live=True, key=key,
                segment_budget=MAX_SEGMENTS_PER_RUN)
            if (rotated.get("public_writes") != 0
                    or rotated.get("publication_ready") is not False):
                raise ValueError("unsafe_private_individual_rotation")
            examined_segments += rotated["segment_reports_examined"]
            examined_events += rotated["event_slots_examined"]
            segment_holds += rotated["segment_reports_held"]
            observed_hold = rotated["segment_reports_held"] > 0
        except (OSError, ValueError, TypeError, KeyError, TimeoutError,
                UnicodeError) as exc:
            # Preserve existing per-agenda state for a subsequent retry.
            held += 1
            failure = _safe_failure_reason(exc)
        # Store private reason codes before advancing the selector.
        write_private_agenda_diagnostic(
            campaign_dir, idx, candidates[idx]["agenda_uid"], digest,
            scan_day, status=("held_for_research" if failure else
                              "partial_research" if observed_hold else
                              "research_cycle_completed"),
            stage=stage, reason=(failure or
                "segment_requires_research_review" if observed_hold else
                failure or "no_error"))
        # Persist AFTER each attempt to survive power loss and avoid allowing
        # the same failed source to starve other candidates after restart.
        _write_atomic_private(selector, (json.dumps({
            **default, "next_index": (idx + 1) % total},
            ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"))
    return {"agenda_attempts": attempts,
            "agenda_advanced": started, "agenda_finished": completed,
            "agenda_held": held, "segments_examined": examined_segments,
            "event_slots_examined": examined_events,
            "segment_holds": segment_holds}


def run_observation(root, day, batch_id, *,
                    execute_live=False, key="", index_reader=scan_index_pages,
                    campaign_runner=run_campaign,
                    segment_runner=run_all_discovered_segments,
                    geography_reader=None):
    """Inspect a bounded fair rotation; resume every saved campaign batch.

    The original day stays attached to each collected report. Older reports
    remain discoverable rather than being silently dropped at midnight. Their
    old evidence is research ONLY and must be freshly checked for admission.
    """
    root = Path(root)
    _private_directory(root)
    if type(day) is not date or not isinstance(batch_id, str) or not BATCH_RE.fullmatch(batch_id):
        raise ValueError("invalid_private_observation_arguments")
    index_dir = private_subdir(root / "index") if execute_live else root / "index"
    reports_dir = private_subdir(index_dir / "reports") if execute_live else index_dir / "reports"
    existing = (available_index_reports(reports_dir)
                if reports_dir.is_dir() else [])
    if not execute_live:
        return {"mode": "dry_run_no_network_or_writes",
                "stored_index_batches": len(existing), "public_writes": 0}
    if not _valid_public_read_key(key):
        raise ValueError("private_observation_read_key_required")
    # The legacy sources.json is deliberately not an input. Discover ALL
    # OpenAgenda agendas, including historically known ones, with no manual
    # source-ID registry, venue registry, or curated source list.
    campaign_root = private_subdir(root / "campaigns")
    rotation_root = private_subdir(root / "rotations")
    control_path = root / "controller.json"
    controller = controller_read(control_path)
    # Recover either cursor transaction before issuing another read. Neither
    # sort order is allowed to advance past a report lost during a crash.
    recovered_index = (recover_pending_index(index_dir, reports_dir)
                       or recover_pending_index(index_dir, reports_dir,
                                                mode="recent"))

    # No historical source list filters OpenAgenda's directory; all agenda
    # identities are merely research leads requiring independent evidence.
    # Keep each batch: adding a fresh index cannot destroy unfinished ones.
    index_scanned = False
    index_read_failure = None
    if (not recovered_index
            and controller["invocations"] % INDEX_EVERY_N_INVOCATIONS == 0):
        # Legacy UID-ascending crawl guarantees exhaustive eventual coverage.
        # A second independent cursor targets agendas with newly added events
        # so recently active, previously unknown organizers need not wait for
        # the complete historical directory crawl. No territorial/genre list.
        legacy_started = _index_cursor_path(index_dir, "legacy").is_file()
        recent_started = _index_cursor_path(index_dir, "recent").is_file()
        turn = controller["invocations"] // INDEX_EVERY_N_INVOCATIONS
        mode = ("recent" if (legacy_started and not recent_started)
                or (legacy_started and turn % 2 == 1)
                else "legacy")
        # A failure of one documented sort must not freeze the other
        # independent census. Only attempt the alternate when an index
        # already exists, and retain the primary error and its retry due.
        # Each mode has its own cursor and transaction journal.
        modes = [mode]
        if legacy_started or recent_started:
            modes.append("legacy" if mode == "recent" else "recent")
        for mode in modes:
            suffix = "-recent" if mode == "recent" else ""
            name = f"index-{day.isoformat()}-{batch_id}{suffix}.json"
            new_path = reports_dir / name
            if not new_path.exists():
                state_path = _index_cursor_path(index_dir, mode)
                state = load_index_state(state_path)
                arguments = {"start_cursor": state["after"],
                             "public_read_key": key}
                if mode == "recent":
                    arguments["sort"] = "recentlyAddedEvents.desc"
                try:
                    result = index_reader([], **arguments)
                    if (not isinstance(result, dict)
                            or result.get("schema") != "ptitesondes.private_national_oa_index.v1"
                            or result.get("publication_ready") is not False
                            or result.get("public_writes") != 0):
                        raise ValueError("untrusted_national_index_response")
                except (OSError, ValueError, TypeError, KeyError) as exc:
                    # Keep the failed census due; existing saved campaigns can
                    # nevertheless advance. Never publish raw upstream messages.
                    if index_read_failure is None:
                        index_read_failure = exc
                    write_index_read_failure(index_dir, mode, day, exc)
                else:
                    store_index_batch(index_dir, reports_dir, new_path, result, state,
                                      mode=mode)
                    index_scanned = True
                    break

    geographic_path = None
    geographic_completed = geographic_failed = geographic_new = 0
    if geography_reader is not None:
        try:
            geographic_path, geographic_completed, geographic_failed, geographic_new = (
                geographic_index_sample(index_dir, reports_dir, day, batch_id,
                                        key, geography_reader))
        except (OSError, ValueError, TypeError, KeyError, TimeoutError):
            geographic_failed = GEOGRAPHIC_QUERIES_PER_RUN
    reports = available_index_reports(reports_dir)
    n = len(reports)
    started = held = examined_segments = examined_events = 0
    agenda_attempts = agenda_held = agenda_finished = 0
    agenda_keys, event_keys, session_keys = set(), set(), set()
    venue_keys, territory_claims = set(), set()
    invalid_metric_segments = 0
    # Round robin across ALL saved batches; old batches are never replaced by
    # today's index. New reports enter the same queue on subsequent passes.
    start = controller["next_batch_index"] % n if n else 0
    selected = [reports[(start + step) % n]
                for step in range(min(n, MAX_BATCHES_PER_RUN))]
    regular_slots = len(selected)
    # Newly discovered geographic sources get one prompt review slot;
    # retain at least one ordinary batch and its own fair rotation.
    if geographic_path is not None and all(p != geographic_path for p, _ in selected):
        pair = next((pair for pair in reports if pair[0] == geographic_path), None)
        if pair is not None:
            selected = selected[:1] + [pair]
            regular_slots = 1
    for report_path, scan_day in selected:
        try:
            raw = _private_input(report_path, MAX_INDEX_BYTES)
            digest = sha256(raw).hexdigest()
            campaign = private_subdir(campaign_root / digest[:24])
            rotation = private_subdir(rotation_root / digest[:24])
            # A whole index batch is validated first, but each agenda
            # executes in its own cursor namespace to avoid starvation.
            plan = plan_campaign(json.loads(raw), digest, scan_day, campaign)
            result = rotate_agendas_independently(
                plan["index_doc"], digest, scan_day, campaign, rotation,
                key, campaign_runner, segment_runner)
            started += int(result["agenda_advanced"] > 0)
            agenda_finished += result["agenda_finished"]
            agenda_attempts += result["agenda_attempts"]
            agenda_held += result["agenda_held"]
            examined_segments += result["segments_examined"]
            examined_events += result["event_slots_examined"]
            held += result["segment_holds"] + result["agenda_held"]
            for candidate in plan["index_doc"]["new_agenda_candidates"]:
                if type(candidate.get("agenda_uid")) is int:
                    agenda_keys.add(candidate["agenda_uid"])
            for candidate_dir in sorted(campaign.iterdir()):
                if not candidate_dir.is_dir() or not candidate_dir.name.startswith("agenda-"):
                    continue
                candidate_index = candidate_dir.name.split("-")[-1]
                if not candidate_index.isdecimal():
                    continue
                item_idx = int(candidate_index)
                if item_idx >= len(plan["index_doc"]["new_agenda_candidates"]):
                    continue
                single_doc = dict(plan["index_doc"], new_agenda_candidates=[
                    plan["index_doc"]["new_agenda_candidates"][item_idx]])
                single_digest = sha256(json.dumps(
                    single_doc, sort_keys=True, ensure_ascii=False,
                    separators=(",", ":")).encode("utf-8")).hexdigest()
                invalid_metric_segments += summarize_private_segment_hints(
                    candidate_dir, single_digest, scan_day,
                    event_keys, session_keys, venue_keys, territory_claims)
        except (OSError, ValueError, TypeError, KeyError, TimeoutError,
                UnicodeError):
            # This report stays on disk and remains in the next rotation.
            held += 1

    updated = {
        "schema": CONTROLLER_SCHEMA,
        "invocations": controller["invocations"] + int(index_read_failure is None),
        "next_batch_index": (start + regular_slots) % n if n else 0,
    }
    _write_atomic_private(control_path, (
        json.dumps(updated, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8"))
    if index_read_failure is not None:
        # Checkpoints are saved, but the workflow must remain failed.
        raise index_read_failure
    return {"mode": "private_observation_readonly",
            "stored_index_batches": n, "new_index_census": int(index_scanned),
            "geographic_queries_completed": geographic_completed,
            "geographic_queries_failed": geographic_failed,
            "geographic_new_agendas_unverified": geographic_new,
            "index_batches_examined": len(selected),
            "index_batches_advanced": started,
            # A completed agenda is not proof the whole index batch finished.
            "agendas_completed_in_examined_slots": agenda_finished,
            "agenda_attempts": agenda_attempts,
            "agenda_held_for_research": agenda_held,
            "segments_examined": examined_segments,
            "event_slots_examined": examined_events,
            "held_for_research": held,
            "index_agendas_observed_in_batch_sample": len(agenda_keys),
            "distinct_event_uids_in_saved_segments": len(event_keys),
            "distinct_exact_session_hints_in_saved_segments": len(session_keys),
            "distinct_city_venue_name_hints_unverified": len(venue_keys),
            "distinct_territory_country_claims_unverified": len(territory_claims),
            "unreadable_segments_for_metric_review": invalid_metric_segments,
            "publisher_connected": False,
            "publication_ready": False, "public_writes": 0}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--private-observation-root", required=True, type=Path)
    parser.add_argument("--day", required=True, type=date.fromisoformat)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--execute-live", action="store_true")
    args = parser.parse_args()
    result = run_observation(
        args.private_observation_root,
        args.day, args.batch_id, execute_live=args.execute_live,
        key=os.environ.get("OPENAGENDA_READ_KEY", ""),
        geography_reader=read_index_page)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
