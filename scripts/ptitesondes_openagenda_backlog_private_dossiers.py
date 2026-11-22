#!/usr/bin/env python3
"""Bridge existing PRIVATE OpenAgenda backlog clues to the first-party Publisher.

A collector/ODS entry is NEVER approval: resolve its agenda slug through the
live OpenAgenda directory, re-read the exact event UID, and submit only
untrusted day-bound research dossiers. The Publisher re-reads everything.
No named agenda, city, venue, organiser or category allowlist is used.
"""
import argparse
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener

from proof import norm
from ptitesondes_openagenda_national_event_research import _french_text
from ptitesondes_openagenda_public_agenda_index import NoRedirect
from ptitesondes_openagenda_v2_direct_evidence import (
    _valid_public_read_key, read_direct_v2,
)
from ptitesondes_open_world_municipal_bootstrap import _safe_research_lead
from ptitesondes_open_world_private_dossier_intake import (
    MAX_DOSSIERS, attach_research_dossiers, review_batch_for_cron,
)

API = "https://api.openagenda.com/v2/agendas"
ROOT = Path(__file__).resolve().parents[1]
MAX_BACKLOG = 4000
MAX_ATTEMPTS = 24  # network budget, never an editorial whitelist
MAX_RESPONSE = 120_000
MAX_TIMINGS = 800
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
    except ValueError:
        return None
    if not today <= day <= today + timedelta(days=184):
        return None
    if (url.scheme != "https" or url.hostname != "openagenda.com"
            or url.username or url.password or url.port not in (None, 443)
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


def build_backlog_dossiers(backlog, patch, published, today, key, *,
                           batch_index=0, agenda_reader=read_agenda_by_slug,
                           event_reader=read_direct_v2):
    if (type(backlog) is not list or len(backlog) > MAX_BACKLOG
            or type(today) is not date
            or type(batch_index) is not int or not 0 <= batch_index <= 3
            or type(published) is not dict or type(published.get("events")) is not list
            or not _valid_public_read_key(key)):
        raise ValueError("invalid_backlog_first_party_inputs")
    combined = attach_research_dossiers(patch, [], today)
    capacity = MAX_DOSSIERS - len(combined["open_world_research"])
    identities = sorted(set(
        identity for row in backlog
        if (identity := backlog_identity(row, today)) is not None
    ), key=lambda x: (x[2], x[0], x[1], x[3]))
    # Rotate four independent time slots and successive days. No named
    # source whitelist and no permanent blacklist; all clues remain eligible.
    start = ((today.toordinal() * 4 + batch_index) * MAX_ATTEMPTS
             % len(identities)) if identities else 0
    visited = attempts = holds = 0
    proposals = []
    cache = {}
    already = {x.get("id") for x in published["events"] if type(x) is dict}
    queue_keys = {
        (x["lead"]["event_uid"], x["date_start"])
        for x in combined["open_world_research"]
    }
    while capacity and visited < min(MAX_ATTEMPTS, len(identities)):
        slug, uid, day, title = identity = identities[(start + visited) % len(identities)]
        visited += 1
        if ("openagenda-" + str(uid) + "-" + day) in already or (uid, day) in queue_keys:
            continue
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
            proposals.append(dossier)
            queue_keys.add((uid, day))
            capacity -= 1
        except (OSError, ValueError, TimeoutError, KeyError, TypeError, UnicodeError):
            holds += 1
    result = attach_research_dossiers(combined, proposals, today)
    return result, {
        "backlog_candidates": len(identities), "clues_examined": visited,
        "live_events_read": attempts, "new_dossiers": len(proposals),
        "queued_total": len(result["open_world_research"]),
        "held_for_publisher_or_network": holds, "public_writes": 0,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backlog-file", type=Path, required=True)
    parser.add_argument("--patch-file", type=Path, required=True)
    parser.add_argument("--public-catalogue", type=Path, required=True)
    parser.add_argument("--output-file", type=Path, required=True)
    parser.add_argument("--day", type=date.fromisoformat, required=True)
    args = parser.parse_args()
    if (any(path.resolve().is_relative_to(ROOT)
            for path in (args.backlog_file, args.patch_file, args.output_file))
            or len({p.resolve() for p in (args.backlog_file, args.patch_file,
                                           args.output_file)}) != 3):
        raise ValueError("private_backlog_inputs_must_be_isolated")
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
        backlog, patch, published, args.day, key, batch_index=batch_index)
    args.output_file.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    # Only counts on public GitHub runners; private URLs/titles/UIDs hidden.
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
