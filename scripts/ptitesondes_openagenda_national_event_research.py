#!/usr/bin/env python3
"""Private read-only exploration of future events in newly discovered OA agendas.

The upstream national index (#547) discovers agendas without a city/venue list.
This reader pages one chosen agenda using the official /v2/agendas/UID/events
API and proposes radio-aligned children events. Source/organiser/rights,
geometry, attendance and sessions remain UNVERIFIED FOR PUBLICATION.
No public patch, scheduler, registry modification or publisher access.
"""
import argparse
from collections import Counter
from datetime import date, datetime, timedelta
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler

from proof import norm
from ptitesondes_candidate_promotion import category_for
from ptitesondes_family_activity_classification import (
    ADULT_ONLY, propose_family_activity,
)
from ptitesondes_openagenda_public_agenda_index import (
    SCHEMA as INDEX_SCHEMA, SLUG as AGENDA_SLUG,
)
from ptitesondes_openagenda_v2_direct_evidence import (
    API_ORIGIN, _valid_public_read_key, read_direct_agenda_v2,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "ptitesondes.private_oa_agenda_event_exploration.v1"
STATE_SCHEMA = "ptitesondes.private_oa_event_exploration_cursor.v1"
MAX_PAGE_EVENTS = 20
MAX_PAGES = 3
MAX_BYTES = 1_500_000
MAX_INDEX_BYTES = 750_000
MAX_TIMINGS = 800
MAX_REPORT_EVENTS = MAX_PAGE_EVENTS * MAX_PAGES
COUNTRY_CODES = frozenset((
    "FR", "GP", "MQ", "GF", "RE", "YT", "PF", "NC", "WF", "PM", "BL", "MF",
))
TOKEN = re.compile(r"[a-zA-Z0-9_.~-]{1,64}\Z")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def valid_after(value):
    """Event cursors are STRINGS, unlike the national agenda index cursors."""
    return (isinstance(value, list) and 1 <= len(value) <= 8
            and all(isinstance(v, str) and TOKEN.fullmatch(v) is not None
                    for v in value))


def select_index_candidate(document, candidate_index):
    """Read an index result ONLY as an untrusted source research queue."""
    if (not isinstance(document, dict) or
            document.get("schema") != INDEX_SCHEMA or
            document.get("mode") != "private_index_readonly_discovery_not_admission"
            or document.get("publication_ready") is not False or
            document.get("public_writes") != 0 or
            not isinstance(document.get("new_agenda_candidates"), list) or
            type(candidate_index) is not int or candidate_index < 0):
        raise ValueError("invalid_private_index_report")
    candidates = document["new_agenda_candidates"]
    if not candidates or candidate_index >= len(candidates) or len(candidates) > 160:
        raise ValueError("agenda_candidate_index_out_of_range")
    seen = set()
    for entry in candidates:
        if not isinstance(entry, dict):
            raise ValueError("invalid_private_agenda_candidate")
        uid, slug = entry.get("agenda_uid"), entry.get("agenda_slug")
        if (type(uid) is not int or not 0 < uid < 10**12 or uid in seen
                or not isinstance(slug, str)
                or AGENDA_SLUG.fullmatch(slug) is None
                or entry.get("source_identity_only") is not True
                or entry.get("publisher_enabled") is not False):
            raise ValueError("invalid_private_agenda_candidate")
        seen.add(uid)
    return {"agenda_uid": candidates[candidate_index]["agenda_uid"],
            "agenda_slug": candidates[candidate_index]["agenda_slug"]}


def _french_text(row, key):
    obj = row.get(key)
    if isinstance(obj, str):
        return obj[:5000]
    if not isinstance(obj, dict):
        return ""
    return (obj.get("fr") if isinstance(obj.get("fr"), str) else "")[:5000]


def _time_days(timings, today):
    """Only explicit timezone-aware actual intervals; no guessed recurrence."""
    if not isinstance(timings, list) or len(timings) > MAX_TIMINGS:
        return [], "timings_invalid_or_too_many"
    dates = set()
    for timing in timings:
        if not isinstance(timing, dict):
            continue
        start, end = timing.get("begin"), timing.get("end")
        if not isinstance(start, str) or not isinstance(end, str):
            continue
        try:
            begin, finish = datetime.fromisoformat(start), datetime.fromisoformat(end)
        except ValueError:
            continue
        if (begin.tzinfo is None or finish.tzinfo is None
                or begin.utcoffset() is None or finish.utcoffset() is None
                or not begin < finish or finish - begin > timedelta(days=2)):
            continue
        if today <= begin.date() <= today + timedelta(days=184):
            dates.add(begin.date().isoformat())
    return sorted(dates), ("explicit_future_intervals" if dates
                           else "no_usable_future_dated_session")


def propose_event(row, agenda, today):
    """Source research item, NEVER proof of rights, official venue or approval."""
    base = {"decision": "research_only", "publication_ready": False,
            "official_organiser_verified": False, "rights_reviewed": False,
            "location_verified": False, "session_verified": False,
            "public_writes": 0}
    if (not isinstance(row, dict) or type(row.get("uid")) is not int or
            not 0 < row["uid"] < 10**12 or
            row.get("removed") is True or
            row.get("state") != 2):
        return None, "invalid_or_nonpublic_event"
    status = row.get("status")
    if status not in (1, {"id": 1}):
        return None, "cancelled_or_unconfirmed_event"
    title, desc = _french_text(row, "title"), _french_text(row, "description")
    if not title or len(title) > 300:
        return None, "no_french_title"
    combined = norm(title + " " + desc)
    if ADULT_ONLY.search(combined):
        return None, "explicit_adults_only"
    music = category_for(title, desc)
    # Some radio-relevant forms have no literal "concert" or "musical"
    # in their title. Keep precise child-audience and activity cues.
    if not music and re.search(
            r"\b(?:enfant|jeune public|famill|bebe|tout petit)", combined):
        if re.search(r"\b(?:comptines|chansons? pour enfants|chansons? enfantines)\b",
                     combined):
            music = ("eveil-musical", "Éveil musical")
        elif re.search(
                r"\b(?:atelier sonore|decouverte des instruments)\b",
                combined):
            music = ("atelier-musical", "Atelier musical")
    family = (propose_family_activity(title, desc)
              if not music else None)
    if music:
        category = music[0]
        label = music[1]
    elif family and family["category_proposal"]:
        category = family["category_proposal"]
        label = family["category_label_proposal"]
    else:
        return None, "editorial_evidence_not_yet_recognised"
    location = row.get("location")
    if not isinstance(location, dict):
        location = {}
    city, venue = location.get("adminLevel4"), location.get("name")
    if not isinstance(city, str) or not 0 < len(city.strip()) <= 120:
        city = None
    if not isinstance(venue, str) or not 0 < len(venue.strip()) <= 180:
        venue = None
    country = location.get("countryCode")
    country_hint = (country in COUNTRY_CODES if isinstance(country, str)
                    else False)
    dates, session_reason = _time_days(row.get("timings"), today)
    result = {**base, "agenda_uid": agenda["agenda_uid"],
              "agenda_slug": agenda["agenda_slug"], "event_uid": row["uid"],
              "title": title, "editorial_category_proposal": category,
              "editorial_category_label": label,
              "city_unverified": city, "venue_unverified": venue,
              "country_code_unverified": country,
              "french_territory_claim_present": country_hint,
              "explicit_source_session_days": dates,
              "session_research_status": session_reason,
              "requires_new_venue_search": bool(city and venue),
              "decision": "candidate_for_independent_qualification"}
    return result, "editorial_candidate"


def read_events_page(agenda_uid, public_read_key, after=None, *,
                     size=MAX_PAGE_EVENTS, opener=None):
    """GET public future events, no keyword or known-venue filtering."""
    if (type(agenda_uid) is not int or not 0 < agenda_uid < 10**12
            or not _valid_public_read_key(public_read_key)
            or type(size) is not int or not 1 <= size <= MAX_PAGE_EVENTS
            or (after is not None and not valid_after(after))):
        raise ValueError("invalid_private_events_request")
    params = [("size", str(size)), ("relative[]", "current"),
              ("relative[]", "upcoming"), ("monolingual", "fr"),
              ("detailed", "1")]
    if after is not None:
        params += [("after[]", value) for value in after]
    url = (API_ORIGIN + "/v2/agendas/" + str(agenda_uid)
           + "/events?" + urlencode(params))
    req = Request(url, headers={
        "key": public_read_key, "Accept": "application/json",
        "User-Agent": "PtitesOndesNationalEventsResearchReadOnly/1.0",
    })
    fetch = opener or build_opener(NoRedirect()).open
    try:
        with fetch(req, timeout=24) as resp:
            if resp.status != 200 or resp.geturl() != url:
                raise ValueError("unexpected_oa_events_endpoint")
            raw = resp.read(MAX_BYTES + 1)
    except (OSError, TimeoutError):
        raise ValueError("public_oa_events_unavailable") from None
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError("public_oa_events_size_invalid")
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise ValueError("invalid_public_events_json") from None
    return validate_events_page(data, after, size)


def validate_events_page(data, old_cursor=None, size=MAX_PAGE_EVENTS):
    if not isinstance(data, dict) or not isinstance(data.get("events"), list):
        raise ValueError("invalid_event_page")
    rows = data["events"]
    if len(rows) > size:
        raise ValueError("unbounded_event_page")
    next_cursor = data.get("after")
    if next_cursor is not None and (not valid_after(next_cursor)
                                   or next_cursor == old_cursor or not rows):
        raise ValueError("invalid_event_page_cursor")
    identities = []
    for row in rows:
        if not isinstance(row, dict) or type(row.get("uid")) is not int:
            raise ValueError("invalid_event_identity_in_page")
        identities.append(row["uid"])
    if len(set(identities)) != len(identities):
        raise ValueError("duplicate_event_uid_in_page")
    return {"events": rows, "after": next_cursor}


def scan_agenda(agenda, public_key, today, *, after=None, pages=MAX_PAGES,
                read_agenda=read_direct_agenda_v2, read_page=read_events_page):
    if (not isinstance(agenda, dict)
            or type(agenda.get("agenda_uid")) is not int
            or not isinstance(agenda.get("agenda_slug"), str)
            or AGENDA_SLUG.fullmatch(agenda["agenda_slug"]) is None
            or not _valid_public_read_key(public_key)
            or type(today) is not date
            or type(pages) is not int or not 1 <= pages <= MAX_PAGES
            or (after is not None and not valid_after(after))):
        raise ValueError("invalid_agenda_research_inputs")
    uid = agenda["agenda_uid"]
    direct = read_agenda(uid, public_key)
    if (not isinstance(direct, dict)
            or str(direct.get("uid")) != str(uid)
            or direct.get("slug") != agenda["agenda_slug"]):
        raise ValueError("independent_agenda_uid_slug_mismatch")
    cursor = after
    seen_cursor = {tuple(after)} if after is not None else set()
    seen_uid = set()
    counters = Counter()
    leads = []
    done = False
    for _ in range(pages):
        page = read_page(uid, public_key, cursor, size=MAX_PAGE_EVENTS)
        result = validate_events_page(page, cursor)
        counters["pages_read"] += 1
        for row in result["events"]:
            if row["uid"] in seen_uid:
                raise ValueError("repeated_event_in_paginated_scan")
            seen_uid.add(row["uid"])
            counters["public_event_uids_seen"] += 1
            proposed, reason = propose_event(row, agenda, today)
            counters[reason] += 1
            if proposed is not None:
                leads.append(proposed)
        cursor = result["after"]
        if cursor is None:
            done = True
            break
        if tuple(cursor) in seen_cursor:
            raise ValueError("repeated_event_pagination_cursor")
        seen_cursor.add(tuple(cursor))
    return {
        "schema": SCHEMA, "mode": "private_research_event_leads_only",
        "agenda_uid": uid, "agenda_slug": agenda["agenda_slug"],
        "counts": dict(sorted(counters.items())),
        "event_leads": leads,
        "next_cursor": cursor, "agenda_scan_complete": done,
        "no_publisher_bridge": True, "publication_ready": False,
        "public_writes": 0,
    }


def _private_directory(path):
    if (path.is_symlink() or not path.is_dir()
            or path.resolve().is_relative_to(ROOT)
            or path.stat().st_mode & 0o077):
        raise ValueError("private_workspace_directory_required")


def _private_input(path, max_bytes):
    _private_directory(path.parent)
    if (path.is_symlink() or not path.is_file()
            or not 0 < path.stat().st_size <= max_bytes):
        raise ValueError("private_input_invalid")
    return path.read_bytes()


def _state(path, source_digest, agenda_uid):
    _private_directory(path.parent)
    if path.is_symlink():
        raise ValueError("private_state_symlink_forbidden")
    if not path.exists():
        return {"schema": STATE_SCHEMA, "source_sha256": source_digest,
                "agenda_uid": agenda_uid, "after": None, "complete": False}
    raw = _private_input(path, 2000)
    state = json.loads(raw)
    if (not isinstance(state, dict) or
            set(state) != {"schema", "source_sha256", "agenda_uid", "after", "complete"}
            or state["schema"] != STATE_SCHEMA
            or state["source_sha256"] != source_digest
            or state["agenda_uid"] != agenda_uid
            or state["complete"] not in (True, False)
            or (state["after"] is not None and not valid_after(state["after"]))):
        raise ValueError("private_cursor_state_mismatch")
    return state


def _write_new(path, data):
    _private_directory(path.parent)
    if path.exists() or path.is_symlink():
        raise ValueError("private_report_must_be_unique")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        json.dump(data, out, ensure_ascii=False, indent=2)
        out.write("\n")


def _write_state(path, obj):
    _private_directory(path.parent)
    if path.is_symlink():
        raise ValueError("private_state_symlink_forbidden")
    fd, name = tempfile.mkstemp(prefix=".oa-event-state-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(obj, out, ensure_ascii=False)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--private-agenda-index-report", type=Path, required=True)
    ap.add_argument("--candidate-index", type=int, required=True)
    ap.add_argument("--private-cursor-state", type=Path, required=True)
    ap.add_argument("--output-private-report", type=Path, required=True)
    ap.add_argument("--day", type=date.fromisoformat, required=True)
    ap.add_argument("--execute-live", action="store_true")
    args = ap.parse_args()
    all_paths = (args.private_agenda_index_report.resolve(),
                 args.private_cursor_state.resolve(),
                 args.output_private_report.resolve())
    if len(set(all_paths)) != 3:
        raise ValueError("private_input_state_output_must_be_separate")
    raw = _private_input(args.private_agenda_index_report, MAX_INDEX_BYTES)
    digest = sha256(raw).hexdigest()
    document = json.loads(raw)
    agenda = select_index_candidate(document, args.candidate_index)
    state = _state(args.private_cursor_state, digest, agenda["agenda_uid"])
    _private_directory(args.output_private_report.parent)
    if args.output_private_report.exists() or args.output_private_report.is_symlink():
        raise ValueError("private_report_must_be_unique")
    if state["complete"]:
        raise ValueError("private_agenda_scan_already_completed")
    if not args.execute_live:
        print(json.dumps({"mode": "dry_run_no_network",
                          "candidate_index": args.candidate_index,
                          "cursor_present": state["after"] is not None,
                          "public_writes": 0}))
        return
    key = os.environ.get("OPENAGENDA_READ_KEY", "")
    report = scan_agenda(agenda, key, args.day, after=state["after"])
    next_state = {"schema": STATE_SCHEMA, "source_sha256": digest,
                  "agenda_uid": agenda["agenda_uid"],
                  "after": report["next_cursor"],
                  "complete": report["agenda_scan_complete"]}
    _write_new(args.output_private_report, report)
    _write_state(args.private_cursor_state, next_state)
    # No names, UID, event titles or private paths in public Actions stdout.
    print(json.dumps({"mode": report["mode"], "counts": report["counts"],
                      "agenda_scan_complete": report["agenda_scan_complete"],
                      "public_writes": 0}))


if __name__ == "__main__":
    main()
