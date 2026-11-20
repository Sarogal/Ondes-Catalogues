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
    # Keep only non-sensitive bounded counters in the private report:
    # page URL, concert ID, HTML excerpts and artist names remain private in
    # the discovery worker and are never sent to Actions logs.
    def count(value):
        return value if type(value) is int and 0 <= value <= 100_000 else 0

    return {
        "name": item.get("venue", "unknown"), "status": status,
        "detailsRead": count(details.get("detailPagesRead", 0)),
        "detailsErrors": count(details.get("detailErrors", 0)),
        "pagesChecked": count(item.get("pagesChecked", 0)),
        "eventDetailLinksFound": count(item.get("eventDetailLinksFound", 0)),
        "eventDetailPagesFetched": count(item.get("eventDetailPagesFetched", 0)),
        "htmlVisibleBillLeads": count(item.get("htmlVisibleBillLeads", 0)),
        "candidatesDetected": count(item.get("candidatesDetected", 0)),
    }


def describe_organizer(item):
    """Only non-sensitive counters; no organizer URL or event identity in metrics."""
    def bounded(value):
        return value if type(value) is int and 0 <= value <= 100_000 else 0

    status = item.get("status", "unknown")
    if status not in {"read", "held_source_unavailable"}:
        status = "unknown"
    return {
        "organizerSourceId": item.get("organizerSourceId", "unknown"),
        "status": status,
        "listingPageFetched": item.get("listingPageFetched") is True,
        "eventDetailLinks": bounded(item.get("eventDetailLinks")),
        "individualPagesRead": bounded(item.get("individualPagesRead")),
        "individualPagesHeld": bounded(item.get("individualPagesHeld")),
        "candidateCount": bounded(item.get("candidateCount")),
    }


def build(discovery, tours, registry, official, watch, archive_summaries, when,
          organizers=None):
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
    if organizers is None:
        organizers = {"schema": "grossesondes.concert.discovery.v1",
                      "candidates": [], "sourceChecks": []}
    if (organizers.get("schema") != "grossesondes.concert.discovery.v1"
            or not isinstance(organizers.get("candidates"), list)
            or not isinstance(organizers.get("sourceChecks"), list)):
        raise ValueError("Invalid first-party organizer report")
    organizer_sources = [describe_organizer(x)
                         for x in organizers["sourceChecks"]
                         if isinstance(x, dict)]
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
        "venueHtmlVisibleBillLeads": sum(
            x["htmlVisibleBillLeads"] for x in sources),
        "venueEventDetailPagesFetched": sum(
            x["eventDetailPagesFetched"] for x in sources),
        "venueEventLinksDiscovered": sum(
            x["eventDetailLinksFound"] for x in sources),
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
        "organizerDiscoveriesThisRun": len(organizers["candidates"]),
        "organizerSources": organizer_sources,
        "organizerSourcesFetched": sum(
            x["status"] == "read" for x in organizer_sources),
        "organizerSourcesHeld": sum(
            x["status"] == "held_source_unavailable" for x in organizer_sources),
        "organizerDetailPagesRead": sum(
            x["individualPagesRead"] for x in organizer_sources),
        "organizerDetailPagesHeld": sum(
            x["individualPagesHeld"] for x in organizer_sources),
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
    parser.add_argument("--organizers", required=True)
    parser.add_argument("--organizer-archive", required=True)
    args = parser.parse_args()
    data = build(read(args.discovery), read(args.tours), read(args.registry),
                 read(args.official), read(args.watch),
                 [read(args.venue_archive), read(args.tour_archive),
                  read(args.organizer_archive)],
                 dt.datetime.now(dt.timezone.utc).isoformat(),
                 organizers=read(args.organizers))
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8")
    # Fixed marker, never expose private report or URL in a public job log.
    print("Private concert intake metrics written; no publication.")


if __name__ == "__main__":
    main()
