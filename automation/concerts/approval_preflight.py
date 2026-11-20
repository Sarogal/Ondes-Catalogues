#!/usr/bin/env python3
"""Fail-closed, offline publication preflight for proposed private approvals.

Official discoveries are still quarantined.  This command verifies that a
proposed *append-only* change to approved.json survives the EXACT cloud
publisher's merge/validation, before an automated workflow may persist it.
No private record is uploaded to a public workflow artifact or printed.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import os
from pathlib import Path
import sys
import tempfile
from zoneinfo import ZoneInfo


class PublisherRejections(ValueError):
    """Private diagnostics for proposed events held by the real publisher."""

    def __init__(self, rejections):
        self.rejections = rejections
        super().__init__(
            "At least one proposed approval was held or modified by the publisher: "
            + str(len(rejections)) + " rejected; IDs="
            + ",".join(row["eventId"] for row in rejections)
        )


def require(condition, message):
    if not condition:
        raise ValueError(message)


def check_append_only(previous, proposed, today):
    """Reject deletion, mutation, reviewer substitution and duplicate IDs."""
    require(isinstance(previous, dict) and isinstance(proposed, dict),
            "Approval queues must be JSON objects")
    require(previous.get("schema") == "grossesondes.concert.approvals.v1"
            and proposed.get("schema") == previous["schema"],
            "Unknown approvals schema")
    require(previous.keys() == proposed.keys(), "Approval metadata changed")
    old = previous.get("approvals")
    new = proposed.get("approvals")
    require(isinstance(old, list) and isinstance(new, list),
            "Missing approval list")
    require(len(new) >= len(old) and new[:len(old)] == old,
            "Existing private approvals were modified or removed")
    # Event-scoped locations are paired additions in the SAME private
    # transaction as their individually approved concerts. Unlike historical
    # permanent venue approvals, they cannot be appended independently.
    prior_sites = previous.get("venueApprovals")
    next_sites = proposed.get("venueApprovals")
    if prior_sites is not None:
        require(isinstance(prior_sites, list) and isinstance(next_sites, list),
                "Private venue approval list invalid")
        require(len(next_sites) >= len(prior_sites)
                and next_sites[:len(prior_sites)] == prior_sites,
                "Existing venue approvals changed or removed")
        added_sites = next_sites[len(prior_sites):]
    else:
        require(next_sites is None, "Missing historical venue ledger")
        added_sites = []
    for key in previous:
        if key not in ("approvals", "venueApprovals"):
            require(proposed[key] == previous[key],
                    "Protected private approval metadata changed")
    appended = new[len(old):]
    require(len(appended) <= 16, "Too many new approvals in a single pass")
    existing_ids = {a.get("event", {}).get("id") for a in old
                    if isinstance(a, dict) and isinstance(a.get("event"), dict)}
    added_ids = set()
    # A new event may not reuse a first-party page for the SAME date under a
    # different ID. Include the immutable private history, not just this batch.
    # A genuinely new date at an unchanged official URL remains eligible.
    pairs = {
        (a["event"]["officialUrl"], a["event"]["date"])
        for a in old
        if isinstance(a, dict) and isinstance(a.get("event"), dict)
        and all(isinstance(a["event"].get(key), str) and a["event"][key]
                for key in ("officialUrl", "date"))
    }
    paired_site_events = {
        site.get("eventBinding", {}).get("eventId")
        for site in added_sites
        if isinstance(site, dict)
        and isinstance(site.get("eventBinding"), dict)
    }
    for approval in appended:
        event = approval.get("event") if isinstance(approval, dict) else None
        # The independent event signer is ONLY admissible for a newly paired,
        # separately reviewed event site. Ordinary auto approvals still require
        # the standard automated reviewer and exact publisher recheck.
        reviewer = approval.get("reviewedBy") if isinstance(approval, dict) else None
        allowed_reviewer = (
            reviewer == "automated-official-recheck" or
            (reviewer == "independent-official-verifier"
             and isinstance(event, dict)
             and event.get("id") in paired_site_events)
        )
        require(isinstance(approval, dict)
                and approval.get("reviewDecision") == "approved"
                and allowed_reviewer
                and approval.get("reviewedAt") == today.isoformat(),
                "Unexpected official reviewer or stale official review")
        require(isinstance(event, dict), "Missing approved event")
        event_id = event.get("id")
        require(isinstance(event_id, str) and event_id
                and event_id not in existing_ids and event_id not in added_ids,
                "Duplicate or missing approval event ID")
        added_ids.add(event_id)
        pair = (event.get("officialUrl"), event.get("date"))
        require(all(isinstance(x, str) and x for x in pair)
                and pair not in pairs,
                "Duplicate official URL and event date")
        pairs.add(pair)
    new_by_id = {a["event"]["id"]: a["event"] for a in appended}
    old_site_ids = {
        a.get("venue", {}).get("id") for a in prior_sites or []
        if isinstance(a, dict) and isinstance(a.get("venue"), dict)
    }
    new_site_ids = set()
    require(len(added_sites) <= 6,
            "More than six new event sites in a single private transaction")
    for site in added_sites:
        require(isinstance(site, dict)
                and site.get("venueKind") == "independent-event-site-v1"
                and site.get("reviewDecision") == "approved"
                and site.get("reviewedBy") == "independent-official-verifier"
                and site.get("reviewedAt") == today.isoformat(),
                "Protected private approval metadata changed: unexpected venue reviewer")
        venue = site.get("venue")
        binding = site.get("eventBinding")
        require(isinstance(venue, dict) and isinstance(binding, dict)
                and isinstance(venue.get("id"), str)
                and venue["id"] not in old_site_ids
                and venue["id"] not in new_site_ids,
                "Duplicate or unlinked event site ID")
        new_site_ids.add(venue["id"])
        linked = new_by_id.get(binding.get("eventId"))
        require(linked is not None
                and linked.get("venueId") == venue["id"]
                and linked.get("date") == binding.get("eventDate")
                and linked.get("officialUrl") == binding.get("eventOfficialUrl"),
                "Event site must be paired with a NEW approved concert")
    return appended


def _new_event_site_approvals(previous, proposed):
    old = previous.get("venueApprovals") or []
    return proposed.get("venueApprovals", [])[len(old):]


def validate_proposal(previous, proposed, reference, current, today, publisher):
    """Use the real publisher to prove that EVERY new approval can be emitted."""
    appended = check_append_only(previous, proposed, today)
    new_sites = _new_event_site_approvals(previous, proposed)
    if not appended:
        return {"newApprovals": 0, "publishableEvents": 0,
                "validatedByPublisher": False}
    already = {e["id"] for e in current["events"]}
    incoming = {approval["event"]["id"] for approval in appended}
    require(not incoming.intersection(already),
            "An automated approval ID is already in the public catalogue")
    # Concurrent cloud publication can leave an intake checkout behind the
    # signed private history. Reproduce the precise publisher baseline from
    # PREVIOUS (already signed) approvals before checking new signatures.
    # This does not authorize an unsigned event or relax any publisher gate.
    old_signed = {
        approval["event"]["id"]: approval["event"]
        for approval in previous["approvals"]
        if isinstance(approval, dict) and isinstance(approval.get("event"), dict)
        and isinstance(approval["event"].get("id"), str)
    }
    require(len(old_signed) == len(previous["approvals"]),
            "Duplicate or malformed previously signed approvals")
    pending_old = set(old_signed) - already
    baseline_by_id = None
    baseline_ids = already
    if pending_old:
        baseline, _baseline_stats = publisher(
            reference, current, previous, today)
        baseline_rows = baseline.get("events") if isinstance(baseline, dict) else None
        require(isinstance(baseline_rows, list),
                "Signed publisher baseline unavailable")
        baseline_by_id = {row.get("id"): row for row in baseline_rows
                          if isinstance(row, dict)}
        baseline_ids = set(baseline_by_id)
        require(len(baseline_by_id) == len(baseline_rows)
                and already.issubset(baseline_ids)
                and baseline_ids.issubset(already | set(old_signed)),
                "Signed publisher baseline lost an event or inserted an unsigned event")
        for event_id in baseline_ids - already:
            proof = old_signed[event_id]
            actual = baseline_by_id[event_id]
            require(all(actual.get(key) == value for key, value in proof.items()),
                    "Previously signed approval mutated by publisher")
    # Compute the exact baseline of previously signed permanent venues;
    # a newly appended event site must be the ONLY extra geographic addition.
    # This is limited to site-bearing batches; ordinary approvals remain
    # backwards compatible and do not incur a second publisher call.
    baseline_venues = None
    if new_sites:
        before_sites, _ = publisher(reference, current, previous, today)
        old_venues = before_sites.get("venues") if isinstance(before_sites, dict) else None
        require(isinstance(old_venues, list), "Publisher venue baseline unavailable")
        baseline_venues = {v.get("id"): v for v in old_venues
                           if isinstance(v, dict)}
        require(len(baseline_venues) == len(old_venues),
                "Publisher baseline contained duplicate venue IDs")
    candidate, stats = publisher(reference, current, proposed, today)
    published = {e["id"]: e for e in candidate["events"]}
    rejected = []
    for approval in appended:
        event = approval["event"]
        published_event = published.get(event["id"])
        if published_event is not None and all(
                published_event.get(field) == value for field, value in event.items()):
            continue
        # ONLY identifiers, field names and publisher text; never full proposed
        # approvals, source HTML or evidence URLs. Stored in private intake.
        reasons = [
            str(row.get("reason", ""))
            for row in (stats.get("held") or [])
            if isinstance(row, dict) and row.get("candidateId") == event["id"]
        ]
        if published_event is None:
            detail = "not emitted by publisher"
            differing = []
        else:
            differing = sorted(
                field for field, value in event.items()
                if published_event.get(field) != value
            )
            detail = "changed fields: " + ", ".join(differing)
        rejected.append({
            "eventId": event["id"],
            "publisherResult": detail,
            "changedFields": differing,
            "publisherReason": reasons[0][:160].replace("\n", " ").replace("\r", " ") if reasons else None,
        })
    # Prioritize the real publisher's EVENT rejections, so the existing
    # safe-subset mechanism can drop the paired site together with the event.
    if rejected:
        raise PublisherRejections(rejected)
    if new_sites:
        out_venues = candidate.get("venues") if isinstance(candidate, dict) else None
        require(isinstance(out_venues, list), "Publisher site output missing")
        venue_map = {v.get("id"): v for v in out_venues
                     if isinstance(v, dict)}
        require(len(venue_map) == len(out_venues),
                "Publisher returned duplicate site IDs")
        expected_sites = {row["venue"]["id"]: row["venue"] for row in new_sites}
        # Unexpected new pins, removed or changed historical venues all fail.
        require(set(venue_map) == set(baseline_venues) | set(expected_sites)
                and all(venue_map[k] == v for k, v in baseline_venues.items())
                and all(venue_map[k] == v for k, v in expected_sites.items()),
                "Publisher site changes did not match exact signed pair")
        require(all(row["eventBinding"]["eventId"] in published
                    and published[row["eventBinding"]["eventId"]].get("venueId")
                    == row["venue"]["id"]
                    for row in new_sites),
                "Publisher emitted a site without its signed concert")
    # A numerically unchanged result is not necessarily append-only:
    # deletion of a published event plus insertion of an unrelated one can
    # balance the count. Check exact IDs *after* collecting held diagnostics.
    candidate_ids = [event["id"] for event in candidate["events"]]
    require(len(candidate_ids) == len(set(candidate_ids)),
            "Publisher returned duplicate event IDs")
    require(set(candidate_ids) == baseline_ids | incoming,
            "Publisher removed a published concert or added an unsigned one")
    if baseline_by_id is not None:
        require(all(published[event_id] == baseline_by_id[event_id]
                    for event_id in baseline_ids),
                "Publisher mutated an existing signed event during preflight")
    require(len(candidate_ids) - len(baseline_ids) == len(appended),
            "Unexpected number of publishable events")
    return {"newApprovals": len(appended),
            "publishableEvents": len(appended),
            "validatedByPublisher": True}


def select_exact_publishable_subset(previous, proposed, reference,
                                    current, today, publisher):
    """Keep independently valid signatures; NEVER trust the first partial merge.

    First run the exact publisher against the whole signed proposal to
    identify failures. If there are failures, build an append-only proposal
    that excludes ONLY the rejected new event IDs. Re-run the same publisher
    on that exact subset, with the same catalogue, reference and review day.
    No rejected record is written to the private approval file.
    """
    try:
        stats = validate_proposal(
            previous, proposed, reference, current, today, publisher)
        return stats, proposed, []
    except PublisherRejections as failure:
        additions = check_append_only(previous, proposed, today)
        failed = {r["eventId"] for r in failure.rejections}
        expected_ids = {r["event"]["id"] for r in additions}
        require(bool(failed) and failed.issubset(expected_ids),
                "Publisher rejected an unknown or previously signed event")
        accepted = [r for r in additions if r["event"]["id"] not in failed]
        if not accepted:
            # Existing fail-closed behavior for wholly invalid batches.
            raise
        safe = copy.deepcopy(proposed)
        safe["approvals"] = (
            copy.deepcopy(previous["approvals"]) + copy.deepcopy(accepted)
        )
        # A rejected concert must never carry its new map pin into the
        # selectively approved subset, even if another concert is accepted.
        accepted_ids = {r["event"]["id"] for r in accepted}
        if "venueApprovals" in proposed:
            safe["venueApprovals"] = (
                copy.deepcopy(previous["venueApprovals"]) +
                [copy.deepcopy(v) for v in _new_event_site_approvals(previous, proposed)
                 if v["eventBinding"]["eventId"] in accepted_ids]
            )
        stats = validate_proposal(
            previous, safe, reference, current, today, publisher)
        require(stats["validatedByPublisher"] is True
                and stats["newApprovals"] == len(accepted)
                and stats["publishableEvents"] == len(accepted),
                "Independent accepted subset not reproduced by publisher")
        return stats, safe, failure.rejections


def atomic_store(path, data):
    """Never leave a partially written private approvals file."""
    descriptor, filename = tempfile.mkstemp(
        prefix=".approved-preflight-", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as out:
            json.dump(data, out, indent=2, ensure_ascii=False)
            out.write("\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(filename, path)
    finally:
        if os.path.exists(filename):
            os.unlink(filename)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--catalogue", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    def load(path):
        return json.loads(path.read_text(encoding="utf-8"))
    original, proposed = load(args.before), load(args.candidate)
    reference, current = load(args.reference), load(args.catalogue)
    today = dt.datetime.now(ZoneInfo("Europe/Paris")).date()
    # Import the exact production publisher, not a simplified approximation.
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / "scripts"))
    import concerts_cloud_sync
    try:
        stats, selected, rejected = select_exact_publishable_subset(
            original, proposed, reference, current, today,
            concerts_cloud_sync.merge)
    except PublisherRejections as exc:
        # A blocked batch cannot modify approvals. Preserve detailed reasons
        # in the PRIVATE report before the public runner's catch step.
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps({
            "status": "blocked",
            "validatedByPublisher": False,
            "applied": False,
            "rejected": exc.rejections,
            "reason": str(exc)[:300],
            "recordedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        raise
    stats["proposedApprovals"] = (len(proposed["approvals"]) -
                                  len(original["approvals"]))
    stats["rejectedCount"] = len(rejected)
    stats["rejected"] = rejected
    stats["status"] = ("partially_validated" if rejected else
                       "validated" if stats["newApprovals"] else "no_changes")
    # Never claim an approval was applied before the atomic ledger write
    # succeeds. If storage fails, the caller must see an error, and the
    # private workflow records a blocked diagnostic rather than success.
    stats["applied"] = False
    if args.apply and stats["newApprovals"]:
        atomic_store(args.before, selected)
        stats["applied"] = True
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(stats, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print("Official approval preflight: checked; see private report.")


if __name__ == "__main__":
    main()
