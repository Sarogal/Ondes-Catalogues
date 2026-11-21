#!/usr/bin/env python3
"""Private-only discovery of OpenAgenda sources beyond configured agenda UIDs.

An ODS UID-bound record supplies a starting point, and a second direct
OpenAgenda v2 GET checks agenda UID+slug and exact event UID/place.
This is *not* source-owner verification or authorization to publish.
No fixed list of cities, venues, categories or agenda names is used.
"""
import argparse
from collections import Counter
from datetime import date, timedelta
import json
import math
import os
from pathlib import Path
import re

from proof import norm
from ptitesondes_candidate_promotion import api_record
from ptitesondes_ods_oa_source_binding import (
    ods_source_parts, ods_immutable_source_match, ods_origin_agenda_uid,
    independently_confirm_ods_agenda,
)
from ptitesondes_openagenda_v2_direct_evidence import (
    read_direct_agenda_v2, read_direct_v2, _valid_public_read_key, _source_parts,
)
from ptitesondes_openagenda_national_event_research import COUNTRY_CODES
from ptitesondes_openagenda_slug_discovery import (
    lookup_agenda_by_slug, SCHEMA as SLUG_LOOKUP_SCHEMA,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "ptitesondes.private_dynamic_oa_sources.v1"
MAX_BACKLOG = 4000
MAX_PER_BATCH = 40
MAX_PRIVATE_BYTES = 1_000_000
VALID_UID = re.compile(r"[0-9]{1,12}\Z")


def candidate_batches(backlog, configured_agendas, today, batch_index=0,
                      *, include_openagenda_v2=False):
    """Deterministic UID-only rotation; unknown venues are not discarded."""
    if (type(today) is not date or type(batch_index) is not int
            or batch_index < 0 or not isinstance(backlog, list)
            or len(backlog) > MAX_BACKLOG
            or not isinstance(configured_agendas, (tuple, list))
            or type(include_openagenda_v2) is not bool
            or any(type(x) is not int or x <= 0 for x in configured_agendas)):
        raise ValueError("invalid_private_source_batch")
    unique, conflicts = {}, set()
    for lead in backlog:
        if not isinstance(lead, dict) or lead.get("collector") not in (
                ("opendatasoft-index", "openagenda-v2")
                if include_openagenda_v2 else ("opendatasoft-index",)):
            continue
        uid = lead.get("external_id")
        if not isinstance(uid, str) or not VALID_UID.fullmatch(uid):
            continue
        # Do not require an ODS mirror or known municipality / venue
        # merely to research an independently discovered OpenAgenda source.
        if lead["collector"] == "openagenda-v2":
            parts = _source_parts(lead.get("source_url"))
            slug = parts[0] if parts and parts[1] == uid else None
        else:
            slug = ods_source_parts(lead.get("source_url"))
        if slug is None:
            continue
        if (lead["collector"] == "opendatasoft-index"
                and (not norm(lead.get("city")) or not norm(lead.get("venue")))):
            continue
        try:
            d = date.fromisoformat(lead.get("date_start"))
        except (ValueError, TypeError):
            continue
        if not today <= d <= today + timedelta(days=184):
            continue
        signature = (lead["source_url"], norm(lead.get("city")),
                     norm(lead.get("venue")))
        if uid in unique and unique[uid][0] != signature:
            conflicts.add(uid)
        unique[uid] = (signature, lead)
    ordered = [unique[uid][1] for uid in sorted(unique)
               if uid not in conflicts]
    count = math.ceil(len(ordered) / MAX_PER_BATCH)
    if not ordered:
        if batch_index != 0:
            raise ValueError("private_agenda_batch_out_of_range")
        return [], 0, len(conflicts)
    if batch_index >= count:
        raise ValueError("private_agenda_batch_out_of_range")
    offset = batch_index * MAX_PER_BATCH
    return ordered[offset:offset + MAX_PER_BATCH], count, len(conflicts)


def _direct_location_agrees(lead, record, *, allow_missing_lead_place=False):
    """Same ODS UID must have a matching public OA event and physical place."""
    if not isinstance(record, dict):
        return False
    if str(record.get("uid")) != lead["external_id"]:
        return False
    if (record.get("state") != 2 or record.get("status") != 1
            or record.get("removed") is True
            or record.get("attendanceMode") == 2):
        return False
    place = record.get("location")
    if not isinstance(place, dict):
        return False
    # Legal French jurisdiction, not a hard-coded list of admissible venues.
    # Reuse the national research ISO territory codes, including the Pacific.
    if (place.get("countryCode") not in COUNTRY_CODES
            or not norm(place.get("name"))
            or not norm(place.get("adminLevel4"))):
        return False
    for key, field in (("venue", "name"), ("city", "adminLevel4")):
        claimed = norm(lead.get(key))
        if claimed and claimed != norm(place.get(field)):
            return False
        if not claimed and not allow_missing_lead_place:
            return False
    lat, lon = place.get("latitude"), place.get("longitude")
    return (type(lat) in (float, int) and type(lon) in (float, int)
            and math.isfinite(lat) and math.isfinite(lon)
            and -90 <= lat <= 90 and -180 <= lon <= 180)


def discover_unconfigured_sources(
        leads, configured_agendas, public_read_key,
        ods_get=api_record, agenda_get=read_direct_agenda_v2,
        event_get=read_direct_v2):
    """Return PRIVATE candidate seeds, not admitted events or agendas."""
    if (not isinstance(leads, list) or len(leads) > MAX_PER_BATCH
            or not isinstance(configured_agendas, (tuple, list))
            or not all(callable(x) for x in (ods_get, agenda_get, event_get))
            or not _valid_public_read_key(public_read_key)):
        raise ValueError("invalid_private_dynamic_agenda_scan")
    counters = Counter()
    seen_agendas = {}
    configured = set(configured_agendas)
    for lead in leads:
        counters["candidate_event_uids_examined"] += 1
        group = {"city": lead["city"], "venue": lead["venue"]}
        uid, source_url = lead["external_id"], lead["source_url"]
        slug = ods_source_parts(source_url)
        try:
            row = ods_get(uid)
            if not ods_immutable_source_match(group, uid, source_url, row):
                counters["ods_uid_or_location_conflict"] += 1
                continue
            agenda_uid = ods_origin_agenda_uid(row)
            if agenda_uid is None:
                counters["no_immutable_origin_agenda_uid"] += 1
                continue
            if agenda_uid in configured:
                counters["already_configured_agenda"] += 1
                continue
            verified = independently_confirm_ods_agenda(
                row, slug, agenda_get, public_read_key)
            if verified != agenda_uid:
                counters["oa_agenda_uid_or_slug_disagrees"] += 1
                continue
            # Consult a PUBLIC event of the newly discovered agenda, not just
            # its metadata, without ever adding it to an admission allowlist.
            event = event_get(agenda_uid, uid, public_read_key)
            if not _direct_location_agrees(lead, event):
                counters["oa_direct_event_location_mismatch"] += 1
                continue
        except (OSError, ValueError, TypeError, KeyError, TimeoutError):
            counters["source_api_unavailable_or_invalid"] += 1
            continue
        existing = seen_agendas.get(agenda_uid)
        if existing is not None and existing["agenda_slug"] != slug:
            counters["same_uid_conflicting_agenda_slugs"] += 1
            seen_agendas.pop(agenda_uid, None)
            continue
        if existing is None:
            seen_agendas[agenda_uid] = {
                "agenda_uid": agenda_uid, "agenda_slug": slug,
                "sample_event_uid": uid,
                "research_status": "source_identity_only_private_review",
                "owner_independently_verified": False,
                "rights_reviewed": False,
                "publisher_enabled": False,
            }
        counters["direct_unconfigured_agenda_event_concordant"] += 1
    return {
        "schema": SCHEMA,
        "mode": "private_readonly_oa_source_discovery_no_publication",
        "counts": dict(sorted(counters.items())),
        "new_agenda_candidates": list(seen_agendas.values()),
        "publication_ready": False,
        "public_writes": 0,
    }


def _private_file(path):
    if (path.is_symlink() or not path.is_file()
            or path.resolve().is_relative_to(ROOT)
            or not 0 < path.stat().st_size <= MAX_PRIVATE_BYTES):
        raise ValueError("private_source_input_invalid")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backlog", required=True, type=Path)
    parser.add_argument("--private-source-config", required=True, type=Path)
    parser.add_argument("--output-private-report", required=True, type=Path)
    parser.add_argument("--day", required=True, type=date.fromisoformat)
    parser.add_argument("--batch-index", type=int, default=0)
    parser.add_argument("--live-probe", action="store_true")
    args = parser.parse_args()
    for path in (args.backlog, args.private_source_config):
        _private_file(path)
    output = args.output_private_report
    if (output.resolve().is_relative_to(ROOT)
            or not output.parent.is_dir() or output.parent.is_symlink()
            or output.parent.stat().st_mode & 0o077
            or output.exists() or output.is_symlink()):
        raise ValueError("private_source_report_path_invalid")
    backlog = json.loads(args.backlog.read_text(encoding="utf-8"))
    config = json.loads(args.private_source_config.read_text(encoding="utf-8"))
    if (not isinstance(config, dict)
            or config.get("schema") != "ptitesondes.sources.v1"
            or not isinstance(config.get("openagenda_agendas"), list)):
        raise ValueError("private_source_config_invalid")
    candidates, batches, conflicts = candidate_batches(
        backlog, config["openagenda_agendas"], args.day, args.batch_index)
    if args.live_probe:
        key = os.environ.get("OPENAGENDA_READ_KEY", "")
        result = discover_unconfigured_sources(
            candidates, config["openagenda_agendas"], key)
    else:
        result = {"schema": SCHEMA, "mode": "dry_run_no_network",
                  "counts": {}, "new_agenda_candidates": [],
                  "publication_ready": False, "public_writes": 0}
    result["batch_index"] = args.batch_index
    result["batch_count"] = batches
    result["batch_size"] = len(candidates)
    result["conflicting_source_uids"] = conflicts
    old_umask = os.umask(0o077)
    try:
        with output.open("x", encoding="utf-8") as out:
            json.dump(result, out, ensure_ascii=False, indent=2)
            out.write("\n")
    finally:
        os.umask(old_umask)
    # Never log agenda IDs, URLs, private venue names or API error details.
    print(json.dumps({
        "mode": result["mode"], "batch_index": args.batch_index,
        "batch_count": batches, "batch_size": len(candidates),
        "new_agenda_candidates": len(result["new_agenda_candidates"]),
        "public_writes": 0,
    }))


if __name__ == "__main__":
    main()
