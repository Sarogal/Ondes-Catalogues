#!/usr/bin/env python3
"""Private OpenAgenda national research -> existing intake lead contract.

This is a NON-PUBLISHING adapter. It re-reads each event at the pinned public
OpenAgenda v2 API endpoint and emits only unverified backlog-shaped leads.
Independent organizer, geography, eligibility, rights and duplicates must all
be checked by existing downstream verifiers. No scheduled workflow is changed.
"""
import argparse
from collections import Counter
from datetime import date
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

from proof import norm
from ptitesondes_openagenda_national_event_research import (
    COUNTRY_CODES, MAX_INDEX_BYTES, propose_event, select_index_candidate,
    _french_text, _private_input, _private_directory, _write_new,
)
from ptitesondes_private_national_event_campaign import _validate_segment
from ptitesondes_openagenda_v2_direct_evidence import (
    _valid_public_read_key, read_direct_v2,
)

SCHEMA = "ptitesondes.private_national_oa_intake_handoff.v1"
MAX_FETCH = 12
MAX_REPORT_BYTES = 1_500_000
BACKLOG_REASON = (
    "Découverte OpenAgenda nationale à vérifier : organisateur, catégorie, "
    "séances, accès public, lieu, géolocalisation, droits et doublons"
)
SLUG = re.compile(r"[a-z0-9][a-z0-9-]{0,100}\Z")
EVENT_PART = re.compile(r"([0-9]{1,12})_[a-z0-9-]{1,140}\Z")


def verified_report(index_doc, index_digest, report, today):
    """Bind the private segment to one exact national index and scan day."""
    if type(today) is not date or not isinstance(index_digest, str):
        raise ValueError("invalid_handoff_day_or_digest")
    meta = report.get("campaign_meta") if isinstance(report, dict) else None
    if (not isinstance(meta, dict)
            or set(meta) != {"source_sha256", "scan_day", "agenda_index",
                            "segment", "start_cursor"}
            or meta["source_sha256"] != index_digest
            or meta["scan_day"] != today.isoformat()
            or type(meta["agenda_index"]) is not int
            or type(meta["segment"]) is not int
            or not 0 <= meta["segment"] <= 10000):
        raise ValueError("untrusted_national_handoff_segment")
    agenda = select_index_candidate(index_doc, meta["agenda_index"])
    _validate_segment(report, agenda, meta)
    seen = set()
    for lead in report["event_leads"]:
        uid = lead.get("event_uid")
        if (type(uid) is not int or not 0 < uid < 10**12
                or uid in seen or lead.get("agenda_uid") != agenda["agenda_uid"]
                or lead.get("agenda_slug") != agenda["agenda_slug"]
                or not isinstance(lead.get("title"), str)
                or not 0 < len(lead["title"]) <= 300
                or not isinstance(lead.get("explicit_source_session_days"), list)
                or len(lead["explicit_source_session_days"]) > 185
                or any(not isinstance(day, str)
                       or not re.fullmatch(r"20[0-9]{2}-[0-9]{2}-[0-9]{2}", day)
                       for day in lead["explicit_source_session_days"])):
            raise ValueError("untrusted_private_event_identity")
        seen.add(uid)
    return agenda


def _canonical_url(url, agenda, uid, event_slug=None):
    """Stable OA event identity, never an untrusted organizer URL.

    OpenAgenda's canonicalUrl may point to the ORGANIZER'S own website.
    That is valid metadata, but not independently verified organizer evidence.
    Use the exact OA URL from the event's UID and slug instead; never turn a
    foreign canonical host into a trusted or published source.
    """
    if not isinstance(agenda, dict) or not SLUG.fullmatch(
            agenda.get("agenda_slug", "")):
        return None
    if isinstance(url, str) and 1 <= len(url) <= 1000:
        try:
            parsed = urlsplit(url)
            if parsed.hostname == "openagenda.com":
                if (parsed.scheme != "https" or parsed.username
                        or parsed.password or parsed.port not in (None, 443)
                        or parsed.query or parsed.fragment):
                    return None
                parts = parsed.path.strip("/").split("/")
                if len(parts) == 4 and parts[0] in ("fr", "en"):
                    parts = parts[1:]
                if (len(parts) != 3 or parts[0] != agenda["agenda_slug"]
                        or parts[1] != "events"):
                    return None
                match = EVENT_PART.fullmatch(parts[2])
                return url if match and int(match.group(1)) == uid else None
            if (parsed.hostname and
                    (parsed.hostname.endswith(".openagenda.com")
                     or "openagenda.com" in parsed.hostname)):
                # Do not launder an OpenAgenda lookalike into a source.
                return None
        except (ValueError, TypeError):
            return None
    # A valid external canonical URL is *not* a blocker at discovery time.
    # The slug comes from the direct OA API response, not from a search hit.
    if (isinstance(event_slug, str)
            and re.fullmatch(r"[a-z0-9][a-z0-9-]{0,139}", event_slug)):
        return ("https://openagenda.com/" + agenda["agenda_slug"]
                + "/events/" + str(uid) + "_" + event_slug)
    return None

def _research_item(original, api_event, agenda, today):
    uid = original["event_uid"]
    if (not isinstance(api_event, dict)
            or type(api_event.get("uid")) is not int
            or api_event["uid"] != uid):
        return [], "direct_event_identity_mismatch"
    refreshed, reason = propose_event(api_event, agenda, today)
    if refreshed is None:
        return [], "direct_event_no_longer_editorial_candidate"
    if (norm(original["title"]) != norm(refreshed["title"])
            or original.get("editorial_category_proposal")
            != refreshed["editorial_category_proposal"]):
        return [], "event_editorial_identity_changed"
    if refreshed["requires_reprogramming_verification"]:
        return [], "rescheduled_event_needs_independent_confirmation"
    if refreshed["country_code_unverified"] not in COUNTRY_CODES:
        return [], "territory_requires_independent_verification"
    city, venue = refreshed["city_unverified"], refreshed["venue_unverified"]
    if not city or not venue:
        # A missing city or place is a SEARCH task, not an invalid event.
        return [], "venue_identity_requires_research"
    if (not isinstance(refreshed["title"], str)
            or len(refreshed["title"]) > 180):
        return [], "source_title_requires_private_review"
    url = _canonical_url(api_event.get("canonicalUrl"), agenda, uid,
                         api_event.get("slug"))
    if url is None:
        return [], "canonical_public_event_url_requires_review"
    old_days = set(original["explicit_source_session_days"])
    current_days = refreshed["explicit_source_session_days"]
    if not current_days:
        return [], "source_sessions_require_research"
    # A changed day is not inferred from the previous report. It stays a
    # separate research task, while unchanged days continue independently.
    good_days = [day for day in current_days if day in old_days]
    if not good_days:
        return [], "all_source_session_days_changed"
    leads = [{
        "title": refreshed["title"], "source_url": url,
        "date_start": day, "date_end": day, "city": city, "venue": venue,
        "reason": BACKLOG_REASON, "collector": "openagenda-v2",
        "external_id": str(uid),
    } for day in good_days]
    if len(good_days) != len(current_days):
        return leads, "additional_dates_need_research"
    return leads, "private_intake_leads_only"


def handoff(index_doc, digest, report, today, public_key, *,
            offset=0, max_fetch=MAX_FETCH, fetcher=read_direct_v2):
    """Bounded read-only handoff to the legacy backlog shape.

    Never approves events; the returned rows must still pass the existing
    private intake, independent verification and historical duplicate gates.
    """
    agenda = verified_report(index_doc, digest, report, today)
    if (not _valid_public_read_key(public_key)
            or type(offset) is not int or not 0 <= offset <= len(report["event_leads"])
            or type(max_fetch) is not int or not 1 <= max_fetch <= MAX_FETCH
            or not callable(fetcher)):
        raise ValueError("invalid_private_handoff_arguments")
    selected = report["event_leads"][offset:offset + max_fetch]
    rows, holds = [], []
    counters = Counter()
    for original in selected:
        uid = original["event_uid"]
        try:
            api_event = fetcher(agenda["agenda_uid"], uid, public_key)
            found, reason = _research_item(original, api_event, agenda, today)
        except (OSError, TimeoutError, ValueError, TypeError, KeyError):
            found, reason = [], "direct_event_read_unavailable"
        rows.extend(found)
        counters[reason] += 1
        if reason != "private_intake_leads_only":
            holds.append({"event_uid": uid, "reason": reason})
    return {
        "schema": SCHEMA, "mode": "private_intake_research_only",
        "backlog_leads": rows, "research_holds": holds,
        "counts": dict(sorted(counters.items())),
        "events_examined": len(selected),
        "next_offset": offset + len(selected),
        "finished_segment": offset + len(selected) == len(report["event_leads"]),
        "publisher_connected": False, "publication_ready": False,
        "safe_to_publish": False, "public_writes": 0,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--private-agenda-index-report", required=True, type=Path)
    parser.add_argument("--private-segment-report", required=True, type=Path)
    parser.add_argument("--private-output-report", required=True, type=Path)
    parser.add_argument("--day", required=True, type=date.fromisoformat)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--max-fetch", type=int, default=MAX_FETCH)
    parser.add_argument("--execute-live", action="store_true")
    args = parser.parse_args()
    paths = (args.private_agenda_index_report.resolve(),
             args.private_segment_report.resolve(),
             args.private_output_report.resolve())
    if len(set(paths)) != 3:
        raise ValueError("handoff_private_paths_must_be_separate")
    index_raw = _private_input(args.private_agenda_index_report, MAX_INDEX_BYTES)
    doc = json.loads(index_raw)
    report = json.loads(_private_input(args.private_segment_report, MAX_REPORT_BYTES))
    verified_report(doc, sha256(index_raw).hexdigest(), report, args.day)
    _private_directory(args.private_output_report.parent)
    if args.private_output_report.exists() or args.private_output_report.is_symlink():
        raise ValueError("private_handoff_output_must_be_new")
    if not args.execute_live:
        print(json.dumps({"mode": "dry_run_no_network",
                          "events_in_segment": len(report["event_leads"]),
                          "public_writes": 0}))
        return
    result = handoff(
        doc, sha256(index_raw).hexdigest(), report, args.day,
        os.environ.get("OPENAGENDA_READ_KEY", ""),
        offset=args.offset, max_fetch=args.max_fetch,
    )
    _write_new(args.private_output_report, result)
    # Do not log event UID, title, URL, venue, agenda UID or private paths.
    print(json.dumps({
        "mode": result["mode"], "counts": result["counts"],
        "events_examined": result["events_examined"],
        "next_offset": result["next_offset"],
        "finished_segment": result["finished_segment"],
        "public_writes": 0,
    }))


if __name__ == "__main__":
    main()
