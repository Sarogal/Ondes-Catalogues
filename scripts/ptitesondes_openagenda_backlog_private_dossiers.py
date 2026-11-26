#!/usr/bin/env python3
"""Bridge existing PRIVATE OpenAgenda backlog clues to the first-party Publisher.

A collector/ODS entry is NEVER approval: resolve its agenda slug through the
live OpenAgenda directory, re-read the exact event UID, and submit only
untrusted day-bound research dossiers. The Publisher re-reads everything.
No named agenda, city, venue, organiser or category allowlist is used.
"""
import argparse
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener

from proof import norm
from ptitesondes_editorial_refusal_memory import (
    digest, deferred, remember_refusal, fresh_memory, load_memory,
    MAX_QUEUE_RECHECKS, attempt_key, retain_active_attempts, mark_attempt,
)
from ptitesondes_national_backlog_bridge import _atomic_json
from ptitesondes_openagenda_national_event_research import _french_text
from ptitesondes_oa_evergreen_on_demand import ambiguous_on_demand_studio_series
from ptitesondes_openagenda_public_agenda_index import NoRedirect
from ptitesondes_openagenda_v2_direct_evidence import (
    _valid_public_read_key, read_direct_v2,
)
from ptitesondes_open_world_municipal_bootstrap import _safe_research_lead
from ptitesondes_open_world_private_dossier_intake import (
    MAX_DOSSIERS, attach_research_dossiers, fair_dossier_order,
    review_batch_for_cron,
)

API = "https://api.openagenda.com/v2/agendas"
ROOT = Path(__file__).resolve().parents[1]
MAX_BACKLOG = 4000
MAX_ATTEMPTS = 24  # network budget, never an editorial whitelist
# Reserve bounded, source-neutral verification capacity for imminent sessions.
# These are only untrusted leads; the Publisher still re-reads each live UID.
URGENT_WINDOW_DAYS = 3
URGENT_CYCLE_BUDGET = 8
MAX_RESPONSE = 120_000
MAX_TIMINGS = 800
MAX_EVERGREEN_RECHECKS = 8  # live UID reads per saturated cycle, not a session limit
SOURCE_PATH = re.compile(
    r"^/(?:fr/)?([a-z0-9][a-z0-9-]{0,100})/events/"
    r"([a-z0-9][a-z0-9_-]{0,220})/?$"
)
POSITIVE_UID = re.compile(r"[1-9][0-9]{0,11}\Z")


def backlog_identity(row, today):
    """Only extract hints; never mint a source/age/geo approval from ODS."""
    if (type(row) is not dict or row.get("collector") not in
            ("opendatasoft-index", "openagenda-v2")
            or type(row.get("external_id")) is not str
            or not POSITIVE_UID.fullmatch(row["external_id"])
            or type(row.get("source_url")) is not str
            or type(row.get("title")) is not str
            or not row["title"].strip()
            or type(row.get("date_start")) is not str):
        return None
    try:
        day = date.fromisoformat(row["date_start"])
        url = urlsplit(row["source_url"])
        port = url.port
    except ValueError:
        return None
    if not today <= day <= today + timedelta(days=184):
        return None
    if (url.scheme != "https" or url.hostname != "openagenda.com"
            or url.username or url.password or port not in (None, 443)
            or url.query or url.fragment):
        return None
    match = SOURCE_PATH.fullmatch(url.path)
    if match is None:
        return None
    slug, tail = match.groups()
    uid = int(row["external_id"])
    # If the event URL explicitly states an immutable UID, it MUST agree.
    prefix = re.match(r"([0-9]+)_", tail)
    if prefix and int(prefix.group(1)) != uid:
        return None
    return slug, uid, day.isoformat(), row["title"]


def read_agenda_by_slug(slug, public_key, *, opener=None):
    """Official OA v2 exact slug filter; fixed host and no redirect."""
    if (type(slug) is not str or
            re.fullmatch(r"[a-z0-9][a-z0-9-]{0,100}", slug) is None
            or not _valid_public_read_key(public_key)):
        raise ValueError("invalid_live_oa_slug_query")
    url = API + "?" + urlencode({"slug": slug, "size": 2})
    request = Request(url, headers={
        "key": public_key, "Accept": "application/json",
        "User-Agent": "PtitesOndesBacklogFirstPartyReadOnly/1.0",
    })
    fetch = opener or build_opener(NoRedirect()).open
    try:
        with fetch(request, timeout=20) as response:
            if response.status != 200 or response.geturl() != url:
                raise ValueError("oa_slug_unexpected_endpoint")
            body = response.read(MAX_RESPONSE + 1)
    except (OSError, TimeoutError) as exc:
        raise ValueError("oa_slug_source_unavailable") from exc
    if not body or len(body) > MAX_RESPONSE:
        raise ValueError("oa_slug_invalid_response_size")
    try:
        data = json.loads(body)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("oa_slug_invalid_json") from exc
    rows = data.get("agendas") if type(data) is dict else None
    if (type(rows) is not list or len(rows) != 1
            or type(rows[0]) is not dict
            or rows[0].get("slug") != slug
            or type(rows[0].get("uid")) is not int
            or not 0 < rows[0]["uid"] < 10**12):
        raise ValueError("oa_slug_not_unique_or_not_exact")
    return rows[0]


def live_research_dossier(identity, today, agenda, event):
    """Form an untrusted hint exclusively from LIVE OA fields and sessions."""
    slug, uid, day, legacy_title = identity
    if (type(agenda) is not dict or agenda.get("slug") != slug
            or type(agenda.get("uid")) is not int
            or not 0 < agenda["uid"] < 10**12):
        return None
    if type(event) is dict and "uid" not in event and type(event.get("event")) is dict:
        # Only an exact UID may be unwrapped; a conflicting top-level UID
        # must never be masked by a nested record.
        if type(event["event"].get("uid")) is int and event["event"]["uid"] == uid:
            event = event["event"]
    if (type(event) is not dict or type(event.get("uid")) is not int
            or event["uid"] != uid or event.get("state") != 2
            or event.get("removed") is True):
        return None
    title = _french_text(event, "title")
    if not title or norm(title) != norm(legacy_title):
        return None
    location = event.get("location")
    if type(location) is not dict:
        return None
    city, venue = location.get("adminLevel4"), location.get("name")
    if not all(type(v) is str and v.strip() for v in (city, venue)):
        return None
    raw = event.get("timings")
    if type(raw) is not list or len(raw) > MAX_TIMINGS:
        return None
    sessions, seen = [], set()
    for slot in raw:
        if type(slot) is not dict or type(slot.get("begin")) is not str or type(slot.get("end")) is not str:
            return None
        begin, end = slot["begin"], slot["end"]
        try:
            start, finish = datetime.fromisoformat(begin), datetime.fromisoformat(end)
        except ValueError:
            return None
        if (start.tzinfo is None or finish.tzinfo is None
                or start.utcoffset() is None or finish.utcoffset() is None
                or not start < finish or finish - start > timedelta(days=2)
                or len(begin) > 40 or len(end) > 40):
            return None
        if today <= start.date() <= today + timedelta(days=184):
            if (begin, end) in seen:
                return None
            seen.add((begin, end))
            sessions.append({"begin": begin, "end": end})
    if not any(x["begin"][:10] == day for x in sessions):
        return None
    lead = {
        "agenda_uid": agenda["uid"], "agenda_slug": slug,
        "event_uid": uid, "title": title,
        "city_unverified": city, "venue_unverified": venue,
        "country_code_unverified": location.get("countryCode"),
        "explicit_source_session_days": sorted({s["begin"][:10] for s in sessions}),
        "explicit_source_session_intervals": sessions,
        "publication_ready": False, "public_writes": 0,
    }
    if not _safe_research_lead(lead, today):
        return None
    exact = "https://openagenda.com/" + slug + "/events/" + str(uid)
    return {"lead": lead, "date_start": day,
            "official_event_url": exact, "official_venue_url": exact}


def reclaim_live_confirmed_on_demand(queue, public_key, agenda_reader, event_reader):
    """Free bounded Publisher slots only for live-confirmed commercial booking series.

    The private patch is a temporary research queue, not the durable backlog.
    Re-read the official agenda and UID before dropping any queued request;
    failures or ambiguous evidence preserve every request. No organizer, venue,
    territory or number-of-performances denylist is involved. A genuinely
    scheduled fifty-session youth event remains eligible.
    """
    grouped = {}
    for item in queue:
        lead = item.get("lead") if type(item) is dict else None
        if type(lead) is not dict:
            continue
        identity = (lead.get("agenda_slug"), lead.get("agenda_uid"),
                    lead.get("event_uid"))
        if (type(identity[0]) is not str or type(identity[1]) is not int
                or type(identity[2]) is not int):
            continue
        grouped[identity] = grouped.get(identity, 0) + 1
    confirmed = set()
    # High-volume UIDs first: one official read can reclaim dozens of slots.
    # The eight-read bound limits network work, never an event's sessions.
    ranked = sorted(grouped, key=lambda x: (-grouped[x], x))
    for slug, agenda_uid, event_uid in ranked[:MAX_EVERGREEN_RECHECKS]:
        try:
            agenda = agenda_reader(slug, public_key)
            if (type(agenda) is not dict
                    or agenda.get("slug") != slug
                    or agenda.get("uid") != agenda_uid):
                continue
            event = event_reader(agenda_uid, event_uid, public_key)
            if (type(event) is dict and "uid" not in event
                    and type(event.get("event")) is dict
                    and event["event"].get("uid") == event_uid):
                event = event["event"]
            if (type(event) is not dict or event.get("uid") != event_uid
                    or event.get("state") != 2
                    or event.get("removed") is True
                    or type(event.get("timings")) is not list):
                continue
            source_days = {
                slot["begin"][:10]: True for slot in event["timings"]
                if type(slot) is dict and type(slot.get("begin")) is str
            }
            if ambiguous_on_demand_studio_series(event, source_days):
                confirmed.add((slug, agenda_uid, event_uid))
        except (OSError, TimeoutError, ValueError, KeyError,
                TypeError, UnicodeError, OverflowError):
            continue

    if not confirmed:
        return queue, 0
    remaining = [
        item for item in queue
        if (item.get("lead", {}).get("agenda_slug"),
            item.get("lead", {}).get("agenda_uid"),
            item.get("lead", {}).get("event_uid")) not in confirmed
    ]
    return remaining, len(queue) - len(remaining)


def fair_backlog_identity_order(identities):
    """Rotate between agendas and original event UIDs before bounded API reads.

    The historical backlog may contain dozens of dates from the same busy
    source; chronological slicing alone can hide other French sources.
    Preserve every identity for later rounds, including long event series.
    """
    from collections import deque
    grouped = {}
    for slug, uid, day, title in sorted(
            identities, key=lambda x: (x[2], x[0], x[1], x[3])):
        grouped.setdefault(slug, {}).setdefault(uid, deque()).append(
            (slug, uid, day, title))
    pending_agendas = deque(sorted(grouped))
    pending_events = {
        slug: deque(sorted(events)) for slug, events in grouped.items()
    }
    result = []
    while pending_agendas:
        slug = pending_agendas.popleft()
        uid = pending_events[slug].popleft()
        queue = grouped[slug][uid]
        result.append(queue.popleft())
        if queue:
            pending_events[slug].append(uid)
        if pending_events[slug]:
            pending_agendas.append(slug)
    return result


def deadline_aware_backlog_batch(identities, today, batch_index):
    """Reserve eight of 24 reads for sessions expiring within three days.

    Keep rotating every other identity fairly, regardless of geography,
    organizer, venue or genre. If no urgent session exists, retain the
    established 24-per-slot rotation unchanged. The private backlog keeps
    all unselected leads for a later cycle; this is never an approval.
    """
    if (type(today) is not date or type(batch_index) is not int
            or not 0 <= batch_index <= 3):
        raise ValueError("invalid_deadline_aware_rotation")
    if not identities:
        return []
    cycle = today.toordinal() * 4 + batch_index
    threshold = (today + timedelta(days=URGENT_WINDOW_DAYS)).isoformat()
    urgent = [row for row in identities if row[2] <= threshold]
    if not urgent:
        start = cycle * MAX_ATTEMPTS % len(identities)
        return [identities[(start + i) % len(identities)]
                for i in range(min(MAX_ATTEMPTS, len(identities)))]
    ordinary = [row for row in identities if row[2] > threshold]
    urgency_count = min(URGENT_CYCLE_BUDGET, len(urgent))
    urgent_start = cycle * URGENT_CYCLE_BUDGET % len(urgent)
    selected = [urgent[(urgent_start + i) % len(urgent)]
                for i in range(urgency_count)]
    if ordinary:
        # Advance by the reserved non-urgent budget, not by total backlog:
        # urgent and ordinary runs therefore progress independently.
        ordinary_start = (cycle * (MAX_ATTEMPTS - URGENT_CYCLE_BUDGET)
                          % len(ordinary))
        selected.extend(
            ordinary[(ordinary_start + i) % len(ordinary)]
            for i in range(min(MAX_ATTEMPTS - len(selected), len(ordinary)))
        )
    # Small/empty ordinary lists must not waste the remaining read budget.
    remaining = min(MAX_ATTEMPTS - len(selected), len(urgent) - urgency_count)
    selected.extend(
        urgent[(urgent_start + urgency_count + i) % len(urgent)]
        for i in range(remaining)
    )
    return selected


def persistent_backlog_batch(identities, today, memory, clues):
    """Least-recently attempted rotation; no fixed slot can repeat a batch.

    Keep the established source interleaving as the stable tie-breaker and
    reserve urgent capacity independently. Attempts, including transient
    failures, are advisory ordering only, never denials or admissions.
    """
    threshold = (today + timedelta(days=URGENT_WINDOW_DAYS)).isoformat()
    ordered = sorted(identities, key=lambda identity:
                     memory["attempts"].get(attempt_key(identity, clues[identity]), 0))
    urgent = [row for row in ordered if row[2] <= threshold]
    ordinary = [row for row in ordered if row[2] > threshold]
    urgent_count = min(URGENT_CYCLE_BUDGET, len(urgent))
    chosen = urgent[:urgent_count]
    chosen.extend(ordinary[:MAX_ATTEMPTS - len(chosen)])
    chosen.extend(urgent[urgent_count:urgent_count + MAX_ATTEMPTS - len(chosen)])
    return chosen


def reclaim_editorial_queue(queue, clues, published, today, now, key,
                            memory, agenda_reader, event_reader):
    """Reclaim only exact direct-OA requests recoverable from durable history."""
    candidates = []
    remaining = []
    cached = 0
    for item in queue:
        lead = item["lead"]
        ident = (lead.get("agenda_slug"), lead.get("event_uid"),
                 item.get("date_start"), lead.get("title"))
        if (type(ident[0]) is not str or type(ident[1]) is not int
                or type(ident[2]) is not str or type(ident[3]) is not str
                or ident not in clues):
            remaining.append(item)
            continue
        slug, uid, day, title = ident
        canonical = "https://openagenda.com/" + slug + "/events/" + str(uid)
        # No municipal/other independent proof route may be suppressed.
        if (item["official_event_url"] != canonical
                or item["official_venue_url"] != canonical
                or item.get("municipal_source_reference_url") is not None):
            remaining.append(item)
            continue
        if deferred(memory, ident, clues[ident], today, now):
            cached += 1
            continue
        candidates.append((ident, item))
    candidates.sort(key=lambda pair: pair[0])
    confirmed = set()
    checked = 0
    if candidates:
        start = memory["cursor"] % len(candidates)
        for offset in range(min(len(candidates), MAX_QUEUE_RECHECKS)):
            ident, item = candidates[(start + offset) % len(candidates)]
            slug, uid, day, _ = ident
            try:
                agenda = agenda_reader(slug, key)
                if (type(agenda) is not dict
                        or agenda.get("uid") != item["lead"]["agenda_uid"]):
                    continue
                event = event_reader(agenda["uid"], uid, key)
                checked += 1
                live = live_research_dossier(ident, today, agenda, event)
                if live is not None and remember_refusal(
                        memory, ident, clues[ident], live, agenda, event,
                        published, today, now):
                    confirmed.add(ident)
            except (OSError, ValueError, TimeoutError, KeyError, TypeError, UnicodeError):
                continue
        memory["cursor"] = (memory["cursor"] + MAX_QUEUE_RECHECKS) % 10**12
    # Preserve original queue order, not the sort used for bounded rechecks.
    keep = {id(item) for item in remaining}
    keep.update(id(item) for ident, item in candidates if ident not in confirmed)
    return [item for item in queue if id(item) in keep], cached, len(confirmed), checked


def cycle_cached_reader(reader, counters, label):
    """Reuse only successful reads within this invocation, not across runs.

    Each date still passes exact live UID, session and editorial checks.
    The independent Publisher receives no cached authority or proof.
    """
    cache = {}

    def read(*args):
        if args in cache:
            counters[label + "_reused"] += 1
            return deepcopy(cache[args])
        counters[label + "_requests"] += 1
        value = reader(*args)
        if type(value) is dict:
            cache[args] = deepcopy(value)
        return value

    return read


def build_backlog_dossiers(backlog, patch, published, today, key, *,
                           batch_index=0, agenda_reader=read_agenda_by_slug,
                           event_reader=read_direct_v2, refusal_memory=None,
                           as_of_utc=None):
    if (type(backlog) is not list or len(backlog) > MAX_BACKLOG
            or type(today) is not date
            or type(batch_index) is not int or not 0 <= batch_index <= 3
            or type(published) is not dict or type(published.get("events")) is not list
            or not _valid_public_read_key(key)):
        raise ValueError("invalid_backlog_first_party_inputs")
    network = {"agenda_requests": 0, "agenda_reused": 0,
               "event_requests": 0, "event_reused": 0}
    agenda_reader = cycle_cached_reader(agenda_reader, network, "agenda")
    event_reader = cycle_cached_reader(event_reader, network, "event")
    already = {x.get("id") for x in published["events"] if type(x) is dict}
    # Old private research may refer to occurrences now published by another
    # successful cloud cycle. Prune these BEFORE measuring queue capacity;
    # the normal Publisher also rejects duplicates, but a full queue of
    # already-published requests can starve all newly discovered places.
    # Expired sessions are still historical backlog leads, not actionable
    # future research slots; preserve the backlog file, not the stale queue.
    future_pending = [
        item for item in patch.get("open_world_research", [])
        if (type(item) is not dict
            or type(item.get("date_start")) is not str
            or item["date_start"] >= today.isoformat())
    ]
    # The old patch may be saturated by already-refused commercial booking
    # availabilities. Reclaim capacity only after fresh exact UID-bound
    # OpenAgenda evidence confirms the SAME generic Publisher hold. This
    # changes no published data and never deletes the durable private leads.
    reclaimed = 0
    if len(future_pending) >= MAX_DOSSIERS:
        future_pending, reclaimed = reclaim_live_confirmed_on_demand(
            future_pending, key, agenda_reader, event_reader)
    current = dict(patch, open_world_research=future_pending)
    combined = attach_research_dossiers(
        current, [], today, published_ids=already)
    now = as_of_utc or datetime.now(timezone.utc)
    clues = {}
    cached_queue = confirmed_queue = queue_reads = deferred_clues = new_refusals = 0
    if refusal_memory is not None:
        # All duplicates of a clue contribute to its fingerprint. A changed
        # collector hint invalidates the deferral at the next collection.
        by_identity = {}
        for row in backlog:
            identity = backlog_identity(row, today)
            if identity is not None:
                by_identity.setdefault(identity, set()).add(digest(row))
        clues = {identity: digest(sorted(hashes))
                 for identity, hashes in by_identity.items()}
        refreshed = fresh_memory(refusal_memory, now)
        refusal_memory.clear()
        refusal_memory.update(refreshed)
        retain_active_attempts(refusal_memory, {
            attempt_key(identity, fingerprint) for identity, fingerprint in clues.items()})
        queue, cached_queue, confirmed_queue, queue_reads = reclaim_editorial_queue(
            combined["open_world_research"], clues, published, today, now,
            key, refusal_memory, agenda_reader, event_reader)
        combined = dict(combined, open_world_research=queue)
    # A research queue can be filled entirely by a single agenda's long
    # series before this independent historical OA backlog is examined.
    # A full queue is a *per-run work budget*, never a permanent exclusion
    # of other first-party sources. Recheck one bounded backlog batch even
    # when no free slot remains, then fairly interleave ALL source agendas
    # before applying the existing 80-dossier Publisher budget.
    capacity = MAX_DOSSIERS - len(combined["open_world_research"])
    identities = fair_backlog_identity_order(set(
        identity for row in backlog
        if (identity := backlog_identity(row, today)) is not None
    ))
    queue_keys = {
        (x["lead"]["event_uid"], x["date_start"])
        for x in combined["open_world_research"]
    }
    # Classify before reserving the bounded network slots. Published and
    # already queued occurrences need no duplicate research read; keeping
    # them in the historical store must not consume the active budget.
    active = []
    already_published = already_queued = 0
    for identity in identities:
        _, uid, day, _ = identity
        if ("openagenda-" + str(uid) + "-" + day) in already:
            already_published += 1
        elif (uid, day) in queue_keys:
            already_queued += 1
        elif refusal_memory is not None and deferred(
                refusal_memory, identity, clues[identity], today, now):
            deferred_clues += 1
        else:
            active.append(identity)
    # No permanent blacklist: a future run rebuilds the active view from
    # the full history and the current public catalogue and pending queue.
    ordered_active = fair_backlog_identity_order(active)
    review_order = (persistent_backlog_batch(ordered_active, today, refusal_memory, clues)
                    if refusal_memory is not None else
                    deadline_aware_backlog_batch(ordered_active, today, batch_index))
    visited = attempts = holds = 0
    proposals = []
    cache = {}
    # Preserve the established append-only queue behavior while ordinary
    # free capacity exists. Only a genuinely saturated queue may fairly
    # preempt old research requests from durable source inventories.
    review_budget = capacity if capacity > 0 else MAX_ATTEMPTS
    while (len(proposals) < review_budget
           and visited < len(review_order)):
        slug, uid, day, title = identity = review_order[visited]
        visited += 1
        if ("openagenda-" + str(uid) + "-" + day) in already or (uid, day) in queue_keys:
            continue
        if refusal_memory is not None:
            mark_attempt(refusal_memory, attempt_key(identity, clues[identity]))
        try:
            if slug not in cache:
                cache[slug] = agenda_reader(slug, key)
            agenda = cache[slug]
            if type(agenda) is not dict or type(agenda.get("uid")) is not int:
                holds += 1
                continue
            event = event_reader(agenda["uid"], uid, key)
            attempts += 1
            dossier = live_research_dossier(identity, today, agenda, event)
            if dossier is None:
                holds += 1
                continue
            if refusal_memory is not None and remember_refusal(
                    refusal_memory, identity, clues[identity], dossier, agenda,
                    event, published, today, now):
                new_refusals += 1
                continue
            proposals.append(dossier)
            queue_keys.add((uid, day))
        except (OSError, ValueError, TimeoutError, KeyError, TypeError, UnicodeError):
            holds += 1
    pending = combined["open_world_research"]
    if len(pending) + len(proposals) <= MAX_DOSSIERS:
        result = attach_research_dossiers(
            combined, proposals, today, published_ids=already)
    else:
        # The original national observation and historical source backlog
        # remain the durable discovery stores. No source, agenda or UID is
        # permanently blacklisted; later rotations can resubmit unattended
        # series. Round-robin across agendas and UIDs before truncation
        # prevents a single everyday booking series from consuming 60/80
        # slots while new territories remain unreviewed.
        balanced = fair_dossier_order([*pending, *proposals])
        result = attach_research_dossiers(
            dict(combined, open_world_research=[]),
            balanced[:MAX_DOSSIERS], today, published_ids=already)
    return result, {
        "backlog_candidates": len(identities),
        "active_backlog_candidates": len(active),
        "backlog_candidates_already_published": already_published,
        "backlog_candidates_already_queued": already_queued,
        "clues_examined": visited,
        "live_events_read": attempts,
        "new_dossiers": sum(
            1 for row in result["open_world_research"] if row in proposals),
        "reviewed_not_selected_this_cycle": max(
            0, len(pending) + len(proposals) - MAX_DOSSIERS),
        "source_read_proposals": len(proposals),
        "queued_total": len(result["open_world_research"]),
        "live_confirmed_commercial_slots_reclaimed": reclaimed,
        "editorial_cached_queue_deferred": cached_queue,
        "editorial_live_queue_deferred": confirmed_queue,
        "editorial_queue_live_reads": queue_reads,
        "editorial_cached_backlog_deferred": deferred_clues,
        "editorial_new_live_refusals": new_refusals,
        "held_for_publisher_or_network": holds, "public_writes": 0,
        **network,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backlog-file", type=Path, required=True)
    parser.add_argument("--patch-file", type=Path, required=True)
    parser.add_argument("--public-catalogue", type=Path, required=True)
    parser.add_argument("--output-file", type=Path, required=True)
    parser.add_argument("--day", type=date.fromisoformat, required=True)
    parser.add_argument("--refusal-state", type=Path)
    parser.add_argument("--refusal-output", type=Path)
    args = parser.parse_args()
    if (any(path.resolve().is_relative_to(ROOT)
            for path in (args.backlog_file, args.patch_file, args.output_file))
            or len({p.resolve() for p in (args.backlog_file, args.patch_file,
                                           args.output_file)}) != 3):
        raise ValueError("private_backlog_inputs_must_be_isolated")
    if (args.refusal_state is None) != (args.refusal_output is None):
        raise ValueError("both_private_refusal_paths_required")
    if args.refusal_state is not None:
        paths = [args.backlog_file, args.patch_file, args.output_file,
                 args.public_catalogue, args.refusal_state, args.refusal_output]
        if (len({p.resolve() for p in paths}) != len(paths)
                or any(p.resolve().is_relative_to(ROOT)
                       for p in (args.refusal_state, args.refusal_output))):
            raise ValueError("private_refusal_paths_must_be_isolated")
    now = datetime.now(timezone.utc)
    memory = load_memory(args.refusal_state, now) if args.refusal_state is not None else None
    key = os.environ.get("OPENAGENDA_READ_KEY", "")
    with args.backlog_file.open(encoding="utf-8") as stream:
        backlog = json.load(stream)
    with args.patch_file.open(encoding="utf-8") as stream:
        patch = json.load(stream)
    with args.public_catalogue.open(encoding="utf-8") as stream:
        published = json.load(stream)
    batch_index = review_batch_for_cron(
        os.environ.get("REVIEW_CRON", ""), datetime.now(timezone.utc).hour)
    result, summary = build_backlog_dossiers(
        backlog, patch, published, args.day, key, batch_index=batch_index,
        refusal_memory=memory, as_of_utc=now)
    args.output_file.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    if memory is not None:
        _atomic_json(args.refusal_output, memory)
    # Only counts on public GitHub runners; private URLs/titles/UIDs hidden.
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
