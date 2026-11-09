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

REGISTRY_SCHEMA = "grossesondes.concert.intake.v1"
APPROVALS_SCHEMA = "grossesondes.concert.approvals.v1"
OUTPUT_SCHEMA = "grossesondes.concert.private-funnel.v1"

# Mirrors the source dispatch allowlist in official_recheck.process.
# Diagnostic only. Adding a value here NEVER grants publication permission.
AUTOMATIC_RECHECK_SOURCES = frozenset({
    "agenda_officiel_rex_genre",
    "agenda_officiel_molotov_genre",
    "agenda_officiel_ferrailleur_genre",
    "agenda_officiel_backstage_detail",
    "agenda_officiel_atabal_detail",
})
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
    bucket_counts = Counter()
    status_counts = Counter()
    date_counts = Counter()
    dispositions = Counter()
    source_counts = defaultdict(Counter)
    identities = Counter()
    eligible_stable = 0
    recheck_ready = 0
    evidence_leads = 0
    unique_future = set()
    signature_missing = 0
    sources_with_new_potential = Counter()

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
        stable = isinstance(record.get("stableObservations"), int) and (
            record["stableObservations"] >= 2
        )
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
        elif not official_detail:
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
        "legacyRowsWithoutStabilityProof": signature_missing,
        "candidateDateStatus": dict(sorted(date_counts.items())),
        "candidateReviewBuckets": dict(sorted(bucket_counts.items())),
        "candidatePrivateStatuses": dict(sorted(status_counts.items())),
        "exclusiveBlockingReasons": dict(sorted(dispositions.items())),
        "documentedOfficialGenreLeadsPendingFreshVerification": evidence_leads,
        "stableCandidatesInSupportedSourceQueue": eligible_stable,
        "readyForIndependentRecheck": recheck_ready,
        "possibleYieldBySource": dict(sorted(sources_with_new_potential.items())),
        "sourceDiagnostics": {
            name: dict(sorted(counts.items()))
            for name, counts in sorted(source_counts.items())
        },
        "notes": [
            "All source data and this diagnostic stay private.",
            "Textual identity collisions are advisory, never deduplicated for publication.",
            "Approved/published totals are full snapshots, not a single-cohort funnel.",
            "Official detail flags and genre tags are discovery claims, not independent proof.",
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
