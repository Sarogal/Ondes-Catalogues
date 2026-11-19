#!/usr/bin/env python3
"""Generic independent, READ-ONLY recheck for first-party structured concerts.

No new source is admitted to VERIFIER_SPECS. No approvals are signed or written.
A trusted committed venue list, fresh official network fetch and exact recheck
produce a PRIVATE diagnostic suitable for designing a future publisher contract.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from collections import Counter
from pathlib import Path
from zoneinfo import ZoneInfo

import discover
import official_rss_jsonld_bridge as bridge
import triage

SCHEMA = "grossesondes.concert.structured-independent-preflight.v1"
SOURCE = "agenda_officiel_structuré"
IDENTITY_FIELDS = (
    "date", "name", "leadArtist", "venue", "city", "department",
    "classification", "sourceUrl",
)


def trusted_source(candidate, sources):
    """Committed official source, not self-declared candidate provenance."""
    if (not isinstance(candidate, dict)
            or not isinstance(sources, dict)
            or sources.get("schema") != "grossesondes.concert.sourcelist.v1"):
        return None
    url, page = candidate.get("sourceUrl"), candidate.get("sourcePage")
    for source in sources.get("venues", []):
        if not isinstance(source, dict):
            continue
        if not bridge.official_event_url(url, source.get("url")):
            continue
        if not (isinstance(page, str) and
                discover.same_host(page, source.get("url"))):
            continue
        if (triage.words(candidate.get("venue")) == triage.words(source.get("name"))
                and triage.words(candidate.get("city")) == triage.words(source.get("city"))
                and str(candidate.get("department")) == str(source.get("department"))):
            return source
    return None


def build(registry, sources, catalogue, approvals, today, *,
          fetch=discover.download, robots=discover.robots_allow, limit=8,
          scan_slot=0):
    if (registry.get("schema") != "grossesondes.concert.intake.v1"
            or not isinstance(registry.get("items"), dict)):
        raise ValueError("Private intake schema invalid")
    if (sources.get("schema") != "grossesondes.concert.sourcelist.v1"
            or not isinstance(sources.get("venues"), list)):
        raise ValueError("Source list schema invalid")
    if (catalogue.get("schemaVersion") != 1
            or catalogue.get("mode") != "preview-public-unlisted"
            or not isinstance(catalogue.get("events"), list)):
        raise ValueError("Public catalogue schema invalid")
    if (approvals.get("schema") != "grossesondes.concert.approvals.v1"
            or not isinstance(approvals.get("approvals"), list)):
        raise ValueError("Private approvals schema invalid")
    if (not isinstance(today, dt.date) or not 1 <= limit <= 12
            or scan_slot not in (0, 1, 2)):
        raise ValueError("Invalid date, slot or bounded probe budget")
    published = {
        (e.get("officialUrl"), e.get("date"))
        for e in catalogue["events"] if isinstance(e, dict)
    }
    approved = {
        (a["event"].get("officialUrl"), a["event"].get("date"))
        for a in approvals["approvals"] if isinstance(a, dict)
        and a.get("reviewDecision") == "approved"
        and isinstance(a.get("event"), dict)
    }
    eligible, exploratory = [], []
    for row in registry["items"].values():
        if not isinstance(row, dict) or not isinstance(row.get("candidate"), dict):
            continue
        candidate = row["candidate"]
        if (candidate.get("source") != SOURCE
                or candidate.get("reviewBucket") not in (
                    "genre_tag_review", "genre_unknown")
                or candidate.get("publicationAllowed") is not False
                or candidate.get("reviewRequired") is not True
                or candidate.get("possibleExistingConcert") is True
                or row.get("status", "pending_review") != "pending_review"
                or not isinstance(row.get("stableObservations"), int)
                or row["stableObservations"] < 2):
            continue
        try:
            event_date = dt.date.fromisoformat(candidate.get("date"))
        except (TypeError, ValueError):
            continue
        if event_date <= today:
            continue
        pair = (candidate.get("sourceUrl"), candidate.get("date"))
        if pair in approved or pair in published:
            continue
        if candidate.get("reviewBucket") == "genre_tag_review":
            eligible.append(candidate)
        else:
            exploratory.append(candidate)

    def choose(rows, budget):
        rows.sort(key=lambda c: (str(c.get("candidateId") or ""),
                                 str(c.get("sourceUrl") or "")))
        if not rows or budget <= 0:
            return []
        # Three daily slots cover different fixed-size cohorts, and all
        # candidates eventually rotate in without removing stability checks.
        offset = ((today.toordinal() * 3 + scan_slot) * limit) % len(rows)
        return [rows[(offset + i) % len(rows)]
                for i in range(min(budget, len(rows)))]

    selected = choose(eligible, limit)
    selected_exploratory = choose(exploratory, limit - len(selected))
    results, counts, robot_cache = [], Counter(), {}
    for diagnostic_only, candidate in (
            [(False, c) for c in selected]
            + [(True, c) for c in selected_exploratory]):
        reason = "unknown"
        status = "held"
        source = trusted_source(candidate, sources)
        if source is None:
            reason = "source_not_independently_mapped"
        else:
            try:
                url = candidate["sourceUrl"]
                if not robots(url, robot_cache):
                    reason = "robots_restricted"
                else:
                    page, actual = fetch(url, timeout=12, cap=900_000)
                    fresh = bridge.candidate_from_event_page(
                        candidate, page, actual, source, set(),
                        today, read_ld=discover.read_ld,
                        venue_candidate=discover.venue_candidate,
                        norm=discover.norm,
                        allow_generic_event=True)
                    if not fresh:
                        reason = "structured_event_proof_missing_or_ambiguous"
                    elif any(fresh.get(field) != candidate.get(field)
                             for field in IDENTITY_FIELDS
                             if not diagnostic_only or field != "classification"):
                        reason = "official_event_identity_changed"
                    elif diagnostic_only:
                        # An unknown-genre lead NEVER enters the approval
                        # pathway. This second reading only reveals whether
                        # an official MusicEvent now carries explicit tags.
                        status = "exploratory_evidence_only"
                        bucket = triage.triage(
                            fresh, catalogue=catalogue).get("reviewBucket")
                        reason = (
                            "fresh_official_music_event_genre_recovered"
                            if bucket == "genre_tag_review" else
                            "fresh_official_music_event_genre_still_unknown"
                        )
                    elif triage.triage(fresh, catalogue=catalogue).get(
                            "reviewBucket") != "genre_tag_review":
                        reason = "retriage_requires_review"
                    else:
                        status = "independent_structure_matched"
                        reason = "evidence_only_not_publisher_approved"
            except Exception:
                # Sensitive official URLs, tokens and exception payloads
                # must never appear in public logs.
                reason = "fetch_unavailable_or_invalid"
        counts[reason] += 1
        results.append({
            "candidateId": candidate.get("candidateId"),
            "probeKind": ("genre_unknown_diagnostic" if diagnostic_only
                          else "genre_review_preflight"),
            "status": status, "reason": reason,
            "publicationAllowed": False,
        })
    return {
        "schema": SCHEMA, "asOf": today.isoformat(),
        "eligible": len(eligible), "attempted": len(selected),
        "exploratoryEligible": len(exploratory),
        "exploratoryAttempted": len(selected_exploratory),
        "totalProbed": len(selected) + len(selected_exploratory),
        "exploratoryGenreRecovered": counts[
            "fresh_official_music_event_genre_recovered"],
        "exploratoryGenreUnknown": counts[
            "fresh_official_music_event_genre_still_unknown"],
        "structureMatched": sum(r["status"] == "independent_structure_matched"
                                for r in results),
        "reasonCounts": dict(sorted(counts.items())),
        "results": results, "approvalsProposed": 0, "publicationAllowed": False,
        "note": "Independent evidence preview only; publisher trust contract unchanged",
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--registry", required=True)
    p.add_argument("--sources", required=True)
    p.add_argument("--catalogue", required=True)
    p.add_argument("--approvals", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()
    def read(path):
        return json.loads(Path(path).read_text(encoding="utf-8"))
    local_now = dt.datetime.now(ZoneInfo("Europe/Paris"))
    local_slot = 0 if local_now.hour < 12 else 1 if local_now.hour < 18 else 2
    report = build(
        read(args.registry), read(args.sources), read(args.catalogue),
        read(args.approvals), local_now.date(), scan_slot=local_slot)
    Path(args.out).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    # Public Actions logs reveal ONLY aggregate counts, never candidates/URLs.
    print("Preflight structuré officiel : "
          + str(report["attempted"]) + " analysés ; "
          + str(report["structureMatched"]) + " concordances ; "
          + str(report["exploratoryAttempted"]) + " explorations de genre "
          + "(" + str(report["exploratoryGenreRecovered"]) + " tags retrouvés), "
          "aucune approbation ou publication.")


if __name__ == "__main__":
    main()
