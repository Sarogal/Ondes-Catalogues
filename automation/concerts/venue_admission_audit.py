#!/usr/bin/env python3
"""Offline venue-admission audit; discovers possible venues WITHOUT granting trust.

The independent reviewed manifest remains the sole first-party authority. The
public sources catalogue is discovery data only, even when marked "verified".
No network access, approvals, publisher writes or private registry reads.
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

import generic_music_event

ROOT = Path(__file__).resolve().parents[2]


def normalized(value):
    if not isinstance(value, str):
        return ""
    value = unicodedata.normalize("NFKD", value).casefold()
    return " ".join(re.findall(r"[a-z0-9]+", value.encode("ascii", "ignore").decode()))


def safe_host(url):
    if not isinstance(url, str) or len(url) > 2048:
        return None
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        if (parsed.scheme != "https" or not host or parsed.username
                or parsed.password or parsed.port is not None
                or not re.fullmatch(r"(?:[a-z0-9-]+\.)+[a-z]{2,24}", host)):
            return None
        return host
    except ValueError:
        return None


def evaluate(sources, catalogue, specs=None):
    """Return non-authoritative review queue; no additions to SPECS possible."""
    if specs is None:
        specs = generic_music_event.SPECS
    if (not isinstance(sources, dict)
            or sources.get("schema") != "grossesondes.concert.sourcelist.v1"
            or not isinstance(sources.get("venues"), list)):
        raise ValueError("Source list invalid")
    if (not isinstance(catalogue, dict) or catalogue.get("schemaVersion") != 1
            or not isinstance(catalogue.get("venues"), list)
            or not isinstance(catalogue.get("events"), list)):
        raise ValueError("Catalogue invalid")
    if not hasattr(specs, "items"):
        raise ValueError("Reviewed venue specs invalid")

    known = {}
    for venue in catalogue["venues"]:
        if not isinstance(venue, dict):
            continue
        key = (normalized(venue.get("name")),
               normalized(venue.get("city")), str(venue.get("department")))
        if all(key):
            known.setdefault(key, []).append(venue)
    counts = Counter(
        row.get("venueId") for row in catalogue["events"]
        if isinstance(row, dict) and isinstance(row.get("venueId"), str))
    queue, unmatched, ambiguous = [], 0, 0
    for source in sources["venues"]:
        if not isinstance(source, dict):
            unmatched += 1
            continue
        key = (normalized(source.get("name")),
               normalized(source.get("city")),
               str(source.get("department")))
        matched = known.get(key, [])
        if len(matched) != 1:
            if len(matched) > 1:
                ambiguous += 1
            else:
                unmatched += 1
            continue
        venue = matched[0]
        host = safe_host(source.get("url"))
        address = venue.get("address")
        geo = venue.get("geoSource")
        geo_proof = (
            isinstance(address, str) and len(address.strip()) >= 5
            and "verifier" not in normalized(address)
            and safe_host(geo) is not None)
        spec = specs.get(venue.get("id"))
        trusted = bool(
            spec and normalized(spec.get("name")) == key[0]
            and normalized(spec.get("city")) == key[1]
            and str(spec.get("department")) == key[2]
            and host == spec.get("host")
            and spec.get("base") == "https://" + host + "/")
        if trusted:
            state = "already_reviewed"
        elif not host:
            state = "source_domain_invalid"
        elif not geo_proof:
            state = "needs_geographic_corroboration"
        else:
            state = "needs_independent_official_event_proof"
        queue.append({
            "venueId": venue.get("id"),
            "venue": venue.get("name"), "city": venue.get("city"),
            "department": venue.get("department"),
            "officialHostCandidate": host,
            "publishedEventsForVenue": counts[venue.get("id")],
            "reviewState": state, "alreadyInReviewedContract": trusted,
            "automaticTrustGrantedByAudit": False,
        })
    queue.sort(key=lambda x:(
        x["reviewState"] == "already_reviewed",
        x["publishedEventsForVenue"],
        str(x["department"]), str(x["venue"])))
    return {
        "schema": "grossesondes.concert.venue-admission-audit.v1",
        "sourceCount": len(sources["venues"]),
        "exactVenueMatches": len(queue),
        "unmatchedSources": unmatched, "ambiguousMatches": ambiguous,
        "reviewedVenueMatches": sum(x["alreadyInReviewedContract"] for x in queue),
        "reviewStateCounts": dict(sorted(Counter(x["reviewState"] for x in queue).items())),
        "publicationAllowed": False, "automaticTrustGranted": False,
        "reviewQueue": queue,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", type=Path,
                        default=ROOT / "automation/concerts/sources.json")
    parser.add_argument("--catalogue", type=Path,
                        default=ROOT / "docs/grossesondes/concerts-reference.json")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = evaluate(
        json.loads(args.sources.read_text(encoding="utf-8")),
        json.loads(args.catalogue.read_text(encoding="utf-8")))
    serialized = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(serialized, encoding="utf-8")
    else:
        print(serialized, end="")


if __name__ == "__main__":
    main()
