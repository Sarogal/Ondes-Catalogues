"""PRIVATE autonomous source-candidate rotation: OA -> DILA -> crawl -> review.

This is an opt-in LIBRARY, not a scheduler or publisher. It links open-world
national OA event leads to DILA municipal page discovery, deep municipal
navigation and the full #599 per-session diagnostic. No curated agendas,
organizers, domains, venues, cities, categories, or HTML path names.

The exact municipal page of each external discovery is carried to the verifier.
The caller persists opaque private checkpoints between runs. Work budgets are
per invocation and never a permanent domain/venue exclusion policy.
"""
from copy import deepcopy
from datetime import date
from hashlib import sha256
import json
import re

from ptitesondes_dynamic_municipal_source_links import _safe_url
from ptitesondes_open_world_municipal_bootstrap import (
    bootstrap_municipal_sources, _safe_research_lead,
)
from ptitesondes_open_world_municipal_crawler import (
    crawl_private_municipal_sources,
)
from ptitesondes_open_world_admission_diagnostics import (
    inspect_open_world_candidate, SCHEMA as ADMISSION_SCHEMA,
)
from ptitesondes_openagenda_v2_direct_evidence import (
    _valid_public_read_key, read_direct_agenda_v2, read_direct_v2,
)
from ptitesondes_dila_municipal_domains import fetch_dila
from ptitesondes_unlisted_source_safe_recheck import read_unknown_https

SCHEMA = "ptitesondes.private_open_world_candidate_rotation.v1"
MAX_PAGES_PER_CYCLE = 5
MAX_SOURCES_PER_CYCLE = 5
MAX_QUEUE = 20_000
MAX_SEEN = 100_000
MAX_SOURCE_BYTES = 400_000


def _fingerprint(lead):
    try:
        raw = json.dumps(lead, sort_keys=True, ensure_ascii=False,
                         separators=(",", ":"), allow_nan=False).encode()
    except (ValueError, TypeError, UnicodeError):
        return None
    if len(raw) > MAX_SOURCE_BYTES:
        return None
    return sha256(raw).hexdigest()


def _entry(municipal, external):
    return {"municipal_url": municipal, "source_url": external}


def _key(entry):
    return sha256(
        (entry["municipal_url"] + "\n" + entry["source_url"])
        .encode("utf-8")).hexdigest()


def _initial(lead_digest, today):
    return {
        "schema": SCHEMA, "lead_sha256": lead_digest,
        "scan_day": today.isoformat(),
        "crawl_checkpoint": None, "pending_source_pairs": [],
        "seen_source_sha256": [],
    }


def _checkpoint_ok(value, lead_digest, today):
    if (type(value) is not dict
            or set(value) != {"schema", "lead_sha256", "scan_day",
                              "crawl_checkpoint", "pending_source_pairs",
                              "seen_source_sha256"}
            or value["schema"] != SCHEMA
            or value["lead_sha256"] != lead_digest
            or value["scan_day"] != today.isoformat()
            or not (value["crawl_checkpoint"] is None
                    or type(value["crawl_checkpoint"]) is dict)
            or type(value["pending_source_pairs"]) is not list
            or len(value["pending_source_pairs"]) > MAX_QUEUE
            or type(value["seen_source_sha256"]) is not list
            or len(value["seen_source_sha256"]) > MAX_SEEN):
        return False
    entries = value["pending_source_pairs"]
    if any(type(row) is not dict
           or set(row) != {"municipal_url", "source_url"}
           or not _safe_url(row["municipal_url"])
           or not _safe_url(row["source_url"])
           for row in entries):
        return False
    seen = value["seen_source_sha256"]
    if (any(type(x) is not str
            or re.fullmatch("[a-f0-9]{64}", x) is None
            for x in seen) or len(set(seen)) != len(seen)):
        return False
    pair_keys = [_key(row) for row in entries]
    return (len(pair_keys) == len(set(pair_keys))
            and not (set(pair_keys) & set(seen)))


def _blank(status, checkpoint=None):
    return {
        "schema": SCHEMA, "status": status,
        # The verified bootstrap status is a non-identifying PRIVATE reason
        # code; never replace it with an exception message or source URL.
        "bootstrap_reason_code": None,
        "private_checkpoint": checkpoint,
        "private_research_reviews": [],
        "municipal_page_batches_checked": 0,
        "source_candidates_discovered": 0,
        "source_candidates_examined": 0,
        "source_candidates_pending": (
            len(checkpoint["pending_source_pairs"])
            if isinstance(checkpoint, dict)
            and isinstance(checkpoint.get("pending_source_pairs"), list)
            else 0),
        "municipal_pages_remaining": 0,
        "organizer_identity_verified": False,
        "authoritative_duplicate_check": False,
        "source_rights_reviewed": False,
        "publisher_connected": False, "publication_ready": False,
        "public_writes": 0,
    }


def rotate_private_open_world_lead(
        lead, public_read_key, today, previous_checkpoint=None, *,
        pages_per_cycle=MAX_PAGES_PER_CYCLE,
        sources_per_cycle=MAX_SOURCES_PER_CYCLE,
        directory_reader=fetch_dila, html_reader=read_unknown_https,
        oa_agenda_reader=read_direct_agenda_v2,
        oa_event_reader=read_direct_v2, location_proof=None):
    """One read-only private cycle with *no manually selected candidate URLs*.

    All source reads are still reauthenticated inside the #599 verifier.
    Caller must store private results securely and never publish their URLs.
    """
    digest = _fingerprint(lead)
    if (digest is None or not _safe_research_lead(lead, today)
            or not _valid_public_read_key(public_read_key)
            or not type(pages_per_cycle) is int
            or not 1 <= pages_per_cycle <= MAX_PAGES_PER_CYCLE
            or not type(sources_per_cycle) is int
            or not 1 <= sources_per_cycle <= MAX_SOURCES_PER_CYCLE
            or not all(callable(x) for x in (
                directory_reader, html_reader, oa_agenda_reader,
                oa_event_reader))):
        return _blank("invalid_private_rotation_request")
    checkpoint = (
        _initial(digest, today) if previous_checkpoint is None
        else deepcopy(previous_checkpoint))
    if not _checkpoint_ok(checkpoint, digest, today):
        return _blank("stale_or_invalid_private_checkpoint")
    # Before beginning a crawl, independently re-read the live OA identity,
    # exact sessions, DILA municipality and the relevant official homepage.
    boot = bootstrap_municipal_sources(
        lead, public_read_key, today,
        agenda_reader=oa_agenda_reader, event_reader=oa_event_reader,
        directory_reader=directory_reader,
        municipal_html_reader=html_reader)
    if boot["status"] not in (
            "municipal_homepage_source_research_only",
            "municipal_sources_partial_research"):
        held = _blank("live_source_bootstrap_not_confirmed", checkpoint)
        # Preserve the exact safe stage of failure for the next read-only
        # investigation, instead of erasing all failures into one label.
        # Status comes from the closed bootstrap contract, not a domain list.
        held["bootstrap_reason_code"] = boot["status"]
        return held
    result = _blank("private_rotation_in_progress", checkpoint)
    crawl = crawl_private_municipal_sources(
        lead["city_unverified"], checkpoint["crawl_checkpoint"],
        directory_reader=directory_reader, html_reader=html_reader,
        page_budget=pages_per_cycle)
    if crawl["status"] not in (
            "municipal_sources_research_in_progress",
            "municipal_research_frontier_exhausted",
            "municipal_research_incomplete_held_pages"):
        return _blank("municipal_crawl_requires_recheck", checkpoint)

    new_sources = []
    already = (set(checkpoint["seen_source_sha256"])
               | {_key(row) for row in checkpoint["pending_source_pairs"]})
    for found in crawl["private_external_source_links"]:
        if (type(found) is not dict or
                found.get("candidate_only") is not True or
                found.get("organizer_verified") is not False or
                found.get("rights_reviewed") is not False or
                found.get("publication_ready") is not False):
            return _blank("untrusted_municipal_crawl_discovery", checkpoint)
        src, municipal = (found.get("url"),
                          found.get("discovered_on_municipal_url"))
        if not _safe_url(src) or not _safe_url(municipal):
            return _blank("untrusted_municipal_crawl_discovery", checkpoint)
        candidate = _entry(municipal, src)
        digest_key = _key(candidate)
        if digest_key not in already:
            already.add(digest_key)
            new_sources.append(candidate)
    if (len(checkpoint["pending_source_pairs"]) + len(new_sources)
            > MAX_QUEUE):
        # Do not lose the crawl cursor or any new links on overflow: caller
        # must partition/raise capacity and replay the identical checkpoint.
        return _blank("private_source_queue_capacity_requires_replay",
                      checkpoint)
    checkpoint["crawl_checkpoint"] = crawl["private_state"]
    checkpoint["pending_source_pairs"].extend(new_sources)
    result["municipal_page_batches_checked"] = crawl["page_batches_examined"]
    result["municipal_pages_remaining"] = crawl["pages_remaining_incomplete"]
    result["source_candidates_discovered"] = len(new_sources)
    to_review = min(sources_per_cycle, len(checkpoint["pending_source_pairs"]))
    if len(checkpoint["seen_source_sha256"]) + to_review > MAX_SEEN:
        # Keep all discoveries pending in a VALID checkpoint. Source identity
        # history must be partitioned explicitly, never truncated silently.
        return _blank("private_seen_capacity_requires_replay", checkpoint)
    for _ in range(to_review):
        source = checkpoint["pending_source_pairs"].pop(0)
        review = inspect_open_world_candidate(
            lead, source["municipal_url"], source["source_url"],
            public_read_key, today, location_proof=location_proof,
            oa_event_reader=oa_event_reader, oa_agenda_reader=oa_agenda_reader,
            dila_reader=directory_reader,
            municipal_html_reader=html_reader,
            organizer_html_reader=html_reader)
        if (not isinstance(review, dict)
                or review.get("schema") != ADMISSION_SCHEMA
                or review.get("publication_ready") is not False
                or review.get("public_writes") != 0
                or review.get("publisher_connected") is not False
                or review.get("organizer_authorship_proven") is not False
                or review.get("source_reuse_rights_verified") is not False
                or review.get("final_editorial_admission_authorized") is not False):
            return _blank("untrusted_private_candidate_review", checkpoint)
        # A lead may be unrelated to the event: keep the negative report as
        # private evidence, not a permanent domain exclusion.
        result["private_research_reviews"].append({
            **source, "diagnostic": review})
        result["source_candidates_examined"] += 1
        checkpoint["seen_source_sha256"].append(_key(source))
    if len(checkpoint["seen_source_sha256"]) > MAX_SEEN:
        return _blank("private_seen_capacity_requires_replay", checkpoint)
    result["source_candidates_pending"] = len(checkpoint["pending_source_pairs"])
    result["private_checkpoint"] = checkpoint
    if (crawl["status"] == "municipal_research_frontier_exhausted"
            and not checkpoint["pending_source_pairs"]):
        result["status"] = "private_daily_discovery_pass_exhausted"
    return result


def public_redacted_rotation_summary(report):
    """Safe to expose aggregate counts only; never list source URLs or times."""
    statuses = {
        "invalid_private_rotation_request",
        "stale_or_invalid_private_checkpoint",
        "live_source_bootstrap_not_confirmed",
        "municipal_crawl_requires_recheck",
        "untrusted_municipal_crawl_discovery",
        "private_source_queue_capacity_requires_replay",
        "untrusted_private_candidate_review",
        "private_seen_capacity_requires_replay",
        "private_rotation_in_progress",
        "private_daily_discovery_pass_exhausted",
    }
    if (not isinstance(report, dict) or report.get("schema") != SCHEMA
            or report.get("status") not in statuses
            or any(report.get(k) is not False for k in (
                "organizer_identity_verified", "authoritative_duplicate_check",
                "source_rights_reviewed", "publisher_connected",
                "publication_ready"))
            or report.get("public_writes") != 0
            or any(type(report.get(k)) is not int
                   or not 0 <= report[k] <= MAX_SEEN for k in (
                       "municipal_page_batches_checked",
                       "source_candidates_discovered",
                       "source_candidates_examined",
                       "source_candidates_pending",
                       "municipal_pages_remaining"))):
        raise ValueError("invalid_private_rotation_report")
    return {
        "schema": SCHEMA + ".aggregate", "status": report["status"],
        "page_batches_examined": report["municipal_page_batches_checked"],
        "new_sources_found": report["source_candidates_discovered"],
        "sources_examined": report["source_candidates_examined"],
        "sources_pending": report["source_candidates_pending"],
        "municipal_pages_pending": report["municipal_pages_remaining"],
        "publisher_connected": False, "publication_ready": False,
        "public_writes": 0,
    }
