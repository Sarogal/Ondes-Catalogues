#!/usr/bin/env python3
"""Private-only measurable status of the Concerts intake/review pipeline.

Never exports candidates, official evidence or URLs into public Actions logs.
The cloud sync separately measures *actual* publications: this intake report
must never misrepresent an approval as a published concert.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def describe_venue(item):
    if item.get("error"):
        error = str(item["error"]).lower()
        status = ("robots_denied_or_unavailable" if "robots.txt" in error
                  else "source_error")
    else:
        status = "fetched"
    details = item.get("adapterDiagnostic") or {}
    return {"name": item.get("venue", "unknown"), "status": status,
            "detailsRead": details.get("detailPagesRead", 0),
            "detailsErrors": details.get("detailErrors", 0)}


def build(discovery, tours, registry, official, watch, archive_summaries, when):
    if discovery.get("schema") != "grossesondes.concert.discovery.v1":
        raise ValueError("Invalid venue discovery")
    if tours.get("schema") != "grossesondes.concert.discovery.v1":
        raise ValueError("Invalid artist tour discovery")
    if registry.get("schema") != "grossesondes.concert.intake.v1":
        raise ValueError("Invalid private registry")
    if not isinstance(official.get("results"), list):
        raise ValueError("Official review missing")
    if not isinstance(watch.get("needsReview"), list):
        raise ValueError("Published watch missing")
    sources = [describe_venue(x) for x in discovery.get("venueChecks", [])]
    partner = [dict(x) for x in discovery.get("partnerChecks", [])]
    tour_checks = tours.get("sourceChecks", [])
    items = list(registry["items"].values())
    return {
        "schema": "grossesondes.concert.intake.metrics.v1",
        "generatedAt": when,
        "publicCatalogueEventsObservedAtDiscovery": discovery.get(
            "catalogue", {}).get("events"),
        "venueSources": sources,
        "venueSourcesFetched": sum(x["status"] == "fetched" for x in sources),
        "venueSourcesRobotsDeniedOrUnavailable": sum(
            x["status"] == "robots_denied_or_unavailable" for x in sources),
        "venueSourcesOtherErrors": sum(
            x["status"] == "source_error" for x in sources),
        "partnerChecks": partner,
        "tourSources": [
            {"artistId": x.get("artistId"), "status": x.get("status", "unknown"),
             "candidateCount": x.get("candidateCount", 0),
             "detailPagesRead": x.get("detailPagesRead", 0),
             "heldDetailErrors": x.get("heldDetailErrors", 0)}
            for x in tour_checks],
        "venueDiscoveriesThisRun": len(discovery["candidates"]),
        "tourDiscoveriesThisRun": len(tours["candidates"]),
        "newPrivateCandidates": sum(x.get("added", 0)
                                    for x in archive_summaries),
        "rediscoveredPrivateCandidates": sum(x.get("seenAgain", 0)
                                              for x in archive_summaries),
        "privateCandidatesTotal": len(items),
        "privatePending": sum(x.get("status") == "pending_review" for x in items),
        "privateEligibleStable": sum(
            x.get("status") == "pending_review"
            and x.get("stableObservations", 0) >= 2 for x in items),
        "privateDecided": sum(
            x.get("status") in ("approved", "rejected", "superseded") for x in items),
        "officialEvaluated": official.get("evaluated", 0),
        "officialHeld": len(official.get("held", [])),
        "approvalsProposed": len(official.get("newApprovals", [])),
        "expiredSkipped": official.get("expiredSkipped", 0),
        "publishedWatchChecked": watch.get("checked", 0),
        "publishedWatchAnomalies": len(watch["needsReview"]),
        # To avoid treating proposed approvals as actually published:
        "actuallyPublishedByThisIntake": 0,
        "actualPublicationMeasuredBy": "grossesondes-concerts-cloud-sync",
    }


def main():
    parser = argparse.ArgumentParser()
    for flag in ("discovery", "tours", "registry", "official", "watch",
                 "venue-archive", "tour-archive", "out"):
        parser.add_argument("--" + flag, required=True)
    args = parser.parse_args()
    data = build(read(args.discovery), read(args.tours), read(args.registry),
                 read(args.official), read(args.watch),
                 [read(args.venue_archive), read(args.tour_archive)],
                 dt.datetime.now(dt.timezone.utc).isoformat())
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8")
    # Fixed marker, never expose private report or URL in a public job log.
    print("Private concert intake metrics written; no publication.")


if __name__ == "__main__":
    main()
