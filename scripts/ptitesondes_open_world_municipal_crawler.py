"""Resumable PRIVATE municipal website exploration; no city or page lists.

The trusted origin is discovered live from DILA (not from OpenAgenda alone).
Traverse *every* discovered same-site HTML page across multiple invocations,
regardless of whether URL/text resembles a venue, event, music or performance.
Resource limits are per-run work budgets, never semantic inclusion rules.

External links are private research leads only. Failed pages remain in a held
queue rather than disappearing; changing pages restart at their first links.
No cron, persistence, publisher, source approval or public catalogue writes.
"""
from copy import deepcopy
from hashlib import sha256
import re

from ptitesondes_dila_municipal_domains import (
    fetch_dila, municipal_site_hosts, approved_municipal_page_host,
)
from ptitesondes_dynamic_municipal_source_links import (
    scan_municipal_page, _safe_url,
)
from ptitesondes_unlisted_source_safe_recheck import read_unknown_https

SCHEMA = "ptitesondes.open_world_municipal_crawl.v1"
MAX_PAGES_PER_STEP = 5
MAX_PENDING = 10_000
MAX_SEEN = 100_000
MAX_HELD = 10_000
MAX_TRIES_PER_PAGE = 3
_LINK_BATCH_SIZE = 40


def _page(url, *, cursor=None, attempts=0):
    return {"url": url, "cursor": cursor, "attempts": attempts}


def _state_for(city, hosts):
    return {
        "schema": SCHEMA, "city": city,
        "dila_homepage_hosts": sorted(hosts),
        "pending_pages": [_page("https://" + host + "/")
                          for host in sorted(hosts)],
        "completed_pages": [], "held_pages": [],
    }


def _valid_page(row, city, directory):
    if (type(row) is not dict
            or set(row) != {"url", "cursor", "attempts"}
            or type(row["url"]) is not str
            or _safe_url(row["url"]) != row["url"]
            or type(row["attempts"]) is not int
            or not 0 <= row["attempts"] <= MAX_TRIES_PER_PAGE
            or approved_municipal_page_host(
                row["url"], city, directory) is None):
        return False
    cursor = row["cursor"]
    return cursor is None or (
        type(cursor) is dict
        and set(cursor) == {"page_sha256", "next_index"}
        and type(cursor["page_sha256"]) is str
        and re.fullmatch(r"[a-f0-9]{64}", cursor["page_sha256"]) is not None
        and type(cursor["next_index"]) is int
        and cursor["next_index"] > 0
    )


def _valid_existing(state, city, directory, hosts):
    if (type(state) is not dict
            or set(state) != {
                "schema", "city", "dila_homepage_hosts",
                "pending_pages", "completed_pages", "held_pages"}
            or state["schema"] != SCHEMA or state["city"] != city
            or state["dila_homepage_hosts"] != sorted(hosts)
            or type(state["pending_pages"]) is not list
            or type(state["completed_pages"]) is not list
            or type(state["held_pages"]) is not list
            or len(state["pending_pages"]) > MAX_PENDING
            or len(state["completed_pages"]) > MAX_SEEN
            or len(state["held_pages"]) > MAX_HELD):
        return False
    rows = state["pending_pages"] + state["held_pages"]
    if any(not _valid_page(item, city, directory) for item in rows):
        return False
    seen = state["completed_pages"]
    if any(type(url) is not str or _safe_url(url) != url
           or approved_municipal_page_host(url, city, directory) is None
           for url in seen):
        return False
    urls = [item["url"] for item in rows] + seen
    return len(urls) == len(set(urls))


def _out(status, state):
    return {
        "schema": SCHEMA, "status": status, "private_state": state,
        "private_external_source_links": [],
        "private_internal_links_examined": 0,
        "pages_fully_examined": 0,
        "page_batches_examined": 0,
        "pages_held_for_recheck": 0,
        "pages_queued": len(state["pending_pages"]) if state else 0,
        "pages_remaining_incomplete": (
            len(state["pending_pages"]) + len(state["held_pages"])
            if state else 0),
        "municipal_page_ownership_attested_by_dila": False,
        "linked_organizers_independently_attested": False,
        "source_reuse_rights_verified": False,
        "event_sessions_verified": False,
        "publisher_connected": False, "publication_ready": False,
        "approval_granted": False, "public_writes": 0,
    }


def crawl_private_municipal_sources(
        city, previous_state=None, *, directory_reader=fetch_dila,
        html_reader=read_unknown_https, page_budget=MAX_PAGES_PER_STEP):
    """Each step rechecks DILA, validates checkpoint and visits ≤5 page batches.

    The caller is responsible for keeping the state and source-link reports
    in a permission-restricted private workspace. A retry or oversized page
    never silently disappears from the queue or becomes approved.
    """
    empty = _out("invalid_municipal_research_request", None)
    if (type(city) is not str or not 1 <= len(city) <= 120
            or type(page_budget) is not int
            or not 1 <= page_budget <= MAX_PAGES_PER_STEP
            or not callable(directory_reader)
            or not callable(html_reader)):
        return empty
    try:
        directory = directory_reader(city)
        hosts = municipal_site_hosts(city, directory)
    except (OSError, ValueError, TypeError, KeyError, TimeoutError):
        return _out("dila_directory_unavailable", previous_state)
    if not hosts:
        return _out("municipal_domain_not_proven_at_dila", previous_state)
    state = (_state_for(city, hosts) if previous_state is None
             else deepcopy(previous_state))
    if not _valid_existing(state, city, directory, hosts):
        return _out("checkpoint_or_authority_mismatch", previous_state)

    initial_state = deepcopy(state)
    result = _out("municipal_sources_research_in_progress", state)
    result["municipal_page_ownership_attested_by_dila"] = True
    pending = state["pending_pages"]
    completed = state["completed_pages"]
    held = state["held_pages"]
    # Never turn three failed attempts into a permanent denylist. Resume one
    # held page on a later invocation when normal work has been exhausted.
    # The page must be fetched again and the live DILA scope rechecked.
    if not pending and held:
        pending.append(_page(held.pop(0)["url"]))
    external_seen = set()
    processed = 0
    while processed < page_budget and pending:
        current = pending.pop(0)
        processed += 1
        url = current["url"]
        try:
            html = html_reader(url)
            report = scan_municipal_page(
                city, directory, {"url": url, "html": html},
                cursor=current["cursor"], batch_size=_LINK_BATCH_SIZE)
        except (OSError, ValueError, TypeError, KeyError, TimeoutError,
                UnicodeError):
            report = {"status": "source_fetch_failed"}
        if report["status"] not in ("private_source_link_research_only",):
            # Changed HTML invalidates the cursor: re-scan the latest page
            # from its beginning, never keep skipping by a stale index.
            reset = (report["status"] == "municipal_source_cursor_mismatch")
            retry = _page(url, cursor=None if reset else current["cursor"],
                          attempts=current["attempts"] + 1)
            if retry["attempts"] >= MAX_TRIES_PER_PAGE:
                held.append(retry)
                result["pages_held_for_recheck"] += 1
            else:
                pending.append(retry)
            continue

        result["page_batches_examined"] += 1
        fresh = []
        already = set(completed)
        already.update(x["url"] for x in pending)
        already.update(x["url"] for x in held)
        already.add(url)
        for link in report["source_candidates"]:
            found = link["url"]
            if approved_municipal_page_host(
                    found, city, directory) is not None:
                result["private_internal_links_examined"] += 1
                if found not in already:
                    already.add(found)
                    fresh.append(_page(found))
            elif found not in external_seen:
                external_seen.add(found)
                result["private_external_source_links"].append({
                    "url": found,
                    # Preserve the EXACT DILA-verified municipal page that
                    # contains the visible hyperlink. The later verifier must
                    # re-fetch THIS page; a mere municipal home domain cannot
                    # establish the event citation.
                    "discovered_on_municipal_url": url,
                    "candidate_only": True,
                    "organizer_verified": False,
                    "rights_reviewed": False,
                    "publication_ready": False,
                })
        # Check capacity BEFORE committing a page: never report a scanned
        # tail while losing some queued municipal path.
        if (len(pending) + len(fresh) + 1 > MAX_PENDING
                or len(completed) + 1 > MAX_SEEN
                or len(held) > MAX_HELD):
            return _out("private_checkpoint_capacity_requires_review",
                        initial_state)
        if report["next_cursor"] is not None:
            # Continue the SAME page's next 40 links ahead of descendants.
            pending.insert(0, _page(url, cursor=report["next_cursor"]))
        else:
            completed.append(url)
            result["pages_fully_examined"] += 1
        pending.extend(fresh)
    result["pages_queued"] = len(pending)
    result["pages_remaining_incomplete"] = len(pending) + len(held)
    if not pending:
        result["status"] = (
            "municipal_research_incomplete_held_pages"
            if held else "municipal_research_frontier_exhausted")
    return result


def public_redacted_crawl_summary(result):
    """No private URLs, cities, internal paths, HTML, timestamps or tokens."""
    accepted = {
        "invalid_municipal_research_request",
        "dila_directory_unavailable",
        "municipal_domain_not_proven_at_dila",
        "checkpoint_or_authority_mismatch",
        "private_checkpoint_capacity_requires_review",
        "municipal_sources_research_in_progress",
        "municipal_research_incomplete_held_pages",
        "municipal_research_frontier_exhausted",
    }
    if (not isinstance(result, dict) or result.get("schema") != SCHEMA
            or result.get("status") not in accepted
            or any(result.get(k) is not False for k in (
                "linked_organizers_independently_attested",
                "source_reuse_rights_verified",
                "event_sessions_verified",
                "publisher_connected", "publication_ready",
                "approval_granted"))
            or result.get("public_writes") != 0):
        raise ValueError("invalid_private_crawl_report")
    return {
        "schema": SCHEMA + ".aggregate", "status": result["status"],
        "page_batches_examined": result["page_batches_examined"],
        "pages_fully_examined": result["pages_fully_examined"],
        "pages_held": result["pages_held_for_recheck"],
        "private_external_links_discovered_count":
            len(result["private_external_source_links"]),
        "remaining_unfinished_pages": result["pages_remaining_incomplete"],
        "publisher_connected": False, "publication_ready": False,
        "public_writes": 0,
    }
