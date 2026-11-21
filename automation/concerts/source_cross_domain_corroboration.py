#!/usr/bin/env python3
"""Cross-domain concert leads from the PRIVATE registry, without trust transfer.

We can observe the same date/lead-artist/city on different websites even
when the first-party venue page lists additional support bands or prefixes
its room name with a French article. This is a REVIEW PRIORITY, not an
automatically accepted event or proof of domain ownership. No network,
artist, venue, or organizer allowlist is needed.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from collections import defaultdict, Counter
from pathlib import Path
from zoneinfo import ZoneInfo

import source_admission_intake as intake

SCHEMA = "grossesondes.concert.cross-source-corroboration.v1"
BANNED_BUCKETS = frozenset({
    "festival_overlap_review", "excluded_nonconcert", "cancellation_watch",
})


def clean_venue(name):
    value = intake.normalized(name)
    chunks = value.split()
    if chunks and chunks[0] in {"le", "la", "les", "l"}:
        chunks = chunks[1:]
    return " ".join(chunks)


def domain(host):
    """Conservative grouping: two subdomains of one apex are not independent."""
    labels = host.split(".")
    return ".".join(labels[-2:]) if len(labels) >= 2 else host


def build(registry, catalogue, today):
    if (not isinstance(registry, dict)
            or registry.get("schema") != intake.REGISTRY_SCHEMA
            or not isinstance(registry.get("items"), dict)):
        raise ValueError("Invalid private registry")
    if (not isinstance(catalogue, dict)
            or catalogue.get("schemaVersion") != 1
            or not isinstance(catalogue.get("events"), list)):
        raise ValueError("Invalid public catalogue")
    if not isinstance(today, dt.date) or isinstance(today, dt.datetime):
        raise ValueError("Invalid day")
    published = {
        (r.get("date"), r.get("officialUrl"))
        for r in catalogue["events"] if isinstance(r, dict)
    }

    groups, reasons = defaultdict(list), Counter()
    for record in registry["items"].values():
        if not isinstance(record, dict):
            reasons["invalid_record"] += 1
            continue
        c = record.get("candidate")
        if (not isinstance(c, dict)
                or record.get("status", "pending_review") != "pending_review"
                or c.get("publicationAllowed") is not False
                or c.get("reviewRequired") is not True):
            reasons["inactive_or_unsafe"] += 1
            continue
        if c.get("reviewBucket") in BANNED_BUCKETS or c.get("possibleExistingConcert") is True:
            reasons["excluded_or_duplicate"] += 1
            continue
        try:
            day = dt.date.fromisoformat(c.get("date"))
        except (ValueError, TypeError):
            reasons["undated"] += 1
            continue
        if day < today:
            reasons["expired"] += 1
            continue
        if (c.get("date"), c.get("sourceUrl")) in published:
            reasons["already_published"] += 1
            continue
        host = intake.valid_https(c.get("sourceUrl"))
        if host is None:
            reasons["invalid_host"] += 1
            continue
        key = (
            day.isoformat(), intake.normalized(c.get("leadArtist")),
            intake.normalized(c.get("city")),
        )
        venue = clean_venue(c.get("venue"))
        if not all(key) or not venue:
            reasons["missing_identity"] += 1
            continue
        groups[key].append({
            "candidateId": c.get("candidateId"),
            "host": host, "independentDomainHint": domain(host),
            "sourceLabel": c.get("source"),
            "date": c.get("date"), "leadArtist": c.get("leadArtist"),
            "city": c.get("city"), "venue": c.get("venue"),
            "normalizedVenue": venue,
            "stableOnDistinctDays": (
                type(record.get("stableObservations")) is int
                and record["stableObservations"] >= 2),
            "individualEventDetailClaimed": (
                c.get("officialDetailFound") is True
                or isinstance(c.get("eventDetailUrl"), str)),
        })

    matches = []
    for (date, artist, city), entries in groups.items():
        domains = {v["independentDomainHint"] for v in entries}
        if len(domains) < 2:
            continue
        rooms = {e["normalizedVenue"] for e in entries}
        # Incompatible places never become mutually corroborating evidence.
        if len(rooms) > 1:
            status = "conflicting_venue_identity"
        elif len({
                r["independentDomainHint"] for r in entries
                if r["stableOnDistinctDays"]
            }) >= 2:
            status = "cross_domain_stable_observation_needs_live_proof"
        else:
            status = "cross_domain_observation_needs_second_day"
        first_by_host = {}
        for row in entries:
            host = row["host"]
            if (host not in first_by_host
                    or row["stableOnDistinctDays"]
                    and not first_by_host[host]["stableOnDistinctDays"]):
                first_by_host[host] = row
        matches.append({
            "date": date, "leadArtist": artist, "city": city,
            "normalizedVenue": (next(iter(rooms)) if len(rooms) == 1 else None),
            "reviewState": status,
            "distinctDomainHints": len(domains),
            "sources": sorted(first_by_host.values(), key=lambda x: x["host"]),
            "independentOwnershipVerified": False,
            "freshOfficialDetailsVerified": False,
            "publicationAllowed": False, "automaticTrustGranted": False,
        })
    matches.sort(key=lambda x: (x["date"], x["leadArtist"], x["city"]))
    counts = Counter(x["reviewState"] for x in matches)
    return {
        "schema": SCHEMA, "asOf": today.isoformat(),
        "futureCrossDomainLeadGroups": len(matches),
        "stableSameVenueCrossDomainGroups": counts[
            "cross_domain_stable_observation_needs_live_proof"],
        "conflictingVenueGroups": counts["conflicting_venue_identity"],
        "awaitingSecondDayGroups": counts[
            "cross_domain_observation_needs_second_day"],
        "skipped": dict(sorted(reasons.items())),
        "independentOwnershipVerified": False,
        "automaticTrustGranted": False, "publicationAllowed": False,
        "groups": matches,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--catalogue", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data = build(
        json.loads(args.registry.read_text(encoding="utf-8")),
        json.loads(args.catalogue.read_text(encoding="utf-8")),
        dt.datetime.now(ZoneInfo("Europe/Paris")).date())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(
        data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Private cross-domain event leads reviewed; no event approved.")


if __name__ == "__main__":
    main()
