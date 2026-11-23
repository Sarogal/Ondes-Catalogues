#!/usr/bin/env python3
"""Read-only national watch of already published OpenAgenda outing series.

Inspect the UID-bound first-party record, never a guessed page or stale
collector hint. Emit a change signal, NOT a withdrawal, correction or source
approval. Unknown/network errors never imply cancellation. All first-party
sources are dynamically derived from current public records.
"""
import argparse
from collections import Counter
from datetime import date, datetime, timedelta, timezone as dt_timezone
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from ptitesondes_openagenda_v2_direct_evidence import (read_direct_v2, FR_TZ, MAX_TIMINGS, _time)

EVENT_ID = re.compile(r"openagenda-([1-9][0-9]{0,11})-(20[0-9]{2}-[0-9]{2}-[0-9]{2})\Z")
EVENT_SOURCE = re.compile(
    r"/([a-z0-9][a-z0-9-]*)/events/([1-9][0-9]{0,11})_([a-z0-9][a-z0-9-]*)/?\Z")
MAX_SCAN = 30
MAX_INPUT = 12_000_000
MAX_EVENTS = 20000
ALLOWED_REASONS = frozenset((
    "cancelled_or_removed", "source_unpublished", "source_moved_online",
    "source_postponed", "source_sold_out",
    "source_session_missing", "source_session_time_changed",
    "source_new_future_session", "venue_name_changed", "city_changed",
    "venue_coordinates_changed", "source_identity_changed",
    "source_unavailable", "unusable_source_timings",
    "published_identity_invalid",
))


def index_published(document, today):
    """Group exact existing OpenAgenda IDs without any closed agenda registry."""
    if (type(document) is not dict or type(document.get("events")) is not list
            or len(document["events"]) > MAX_EVENTS or type(today) is not date):
        raise ValueError("invalid_published_catalogue_for_watch")
    result = {}
    for published in document["events"]:
        if not isinstance(published, dict):
            raise ValueError("invalid_public_event_for_watch")
        event_id = published.get("id")
        if not isinstance(event_id, str):
            continue
        match = EVENT_ID.fullmatch(event_id)
        if match is None:
            continue
        uid, day = int(match[1]), match[2]
        try:
            if date.fromisoformat(day) < today:
                continue
        except ValueError:
            continue
        url = published.get("source_url")
        if type(url) is not str:
            continue
        try:
            source = urlsplit(url)
        except ValueError:
            continue
        urlmatch = EVENT_SOURCE.fullmatch(source.path)
        if (source.scheme != "https" or source.hostname != "openagenda.com"
                or source.username or source.password or source.fragment
                or source.port not in (None, 443)
                or not urlmatch or int(urlmatch[2]) != uid):
            continue
        key = (urlmatch[1], uid)
        group = result.setdefault(key, {"slug": urlmatch[3],
                                         "published": []})
        if group["slug"] != urlmatch[3]:
            raise ValueError("multiple_source_slugs_for_published_uid")
        group["published"].append(published)
    for group in result.values():
        group["published"].sort(key=lambda x: (x["date_start"], x["id"]))
    return result


def choose_groups(groups, today, slot, limit=MAX_SCAN):
    if (type(today) is not date or type(slot) is not int
            or not 0 <= slot <= 3 or type(limit) is not int
            or not 1 <= limit <= MAX_SCAN):
        raise ValueError("invalid_source_watch_batch")
    identities = sorted(groups)
    if not identities:
        return []
    # Each sequential invocation advances through cyclic, disjoint slices,
    # including all sources if the total is not divisible by batch size.
    offset = ((today.toordinal() * 4 + slot) * limit) % len(identities)
    return [identities[(offset + i) % len(identities)]
            for i in range(min(limit, len(identities)))]


def _timings(event):
    """Use only valid exact local times in the official event timezone.

    A malformed or ambiguously offset session does not mean that a published
    occurrence was cancelled. Reject the whole timing comparison in that case.
    """
    rows, timezone = event.get("timings"), event.get("timezone")
    if not isinstance(rows, list) or not rows or len(rows) > MAX_TIMINGS:
        return None
    if timezone not in FR_TZ:
        return None
    sessions = {}
    for timing in rows:
        if (not isinstance(timing, dict)
                or type(timing.get("begin")) is not str
                or type(timing.get("end")) is not str):
            return None
        begin, end = _time(timing["begin"], timezone), _time(timing["end"], timezone)
        if begin is None or end is None or not begin < end:
            return None
        if (end.astimezone(dt_timezone.utc)
                - begin.astimezone(dt_timezone.utc)
                > timedelta(hours=24)):
            return None
        # OA timings must claim the real local UTC offset, not merely a valid
        # timestamp at some other timezone/season.
        try:
            raw_begin = datetime.fromisoformat(timing["begin"].replace("Z", "+00:00"))
            raw_end = datetime.fromisoformat(timing["end"].replace("Z", "+00:00"))
        except ValueError:
            return None
        if (begin.utcoffset() != raw_begin.utcoffset()
                or end.utcoffset() != raw_end.utcoffset()
                or begin.date() != end.date()):
            return None
        day = begin.date().isoformat()
        sessions.setdefault(day, set()).add(begin.strftime("%H:%M"))
    return sessions


def compare_official_source(source, group, today):
    """Read-only signals; source unavailable is never treated as cancellation."""
    published = group["published"]
    uid = int(published[0]["id"].split("-")[1])
    if (not isinstance(source, dict)
            or type(source.get("uid")) is not int
            or source["uid"] != uid
            or source.get("slug") != group["slug"]):
        return ["source_identity_changed"]
    status = source.get("status")
    if isinstance(status, dict):
        status = status.get("id")
    if source.get("removed") is True or status == 6:
        return ["cancelled_or_removed"]
    if source.get("state") != 2:
        return ["source_unpublished"]
    if type(status) is not int:
        return ["source_identity_changed"]
    if status == 3:
        return ["source_moved_online"]
    if status == 4:
        return ["source_postponed"]
    if status not in (1, 2, 5):
        return ["source_identity_changed"]
    timings = _timings(source)
    if timings is None:
        return ["unusable_source_timings"]
    out = {"source_sold_out"} if status == 5 else set()
    location = source.get("location")
    if not isinstance(location, dict):
        return ["source_identity_changed"]
    for old in published:
        day = old["date_start"]
        current_times = timings.get(day)
        if not current_times:
            out.add("source_session_missing")
        else:
            old_time = old.get("time") or ""
            expected = set(re.findall(r"(?<![0-9])(?:[01][0-9]|2[0-3]):[0-5][0-9](?![0-9])", old_time))
            if expected and expected != current_times:
                out.add("source_session_time_changed")
        if isinstance(location.get("name"), str) and location["name"] != old.get("venue"):
            out.add("venue_name_changed")
        if isinstance(location.get("adminLevel4"), str) and location["adminLevel4"] != old.get("city"):
            out.add("city_changed")
        try:
            point = (float(location.get("latitude")), float(location.get("longitude")))
            current = (float(old["lat"]), float(old["lng"]))
            if (all(-180 <= x <= 180 for x in point)
                    and (abs(point[0]-current[0]) > 0.0001
                         or abs(point[1]-current[1]) > 0.0001)):
                out.add("venue_coordinates_changed")
        except (ValueError, TypeError, KeyError):
            pass
    existing_days = {x["date_start"] for x in published}
    if any(day >= today.isoformat() and day not in existing_days
           for day in timings):
        out.add("source_new_future_session")
    return sorted(out)


def watch(document, today, key, slot, *, read_event=read_direct_v2, limit=MAX_SCAN):
    groups = index_published(document, today)
    chosen = choose_groups(groups, today, slot, limit)
    reasons = Counter()
    findings = []
    for slug, uid in chosen:
        group = groups[(slug, uid)]
        try:
            source = read_event(uid, key, slug)  # injected reader accepts uid,key,slug
            if isinstance(source, dict) and type(source.get("event")) is dict:
                source = source["event"]
            issues = compare_official_source(source, group, today)
        except (OSError, ValueError, TimeoutError, TypeError, KeyError,
                UnicodeError):
            issues = ["source_unavailable"]
        for code in issues:
            if code not in ALLOWED_REASONS:
                code = "source_unavailable"
            reasons[code] += 1
        if issues:
            findings.append({"event_uid": uid, "agenda_slug": slug,
                             "published_ids": [x["id"] for x in group["published"]],
                             "reason_codes": issues})
    return {
        "schema": "ptitesondes.published_oa_drift_watch.v1",
        "day": today.isoformat(), "slot": slot,
        "total_source_series": len(groups),
        "source_series_checked": len(chosen),
        "findings": findings,
        "reason_counts": dict(sorted(reasons.items())),
        "public_writes": 0, "catalogue_modified": False,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalogue", type=Path, required=True)
    ap.add_argument("--date", type=date.fromisoformat, required=True)
    ap.add_argument("--slot", type=int, choices=range(4), required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    data = args.catalogue.read_bytes()
    if len(data) > MAX_INPUT:
        raise ValueError("source_catalogue_too_large")
    from os import environ
    key = environ.get("OPENAGENDA_READ_KEY", "")
    if not key:
        raise RuntimeError("read_only_openagenda_key_missing")
    # UID-only published source URLs do not record the numeric agenda UID.
    # We therefore need to resolve the agenda slug via the first-party
    # OpenAgenda public index before invoking the authenticated events API.
    from ptitesondes_openagenda_backlog_private_dossiers import read_agenda_by_slug
    cache = {}
    def live_reader(uid, secret, slug):
        if slug not in cache:
            cache[slug] = read_agenda_by_slug(slug, secret)
        return read_direct_v2(cache[slug]["uid"], uid, secret)
    result = watch(json.loads(data), args.date, key, args.slot, read_event=live_reader)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n",
                           encoding="utf-8")
    print("Existing OA series checked:", result["source_series_checked"])
    print("Public writes: 0")
    print("Drift reason counts:", json.dumps(result["reason_counts"], sort_keys=True))


if __name__ == "__main__":
    main()
