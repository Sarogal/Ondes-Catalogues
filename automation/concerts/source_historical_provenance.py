#!/usr/bin/env python3
"""Historical provenance signals for UNKNOWN concert sources (PRIVATE only).

When the same host+physical venue already appears on several independently
approved AND published past concerts, there is no reason to pretend the site
has never been seen. This is an evidence dossier, not a new publisher trust
authority: URL ownership could have changed and every future event still
needs fresh independent verification.

No network, fixed domain allowlist, source admission, publisher modification,
or automatic event approval occurs here.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from collections import Counter, defaultdict
from pathlib import Path
from zoneinfo import ZoneInfo

import source_admission_intake as intake

SCHEMA = "grossesondes.concert.historical-source-provenance.v1"
APPROVALS = "grossesondes.concert.approvals.v1"
CATALOGUE = "grossesondes.concert.sourcelist.v1"


def norm(value):
    return intake.normalized(value)


def site_key(row):
    if not isinstance(row, dict):
        return None
    return (norm(row.get("name")), norm(row.get("city")),
            str(row.get("department") or ""))


def published_event_matches(catalogue):
    """Public, dated event record is distinct from private claimed approval."""
    return {
        (e.get("id"), e.get("officialUrl"), e.get("date"), e.get("venueId"))
        for e in catalogue["events"]
        if isinstance(e, dict)
        and isinstance(e.get("id"), str)
        and isinstance(e.get("officialUrl"), str)
    }


def signed_approval(approval, public_events):
    if (not isinstance(approval, dict)
            or approval.get("reviewDecision") != "approved"
            or approval.get("reviewedBy") != "independent-official-verifier"
            or not isinstance(approval.get("reviewedAt"), str)
            or not isinstance(approval.get("event"), dict)):
        return None
    event = approval["event"]
    host = intake.valid_https(event.get("officialUrl"))
    if (host is None
            or event.get("status") != "confirmed"
            or not isinstance(event.get("artistIds"), list)
            or not event["artistIds"]
            or not isinstance(event.get("genres"), list)
            or not event["genres"]
            or (event.get("id"), event.get("officialUrl"),
                event.get("date"), event.get("venueId")) not in public_events):
        return None
    try:
        day = dt.date.fromisoformat(event["date"])
        reviewed = dt.date.fromisoformat(approval["reviewedAt"])
    except (ValueError, TypeError, KeyError):
        return None
    if reviewed > day:
        return None
    proofs = approval.get("officialEvidence")
    if not isinstance(proofs, list) or not any(
        isinstance(p, dict)
        and p.get("url") == event["officialUrl"]
        and p.get("checkedAt") == approval["reviewedAt"]
        and p.get("proofType") == "official-organizer-or-venue"
        and isinstance(p.get("checkedFields"), list)
        and {"artists", "date", "venue", "genre"}.issubset(
            set(p["checkedFields"]))
        for p in proofs):
        return None
    return host, event


def build(queue, approvals, catalogue, sources, today):
    if (not isinstance(queue, dict)
            or queue.get("schema") != intake.SCHEMA
            or queue.get("automaticTrustGranted") is not False
            or queue.get("publicationAllowed") is not False
            or not isinstance(queue.get("reviewQueue"), list)):
        raise ValueError("Untrusted source-discovery queue")
    if (not isinstance(approvals, dict)
            or approvals.get("schema") != APPROVALS
            or not isinstance(approvals.get("approvals"), list)):
        raise ValueError("Invalid private approval ledger")
    if (not isinstance(catalogue, dict)
            or catalogue.get("schemaVersion") != 1
            or not isinstance(catalogue.get("events"), list)
            or not isinstance(catalogue.get("venues"), list)):
        raise ValueError("Invalid published concert catalogue")
    if (not isinstance(sources, dict)
            or sources.get("schema") != CATALOGUE
            or not isinstance(sources.get("venues"), list)):
        raise ValueError("Invalid reviewed source hints")
    if not isinstance(today, dt.date) or isinstance(today, dt.datetime):
        raise ValueError("Invalid day")

    venue_map = {v["id"]: v for v in catalogue["venues"]
                 if isinstance(v, dict) and isinstance(v.get("id"), str)}
    public_events = published_event_matches(catalogue)

    # Distinct historical APPROVALS for distinct real PUBLIC concerts.
    history = defaultdict(dict)
    for approval in approvals["approvals"]:
        hit = signed_approval(approval, public_events)
        if hit is None:
            continue
        host, event = hit
        venue = venue_map.get(event.get("venueId"))
        if venue is None or not all(site_key(venue)):
            continue
        key = (host, venue["id"])
        history[key][event["id"]] = {
            "eventId": event["id"], "date": event["date"],
            "officialUrl": event["officialUrl"],
        }

    # Source-list entries are corroboration HINTS, NOT domain ownership proof.
    source_hints = defaultdict(set)
    for source in sources["venues"]:
        if not isinstance(source, dict):
            continue
        host = intake.valid_https(source.get("url"))
        k = site_key(source)
        if host and all(k):
            source_hints[host].add(k)

    checks = []
    for item in queue["reviewQueue"]:
        if not isinstance(item, dict):
            raise ValueError("Invalid queued source entry")
        host = item.get("host")
        if intake.valid_https("https://" + str(host) + "/") != host:
            raise ValueError("Invalid source host")
        if item.get("alreadyReviewedAuthority") is not False:
            continue
        candidates = []
        for (historical_host, venue_id), events in history.items():
            if historical_host != host or len(events) < 2:
                continue
            venue = venue_map[venue_id]
            key = site_key(venue)
            # A venue merely sharing an official host can be different from
            # this candidate's site. Never infer location from host alone.
            if (norm(venue.get("name")) not in {
                    norm(name) for name in item.get("venues", [])}
                    or norm(venue.get("city")) not in {
                        norm(city) for city in item.get("cities", [])}):
                continue
            # The source catalogue is separately curated but NOT a trust root;
            # require a same-host exact venue+city+department record there too.
            if key not in source_hints.get(host, set()):
                continue
            candidates.append({
                "venueId": venue_id,
                "venueName": venue["name"],
                "city": venue["city"],
                "department": venue["department"],
                "historicalPublishedApprovals": len(events),
                "supportingEvents": sorted(
                    events.values(), key=lambda x: x["eventId"])[:4],
            })
        candidates.sort(key=lambda x: (-x["historicalPublishedApprovals"],
                                       x["venueId"]))
        state = ("previously_signed_published_origin_at_venue"
                 if len(candidates) == 1
                 else ("ambiguous_historical_venue_origin"
                       if len(candidates) > 1
                       else "independent_source_identity_still_needed"))
        checks.append({
            "host": host, "state": state,
            "historicalVenueCandidates": candidates,
            "historicalSignedProof": state == "previously_signed_published_origin_at_venue",
            "sourceOwnershipFreshlyVerified": False,
            "independentCurrentConcertVerified": False,
            "automaticTrustGranted": False, "publicationAllowed": False,
        })
    counts = Counter(row["state"] for row in checks)
    return {
        "schema": SCHEMA, "asOf": today.isoformat(),
        "unreviewedSourceHostsConsidered": len(checks),
        "previouslySignedPublishedVenueOrigins": counts[
            "previously_signed_published_origin_at_venue"],
        "stillWithoutHistoricalProvenance": counts[
            "independent_source_identity_still_needed"],
        "ambiguousHistoricalOrigins": counts[
            "ambiguous_historical_venue_origin"],
        "sourceOwnershipFreshlyVerified": False,
        "automaticTrustGranted": False, "publicationAllowed": False,
        "originChecks": checks,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--intake", type=Path, required=True)
    parser.add_argument("--approvals", type=Path, required=True)
    parser.add_argument("--catalogue", type=Path, required=True)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build(
        json.loads(args.intake.read_text(encoding="utf-8")),
        json.loads(args.approvals.read_text(encoding="utf-8")),
        json.loads(args.catalogue.read_text(encoding="utf-8")),
        json.loads(args.sources.read_text(encoding="utf-8")),
        dt.datetime.now(ZoneInfo("Europe/Paris")).date())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print("Private historical source evidence reviewed; no domain authority issued.")


if __name__ == "__main__":
    main()
