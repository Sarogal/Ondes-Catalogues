#!/usr/bin/env python3
"""Offline intake of previously UNKNOWN official-source *claims* from Concerts.

This stage is deliberately separate from approval. Registry data and page URLs
are untrusted. No networking, authority registration, imports from candidates,
changes to publisher data, or automatic approval are possible here.

The output is PRIVATE. It provides a cumulative queue to be independently
corroborated in a later admission stage, without an exhaustive venue/artist
allowlist and without treating observations as evidence of ownership.
"""
from __future__ import annotations

import argparse
import datetime as dt
import ipaddress
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit

import generic_music_event
import organizer_source_contract

SCHEMA = "grossesondes.concert.source-admission-intake.v1"
REGISTRY_SCHEMA = "grossesondes.concert.intake.v1"
HOST = re.compile(r"(?:[a-z0-9-]+\.)+[a-z]{2,24}\Z")
DISALLOWED = frozenset({"localhost", "local", "internal", "invalid", "test", "example"})
NONCONCERT = frozenset({
    "festival_overlap_review", "excluded_nonconcert", "cancellation_watch",
})


def normalized(value):
    text = unicodedata.normalize("NFKD", str(value or "")).casefold()
    return " ".join(re.findall(
        r"[a-z0-9]+", text.encode("ascii", "ignore").decode("ascii")))


def official_claim(source):
    """Discovery labels only, NEVER authenticated provenance.

    Festival archive touring nominations point at an UNKNOWN organizer
    domain. Treat them as source-admission research only; do not register
    their host, approve an event or trust old Festival metadata.
    """
    return (isinstance(source, str) and
            (source.startswith("agenda_officiel_")
             or source.startswith("artist_official_")
             or source.startswith("promoter_official_")
             or "_official_" in source
             or source == "festival_published_tour_research"))


def valid_https(value):
    """Parse a URL as DATA. Do not resolve, visit, or trust its hostname."""
    if not isinstance(value, str) or not 12 <= len(value) <= 2048:
        return None
    try:
        url = urlsplit(value)
        host = url.hostname
        if (url.scheme != "https" or not host
                or url.username is not None or url.password is not None
                or url.port is not None or url.fragment
                or not HOST.fullmatch(host)
                or any(part in ("", ".", "..") for part in host.split("."))):
            return None
        if host.rsplit(".", 1)[-1] in DISALLOWED:
            return None
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            return None
        return host
    except (ValueError, TypeError):
        return None


def build(registry, catalogue, today, *, organizer_sources=None,
          reviewed_venues=None):
    if (not isinstance(registry, dict)
            or registry.get("schema") != REGISTRY_SCHEMA
            or not isinstance(registry.get("items"), dict)):
        raise ValueError("Invalid PRIVATE concert registry")
    if (not isinstance(catalogue, dict)
            or catalogue.get("schemaVersion") != 1
            or not isinstance(catalogue.get("events"), list)):
        raise ValueError("Invalid public concerts catalogue")
    if not isinstance(today, dt.date) or isinstance(today, dt.datetime):
        raise ValueError("Invalid reference date")
    if organizer_sources is None:
        organizer_sources = organizer_source_contract.read_sources()
    if reviewed_venues is None:
        reviewed_venues = generic_music_event.SPECS
    if not isinstance(organizer_sources, list) or not hasattr(reviewed_venues, "values"):
        raise ValueError("Invalid reviewed authority references")

    # Committed, reviewed authorities are display annotations ONLY.
    reviewed_hosts = {
        s["host"] for s in organizer_sources
        if isinstance(s, dict) and s.get("enabled") is True
    } | {
        s["host"] for s in reviewed_venues.values()
        if isinstance(s, dict) or hasattr(s, "keys")
    }
    published_pairs = {
        (e.get("officialUrl"), e.get("date"))
        for e in catalogue["events"] if isinstance(e, dict)
    }
    queues = {}
    identity_hosts = defaultdict(set)
    skipped = Counter()

    for record in registry["items"].values():
        if not isinstance(record, dict) or not isinstance(record.get("candidate"), dict):
            skipped["invalid_record"] += 1
            continue
        candidate = record["candidate"]
        if record.get("status", "pending_review") != "pending_review":
            skipped["already_decided"] += 1
            continue
        date = candidate.get("date")
        try:
            day = dt.date.fromisoformat(date)
        except (ValueError, TypeError):
            skipped["undated"] += 1
            continue
        if day < today:
            skipped["expired"] += 1
            continue
        if (candidate.get("reviewBucket") in NONCONCERT
                or candidate.get("possibleExistingConcert") is True):
            skipped["excluded_or_duplicate"] += 1
            continue
        if (candidate.get("sourceUrl"), date) in published_pairs:
            skipped["already_published_exact"] += 1
            continue
        if not official_claim(candidate.get("source")):
            skipped["not_first_party_claim"] += 1
            continue
        event_url = candidate.get("eventDetailUrl") or candidate.get("sourceUrl")
        page_url = candidate.get("sourcePage") or candidate.get("sourceUrl")
        host = valid_https(page_url)
        event_host = valid_https(event_url)
        if not host or not event_host:
            skipped["invalid_https_origin_or_event"] += 1
            continue
        key = (date, normalized(candidate.get("name")),
               normalized(candidate.get("venue")), normalized(candidate.get("city")))
        # This key is only a collision HINT: it must never dedupe a real show.
        if not all(key):
            skipped["incomplete_event_identity"] += 1
            continue
        if host not in queues:
            queues[host] = {
                "host": host, "alreadyReviewedAuthority": host in reviewed_hosts,
                "eventLeads": 0, "stableOnDistinctDays": 0,
                "sameHostEventLeads": 0, "offsiteEventLinks": 0,
                "individualDetailClaimed": 0, "genreClaimed": 0,
                "venues": set(), "cities": set(), "sourceLabels": set(),
                "examples": [],
            }
        row = queues[host]
        row["eventLeads"] += 1
        row["stableOnDistinctDays"] += (
            type(record.get("stableObservations")) is int
            and record["stableObservations"] >= 2)
        row["sameHostEventLeads"] += event_host == host
        row["offsiteEventLinks"] += event_host != host
        row["individualDetailClaimed"] += candidate.get("officialDetailFound") is True
        row["genreClaimed"] += candidate.get("reviewBucket") == "genre_tag_review"
        row["venues"].add(candidate.get("venue"))
        row["cities"].add(candidate.get("city"))
        row["sourceLabels"].add(candidate["source"])
        identity_hosts[key].add(host)
        if len(row["examples"]) < 3:
            row["examples"].append({
                "candidateId": candidate.get("candidateId"),
                "date": date, "venue": candidate.get("venue"),
                "city": candidate.get("city"), "eventUrl": event_url,
                "sourcePage": page_url,
            })

    out = []
    for row in queues.values():
        reviewed = row["alreadyReviewedAuthority"]
        # The host may be a ticketing page or artist's tour listing, not the
        # owner of a venue. These are requests for independent research only.
        state = ("already_reviewed" if reviewed
                 else "needs_official_identity_and_independent_corroboration")
        out.append({
            "host": row["host"], "reviewState": state,
            "alreadyReviewedAuthority": reviewed,
            "eventLeads": row["eventLeads"],
            "stableOnDistinctDays": row["stableOnDistinctDays"],
            "sameHostEventLeads": row["sameHostEventLeads"],
            "offsiteEventLinks": row["offsiteEventLinks"],
            "individualDetailClaimed": row["individualDetailClaimed"],
            "genreClaimed": row["genreClaimed"],
            "venues": sorted(x for x in row["venues"] if isinstance(x, str)),
            "cities": sorted(x for x in row["cities"] if isinstance(x, str)),
            "sourceLabels": sorted(row["sourceLabels"]),
            "examples": row["examples"],
            "networkChecked": False,
            "independentCorroborationVerified": False,
            "automaticTrustGranted": False,
            "publicationAllowed": False,
        })
    out.sort(key=lambda x: (
        x["alreadyReviewedAuthority"],
        -x["stableOnDistinctDays"], -x["eventLeads"], x["host"]))
    return {
        "schema": SCHEMA, "asOf": today.isoformat(),
        "privateRegistryRows": len(registry["items"]),
        "candidateSourceHosts": len(out),
        "previouslyUnreviewedHosts": sum(
            not x["alreadyReviewedAuthority"] for x in out),
        "stableUnreviewedSourceHosts": sum(
            not x["alreadyReviewedAuthority"]
            and x["stableOnDistinctDays"] > 0 for x in out),
        "crossHostIdentityHints": sum(len(hosts) >= 2
                                      for hosts in identity_hosts.values()),
        "skipped": dict(sorted(skipped.items())),
        "networkChecked": False, "automaticTrustGranted": False,
        "publicationAllowed": False, "reviewQueue": out,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--catalogue", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = build(
        json.loads(args.registry.read_text(encoding="utf-8")),
        json.loads(args.catalogue.read_text(encoding="utf-8")),
        dt.datetime.now(ZoneInfo("Europe/Paris")).date())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(
        result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # No private hosts, URLs, band names, or candidate IDs in public CI logs.
    print("Source admission intake written privately; automatic trust: false.")


if __name__ == "__main__":
    main()
