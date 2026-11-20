#!/usr/bin/env python3
"""PRIVATE-ONLY coverage of unknown venue cities by official DILA mairie sites.

No events, GPS or municipal sites are approved for publication. The only
network request is to the fixed DILA government directory and includes a
municipality name only, never a private event UID, venue, or date.
"""
import argparse
from collections import defaultdict
from datetime import date
import json
import os
from pathlib import Path
import tempfile

from proof import norm
from ptitesondes_dila_municipal_domains import fetch_dila, municipal_site_hosts
from ptitesondes_generic_venue_osm_preflight import groups_for_review

SCHEMA = "ptitesondes.municipal_domain_coverage_private.v1"
MAX_CITIES_PER_RUN = 60
MAX_PRIVATE_BYTES = 1_000_000


def coverage(backlog, today, *, live=False, max_cities=12, dila_fetch=fetch_dila):
    if (type(today) is not date or type(live) is not bool
            or type(max_cities) is not int
            or not 1 <= max_cities <= MAX_CITIES_PER_RUN
            or not callable(dila_fetch)):
        raise ValueError("invalid_private_coverage_configuration")
    groups = groups_for_review(backlog, today)
    locations = defaultdict(lambda: {"venue_keys": set(), "lead_count": 0,
                                     "city": ""})
    for group in groups:
        key = norm(group["city"])
        row = locations[key]
        row["city"] = group["city"]
        row["venue_keys"].add(tuple(group["key"]))
        row["lead_count"] += group["lead_count"]
    ranked = sorted(locations.values(),
                    key=lambda r: (-r["lead_count"], norm(r["city"])))
    chosen = []
    if ranked:
        # Stable daily rotation. Larger max_cities is supported for deliberate
        # one-off private runs; never allows unbounded government API traffic.
        start = (today.toordinal() * max_cities) % len(ranked)
        chosen = [ranked[(start + offset) % len(ranked)]
                  for offset in range(min(max_cities, len(ranked)))]
    records = []
    for item in chosen:
        state = "not_scanned_preview"
        if live:
            try:
                response = dila_fetch(item["city"])
                sites = municipal_site_hosts(item["city"], response)
                state = ("official_municipal_homepage_identified"
                         if sites else "no_unambiguous_municipal_homepage")
            except (ValueError, TypeError, KeyError, OSError,
                    UnicodeError, TimeoutError):
                state = "directory_api_unavailable"
        records.append({
            "city_private": item["city"],
            "venue_groups_private": len(item["venue_keys"]),
            "lead_count_private": item["lead_count"],
            "state": state,
            "official_venue_verified": False,
            "gps_verified": False,
            "publication_ready": False,
        })
    available = [r for r in records
                 if r["state"] == "official_municipal_homepage_identified"]
    return {
        "schema": SCHEMA, "day": today.isoformat(),
        "mode": "private_dila_read_only" if live else "private_no_network_preview",
        "backlog_leads_total": len(backlog),
        "unknown_venue_leads": sum(g["lead_count"] for g in groups),
        "unknown_unique_venue_groups": len(groups),
        "all_unknown_municipalities": len(ranked),
        "municipalities_selected": len(chosen),
        "municipalities_queried": len(chosen) if live else 0,
        "municipalities_with_official_homepage": len(available),
        "venues_in_municipalities_with_homepage": sum(
            r["venue_groups_private"] for r in available),
        "leads_in_municipalities_with_homepage": sum(
            r["lead_count_private"] for r in available),
        "directory_unavailable": sum(
            r["state"] == "directory_api_unavailable" for r in records),
        "private_records": records,
        "venue_evidence_approved": 0, "event_sessions_approved": 0,
        "publication_ready": False, "public_writes": 0,
    }


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--private-backlog", type=Path, required=True)
    cli.add_argument("--private-report", type=Path, required=True)
    cli.add_argument("--day", type=date.fromisoformat, default=date.today())
    cli.add_argument("--max-cities", type=int, default=12)
    cli.add_argument("--live-dila", action="store_true")
    args = cli.parse_args()
    public_repo = Path(__file__).resolve().parents[1]
    src, dest = args.private_backlog.resolve(), args.private_report.resolve()
    if (src.is_relative_to(public_repo) or dest.is_relative_to(public_repo)
            or args.private_backlog.is_symlink()
            or args.private_report.is_symlink()
            or not args.private_backlog.is_file()
            or args.private_backlog.stat().st_size > MAX_PRIVATE_BYTES
            or not args.private_report.parent.is_dir()):
        raise ValueError("private_paths_outside_public_repo_required")
    backlog = json.loads(args.private_backlog.read_text(encoding="utf-8"))
    report = coverage(backlog, args.day, live=args.live_dila,
                      max_cities=args.max_cities)
    raw = (json.dumps(report, ensure_ascii=False, allow_nan=False,
                      indent=2) + "\n").encode("utf-8")
    if len(raw) > MAX_PRIVATE_BYTES:
        raise ValueError("oversized_private_coverage_report")
    fd, temp = tempfile.mkstemp(prefix=".ptitesondes-dila-",
                                 dir=args.private_report.parent)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(raw)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, dest)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    # Names, candidate URL, UID, exact dates, coordinates stay PRIVATE.
    safe = {key: value for key, value in report.items()
            if key not in ("private_records",)}
    print(json.dumps(safe, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
