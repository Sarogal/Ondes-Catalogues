"""Private-only promotion: Schema.org HINT -> exact visible HTML session review.

No hint alone can be a proof. The trusted runner must *refetch* the current
curated index, find the same child URL in visible links, refetch that exact
child, and independently corroborate its same-block date/clock and audience.
The existing HTML router then recomputes all requirements. This is only a
PRIVATE review, never an approval or a publication path.
"""
from collections import defaultdict, deque
from datetime import date
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from proof import norm
from ptitesondes_html_first_party_session_proof import (
    corroborate_first_party_session,
)
from ptitesondes_nonmusical_private_queue_handoff import (
    reconcile_private_html_review_queue,
)
from ptitesondes_schemaorg_private_intake import (
    curated_schemaorg_sources, reconcile_schemaorg_hints, _source_url,
)
from ptitesondes_official_html_index_discovery import discover_live_html_event_pages
from ptitesondes_openagenda_v2_geo_fetch import fetch_official_page
from ptitesondes_family_national_scope import FAMILY_TYPES

SCHEMA = "ptitesondes.schemaorg_visible_session_private_recheck.v1"
MAX_CANDIDATES = 40
MAX_INDEX_SOURCES = 20


def _fair_batch(hints, today, limit, offset=0):
    """Select diverse municipalities, not only the highest-volume site."""
    city_groups = defaultdict(deque)
    for hint in sorted(hints, key=lambda x: (
            x["date_start"], x["start_local"], x["hint_id"])):
        city_groups[norm(hint["city"])].append(hint)
    names = sorted(city_groups)
    if not names:
        return []
    shift = (today.toordinal() + offset) % len(names)
    names = names[shift:] + names[:shift]
    rotation = deque(names)
    out = []
    while rotation and len(out) < limit:
        name = rotation.popleft()
        out.append(city_groups[name].popleft())
        if city_groups[name]:
            rotation.append(name)
    return out


def recheck_schemaorg_visible_sessions(
        existing_reviews, hints, today, manifest, timezone_pins,
        independent_context, *, limit=24, offset=0,
        index_reader=discover_live_html_event_pages,
        child_reader=fetch_official_page,
        proof_reader=corroborate_first_party_session):
    """Return separately validated PRIVATE review queue and anonymous counts.

    A positive first-party visible proof is still only ONE source; no source
    reuse policy, organizer ownership or geocoding can be self-attested.
    """
    if (type(today) is not date or type(limit) is not int
            or not 1 <= limit <= MAX_CANDIDATES
            or type(offset) is not int or offset < 0
            or not isinstance(independent_context, dict)):
        raise ValueError("invalid_schemaorg_visible_recheck")
    current = reconcile_private_html_review_queue(
        existing_reviews, [], today)["queue"]
    eligible_hints = reconcile_schemaorg_hints(hints, [], today)["queue"]
    sources = curated_schemaorg_sources(manifest, timezone_pins)
    by_host = {s["approved_host"]: s for s in sources}
    counts = {
        "schema": SCHEMA,
        "input_schemaorg_hints": len(hints),
        "future_schemaorg_hints": len(eligible_hints),
        "selected_hints": 0, "source_index_rechecked": 0,
        "source_indexes_unavailable": 0,
        "unregistered_source_hints_held": 0,
        "unclassified_hints_held": 0,
        "unlisted_on_current_index_held": 0,
        "child_pages_refetched": 0, "child_pages_unavailable": 0,
        "visible_same_block_sessions": 0,
        "without_visible_exact_session_held": 0,
        "first_party_packets_routed": 0,
        "new_private_review_sessions": 0,
        "rechecked_private_review_sessions": 0,
        "total_private_review_sessions": 0,
        "public_writes": 0, "publisher_connected": False,
        "publication_ready": False, "approved": False,
        "independent_organizer_or_rights_assumed": False,
    }
    selected = _fair_batch(eligible_hints, today, limit, offset)
    counts["selected_hints"] = len(selected)
    grouped = defaultdict(list)
    for hint in selected:
        host = urlsplit(hint["source_url"]).hostname
        source = by_host.get(host)
        if (source is None or not _source_url(
                hint["source_url"], source["approved_host"],
                source["child_prefix"])):
            counts["unregistered_source_hints_held"] += 1
        elif hint["category_hint_only"] not in FAMILY_TYPES:
            # Category hints are never silently recast as qualified family
            # outings. Unknown topics are kept in the original hint queue.
            counts["unclassified_hints_held"] += 1
        else:
            grouped[host].append(hint)
    if len(grouped) > MAX_INDEX_SOURCES:
        raise ValueError("too_many_recheck_sources")
    for host, rows in sorted(grouped.items()):
        source = by_host[host]
        pin = {"approved_host": host,
               "exact_index_url": source["index_url"]}
        try:
            fresh_index = index_reader(pin)
            if (type(fresh_index) is not dict
                    or fresh_index.get("stage") != "routing_suggestions_only"
                    or type(fresh_index.get("private_routing_proposals")) is not list):
                raise ValueError("source_index_not_current")
            current_links = {
                x.get("url") for x in fresh_index["private_routing_proposals"]
                if type(x) is dict and x.get("approved") is False
                and _source_url(x.get("url"), host, source["child_prefix"])
            }
            counts["source_index_rechecked"] += 1
        except (OSError, ValueError, KeyError, TypeError, TimeoutError):
            counts["source_indexes_unavailable"] += 1
            continue
        # Multiple exact clock slots may share one child page. Fetch once,
        # corroborate independently for each exact date/clock pair.
        pages = {}
        packets = []
        for row in rows:
            url = row["source_url"]
            if url not in current_links:
                counts["unlisted_on_current_index_held"] += 1
                continue
            if url not in pages:
                try:
                    fetched = child_reader({
                        "approved_host": host, "exact_url": url,
                    })
                    if (type(fetched) is not dict
                            or set(fetched) != {"url", "html"}
                            or fetched["url"] != url
                            or type(fetched["html"]) is not str):
                        raise ValueError("wrong_child_response")
                    pages[url] = fetched
                    counts["child_pages_refetched"] += 1
                except (OSError, ValueError, KeyError, TypeError, TimeoutError):
                    pages[url] = None
                    counts["child_pages_unavailable"] += 1
            page = pages[url]
            if page is None:
                continue
            lead = {
                "provider": "schemaorg_private_discovery_not_approval",
                "source_url": url, "title": row["title"],
                "city": row["city"], "venue": row["venue"],
                "date_start": row["date_start"], "date_end": row["date_start"],
                "start_local": row["start_local"],
                "category": row["category_hint_only"],
                "audience_claim": "unconfirmed_from_visible_source",
                "price_evidence": "not_stated",
                "registration_evidence": "not_stated",
            }
            try:
                visible = proof_reader(
                    lead, page, pin, source["child_prefix"])
                if (type(visible) is not dict
                        or visible.get("visible_exact_session") is not True
                        or visible.get("publication_ready") is not False
                        or visible.get("public_writes") != 0):
                    counts["without_visible_exact_session_held"] += 1
                    continue
            except (ValueError, TypeError, KeyError, OSError):
                counts["without_visible_exact_session_held"] += 1
                continue
            counts["visible_same_block_sessions"] += 1
            packets.append({
                "lead": lead, "page": page,
                "trusted_index": pin, "child_prefix": source["child_prefix"],
                "independent_context": independent_context,
            })
        # Do not trust proof_reader approval: private reconciler independently
        # re-runs the real first-party gate, audience and access checks.
        local_day = today
        routed = reconcile_private_html_review_queue(
            current, packets, local_day)
        current = routed["queue"]
        counts["first_party_packets_routed"] += len(packets)
        counts["new_private_review_sessions"] += routed["report"]["new_private_reviews"]
        counts["rechecked_private_review_sessions"] += routed["report"]["rechecked_private_reviews"]
    counts["total_private_review_sessions"] = len(current)
    return {"private_review_queue": current, "report": counts}
