#!/usr/bin/env python3
"""Private-only conversion audit of the cumulative Grosses Ondes concert intake.

The report is a diagnostic, NEVER an approval. It must be written only into
GrossesOndes (private); do not print private candidate records or source URLs.
Counts are not an instruction to bypass distinct-day stability or proof checks.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median
from zoneinfo import ZoneInfo

REGISTRY_SCHEMA = "grossesondes.concert.intake.v1"
APPROVALS_SCHEMA = "grossesondes.concert.approvals.v1"
OUTPUT_SCHEMA = "grossesondes.concert.private-funnel.v1"

# Immutable source-wide approval contract shared with official_recheck.
# Used ONLY to explain private blockers, never to grant publication.
from artist_genre_knowledge import private_genre_review
from verifier_contract import (
    AUTOMATIC_RECHECK_SOURCES,
    DISCOVERY_DETAIL_FLAG_REQUIRED_SOURCES,
)

TERMINAL_STATUSES = frozenset({"approved", "rejected", "superseded"})
EXCLUDED_BUCKETS = frozenset({
    "cancellation_watch", "excluded_nonconcert", "festival_overlap_review",
})


def _pair(source_url, day):
    return (str(source_url or ""), str(day or ""))


def _event_pair(item):
    return _pair(item.get("officialUrl"), item.get("date"))


def _future_date(value, as_of):
    if not isinstance(value, str) or not value:
        return "missing"
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError:
        return "invalid"
    return "future" if parsed >= as_of else "expired"


def _first_seen_paris_day(value):
    """A trusted UTC timestamp for an approximate Paris-calendar-day lag."""
    if not isinstance(value, str):
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(ZoneInfo("Europe/Paris")).date()


def _identity(item):
    """A *diagnostic* collision key, never an authoritative event dedupe."""
    normalized = lambda v: " ".join(str(v or "").casefold().split())
    return (normalized(item.get("date")),
            normalized(item.get("venueCatalogueId") or item.get("venue")),
            normalized(item.get("city")),
            normalized(item.get("name")))


def build(registry, approvals, catalogue, as_of):
    if not isinstance(registry, dict) or registry.get("schema") != REGISTRY_SCHEMA:
        raise ValueError("Unexpected private registry schema")
    if not isinstance(registry.get("items"), dict):
        raise ValueError("Private registry items missing")
    if not isinstance(approvals, dict) or approvals.get("schema") != APPROVALS_SCHEMA:
        raise ValueError("Unexpected private approvals schema")
    if not isinstance(approvals.get("approvals"), list):
        raise ValueError("Private approvals missing")
    if not isinstance(catalogue, dict) or catalogue.get("schemaVersion") != 1:
        raise ValueError("Unexpected public concert catalogue")
    if not isinstance(catalogue.get("events"), list):
        raise ValueError("Public events missing")
    if not isinstance(as_of, dt.date):
        raise ValueError("As-of must be a date")

    approved_pairs = set()
    for approval in approvals["approvals"]:
        if approval.get("reviewDecision") == "approved":
            e = approval.get("event") or {}
            approved_pairs.add(_event_pair(e))
    published_pairs = {_event_pair(e) for e in catalogue["events"]}
    window_start = as_of - dt.timedelta(days=6)

    def within_week(value):
        try:
            day = dt.date.fromisoformat(str(value))
        except (TypeError, ValueError):
            return False
        return window_start <= day <= as_of

    automatic_approvals_this_week = [
        a for a in approvals["approvals"]
        if a.get("reviewDecision") == "approved"
        and a.get("reviewedBy") == "automated-official-recheck"
        and within_week(a.get("reviewedAt"))
    ]
    published_automatic_this_week = sum(
        _event_pair(a.get("event") or {}) in published_pairs
        for a in automatic_approvals_this_week
    )
    first_recorded_by_day = Counter()
    for event in catalogue["events"]:
        history = event.get("history")
        if not isinstance(history, list) or not history or not isinstance(history[0], dict):
            continue
        first_date = history[0].get("date")
        if within_week(first_date):
            first_recorded_by_day[first_date] += 1
    first_recorded_this_week = sum(first_recorded_by_day.values())
    bucket_counts = Counter()
    status_counts = Counter()
    date_counts = Counter()
    dispositions = Counter()
    source_counts = defaultdict(Counter)
    source_dispositions = defaultdict(Counter)
    identities = Counter()
    eligible_stable = 0
    recheck_ready = 0
    evidence_leads = 0
    unique_future = set()
    signature_missing = 0
    sources_with_new_potential = Counter()
    effective_states = Counter()
    unlisted_location_reviews = Counter()
    first_seen_by_published_pair = {}

    for record in registry["items"].values():
        if not isinstance(record, dict) or not isinstance(record.get("candidate"), dict):
            raise ValueError("Corrupt private registry row")
        item = record["candidate"]
        if item.get("publicationAllowed") is not False or item.get("reviewRequired") is not True:
            raise ValueError("Unquarantined candidate in registry")
        status = record.get("status", "pending_review")
        if status not in TERMINAL_STATUSES | {"pending_review"}:
            raise ValueError("Unknown private status")
        source = str(item.get("source") or "unidentified")
        bucket = str(item.get("reviewBucket") or "unclassified")
        date_status = _future_date(item.get("date"), as_of)
        date_counts[date_status] += 1
        status_counts[status] += 1
        bucket_counts[bucket] += 1
        key = _identity(item)
        identities[key] += 1
        if date_status == "future":
            unique_future.add(key)
        if "identitySignature" not in record or "stableObservations" not in record:
            signature_missing += 1

        pair = _pair(item.get("sourceUrl"), item.get("date"))
        published = pair in published_pairs
        approved = pair in approved_pairs
        # Derived reporting states only. Never edit the permanent private
        # decision, which remains append-only and is managed separately.
        if published:
            effective_states["published_exact_url_date"] += 1
            first_day = _first_seen_paris_day(record.get("firstSeenAt"))
            if first_day is not None:
                previous_first_day = first_seen_by_published_pair.get(pair)
                if previous_first_day is None or first_day < previous_first_day:
                    first_seen_by_published_pair[pair] = first_day
        elif approved:
            effective_states["approved_not_published_exact_url_date"] += 1
        elif status in TERMINAL_STATUSES:
            effective_states["privately_decided_not_exactly_matched"] += 1
        else:
            effective_states["pending_not_exactly_matched"] += 1
        stable = isinstance(record.get("stableObservations"), int) and (
            record["stableObservations"] >= 2
        )
        # A concert does not have to be in a previously known venue.
        # These source-claimed location markers are PRIVATE prioritization
        # only: a real show, source identity and coordinates still need
        # independent proof before adding any public pin.
        if (date_status == "future" and not published and not approved
                and status == "pending_review"):
            if item.get("newVenueToReview") is True:
                unlisted_location_reviews["futureUnlistedLocationLeads"] += 1
                if item.get("reviewBucket") == "genre_tag_review":
                    unlisted_location_reviews["genreEvidencePresent"] += 1
                if stable:
                    unlisted_location_reviews["stableOnDistinctDays"] += 1
            if item.get("sameCityArtistCollisionAdvisory") is True:
                unlisted_location_reviews["differentNamedVenueCollisionAdvisories"] += 1
            if not item.get("venue") or not item.get("city"):
                unlisted_location_reviews["missingNamedPlaceOrCity"] += 1
        official_detail = item.get("officialDetailFound") is True
        genre_tag = bucket == "genre_tag_review"
        first_party = (source.startswith("agenda_officiel_")
                       or "_official_" in source
                       or source.startswith("promoter_official_")
                       or source.startswith("artist_official_"))
        source_compatible = source in AUTOMATIC_RECHECK_SOURCES
        metrics = source_counts[source]
        metrics["discovered"] += 1
        metrics["futureDated"] += (date_status == "future")
        metrics["officialDetailDeclared"] += official_detail
        metrics["genreReview"] += genre_tag
        metrics["stableAcrossDays"] += stable
        metrics["exactApprovedUrlDate"] += approved
        metrics["exactPublishedUrlDate"] += published

        # Exclusive, conservative reasons (never equate 'recheck' to approval).
        if published:
            disposition = "already_published_exact_url_date"
        elif approved:
            disposition = "already_approved_exact_url_date"
        elif status in TERMINAL_STATUSES:
            disposition = "privately_decided"
        elif date_status == "missing":
            disposition = "undated"
        elif date_status == "invalid":
            disposition = "invalid_date"
        elif date_status == "expired":
            disposition = "expired"
        elif bucket in EXCLUDED_BUCKETS:
            disposition = "cancellation_festival_or_nonconcert"
        elif item.get("possibleExistingConcert") is True:
            disposition = "possible_duplicate_requires_reconciliation"
        elif not genre_tag:
            disposition = "musical_genre_unconfirmed"
        elif not item.get("sourceUrl", "").startswith("https://"):
            disposition = "source_url_invalid"
        elif (source in DISCOVERY_DETAIL_FLAG_REQUIRED_SOURCES
              and not official_detail):
            disposition = "missing_first_party_detail_evidence"
        elif not first_party:
            disposition = "first_party_status_not_established"
        elif not stable:
            disposition = "awaiting_distinct_day_stability"
        elif not source_compatible:
            disposition = "verified_adapter_not_available"
        else:
            disposition = "ready_for_independent_recheck"
        dispositions[disposition] += 1
        source_dispositions[source][disposition] += 1

        # Review queue potential is not an automatically approvable concert.
        if (date_status == "future" and genre_tag and official_detail and first_party
                and not published and not approved and status == "pending_review"
                and not item.get("possibleExistingConcert")):
            evidence_leads += 1
            sources_with_new_potential[source] += 1
        if (date_status == "future" and genre_tag and source_compatible
                and not published and not approved and status == "pending_review"
                and not item.get("possibleExistingConcert") and stable):
            eligible_stable += 1
        if disposition == "ready_for_independent_recheck":
            recheck_ready += 1

    # Approximate delay: first *archived* observation to the earliest
    # publisher-authored history date, never an exact real-time publication
    # duration. A repeated official URL/date is ambiguous and excluded.
    events_by_pair = defaultdict(list)
    for event in catalogue["events"]:
        events_by_pair[_event_pair(event)].append(event)
    measured_lag_days = []
    excluded_ambiguous = 0
    excluded_non_publisher_history = 0
    published_before_first_seen = 0
    for pair, first_day in first_seen_by_published_pair.items():
        matches = events_by_pair.get(pair, [])
        if len(matches) != 1:
            excluded_ambiguous += 1
            continue
        history = matches[0].get("history")
        if (not isinstance(history, list) or not history
                or not isinstance(history[0], dict)
                or history[0].get("change") != "Ajout après revue des preuves officielles"):
            excluded_non_publisher_history += 1
            continue
        try:
            publication_day = dt.date.fromisoformat(history[0]["date"])
        except (KeyError, TypeError, ValueError):
            excluded_non_publisher_history += 1
            continue
        if publication_day < first_day:
            # Some discovery sources only found a concert after publication.
            # A negative lag cannot be a true time-to-publication measurement.
            published_before_first_seen += 1
        else:
            measured_lag_days.append((publication_day - first_day).days)

    return {
        "schema": OUTPUT_SCHEMA,
        "asOf": as_of.isoformat(),
        "publicationAllowed": False,
        "discoveredRegistryRows": len(registry["items"]),
        "distinctTextualIdentitiesEstimate": len(identities),
        "diagnosticIdentityCollisionGroups": sum(v > 1 for v in identities.values()),
        "diagnosticCollisionExcessRows": sum(v - 1 for v in identities.values() if v > 1),
        "futureDatedDistinctTextualIdentitiesEstimate": len(unique_future),
        "exactApprovedUrlDateInRegistry": sum(
            v["exactApprovedUrlDate"] for v in source_counts.values()),
        "exactPublishedUrlDateInRegistry": sum(
            v["exactPublishedUrlDate"] for v in source_counts.values()),
        "privateApprovedEventsTotal": len(approvals["approvals"]),
        "publicEventsTotal": len(catalogue["events"]),
        "artistGenreKnowledge": private_genre_review(registry, catalogue, as_of),
        "lastSevenDaysInclusive": {
            "start": window_start.isoformat(),
            "end": as_of.isoformat(),
            "automaticallyApproved": len(automatic_approvals_this_week),
            "automaticallyApprovedAndObservedPublished": published_automatic_this_week,
            # Historical first record is an indicator; the cloud sync's
            # per-run newEvents remains the authoritative publication delta.
            "publicEventsFirstRecordedInHistory": first_recorded_this_week,
            "publicEventsFirstRecordedInHistoryByDay": dict(sorted(first_recorded_by_day.items())),
            "authoritativePublicDeltaSource": "grossesondes-concerts-cloud-sync",
        },
        "legacyRowsWithoutStabilityProof": signature_missing,
        "candidateDateStatus": dict(sorted(date_counts.items())),
        "candidateReviewBuckets": dict(sorted(bucket_counts.items())),
        "candidatePrivateStatuses": dict(sorted(status_counts.items())),
        "effectiveCandidateStates": dict(sorted(effective_states.items())),
        "eventLocationReview": {
            "futureUnlistedLocationLeads": unlisted_location_reviews[
                "futureUnlistedLocationLeads"],
            "genreEvidencePresent": unlisted_location_reviews[
                "genreEvidencePresent"],
            "stableOnDistinctDays": unlisted_location_reviews[
                "stableOnDistinctDays"],
            "differentNamedVenueCollisionAdvisories": unlisted_location_reviews[
                "differentNamedVenueCollisionAdvisories"],
            "missingNamedPlaceOrCity": unlisted_location_reviews[
                "missingNamedPlaceOrCity"],
            "publicationAllowed": False,
            "note": "An unlisted or outdoor site needs independent event and location proof",
        },
        "discoveryToFirstRecordedPublication": {
            "estimated": True,
            "unit": "whole Paris calendar days",
            "method": "private firstSeenAt to publisher first history date, exact URL+date only",
            "measuredDistinctEvents": len(measured_lag_days),
            "minDays": min(measured_lag_days) if measured_lag_days else None,
            "medianDays": median(measured_lag_days) if measured_lag_days else None,
            "maxDays": max(measured_lag_days) if measured_lag_days else None,
            "publishedBeforeRegistryFirstSeen": published_before_first_seen,
            "excludedNonPublisherHistory": excluded_non_publisher_history,
            "excludedAmbiguousUrlDate": excluded_ambiguous,
        },
        "exclusiveBlockingReasons": dict(sorted(dispositions.items())),
        "documentedOfficialGenreLeadsPendingFreshVerification": evidence_leads,
        "stableCandidatesInSupportedSourceQueue": eligible_stable,
        "readyForIndependentRecheck": recheck_ready,
        "possibleYieldBySource": dict(sorted(sources_with_new_potential.items())),
        "sourceDiagnostics": {
            name: dict(sorted(counts.items()))
            for name, counts in sorted(source_counts.items())
        },
        # Private aggregate only: show which source is blocked by which
        # exclusive reason, without candidate IDs, names or official URLs.
        "sourceBlockingReasons": {
            name: dict(sorted(counts.items()))
            for name, counts in sorted(source_dispositions.items())
        },
        "notes": [
            "All source data and this diagnostic stay private.",
            "Textual identity collisions are advisory, never deduplicated for publication.",
            "Approved/published totals are full snapshots, not a single-cohort funnel.",
            "Effective candidate states reconcile exact source URL+date only and never edit registry status.",
            "Discovery-to-history lag is an approximate subset, not actual GitHub Pages deployment time.",
            "Public first-history-date metric is not the cloud sync event delta.",
            "Official detail flags and genre tags are discovery claims, not independent proof.",
            "The discovery detail flag is required only by verifiers that enforce it.",
            "Per-source blocking counts are diagnostics, never automatic approvals.",
            "Two distinct-day identity-stable observations remain mandatory.",
            "Only independently rechecked events pass preflight and public cloud sync.",
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--approvals", required=True, type=Path)
    parser.add_argument("--catalogue", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    read = lambda path: json.loads(path.read_text(encoding="utf-8"))
    result = build(read(args.registry), read(args.approvals),
                   read(args.catalogue), dt.datetime.now(dt.timezone.utc).date())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print("Private concerts conversion funnel generated (no data disclosed).")


if __name__ == "__main__":
    main()
