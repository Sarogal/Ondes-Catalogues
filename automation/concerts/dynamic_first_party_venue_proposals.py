#!/usr/bin/env python3
"""Propose new Concert approvals from unlisted first-party venue origins.

Uses the private cross-domain discovery report strictly as an UNSIGNED lead.
Re-fetches every URL with DNS-pinned HTTPS and robots, verifies the independent
OSM named-site website, matches a fresh individual MusicEvent and a second
independent event page. Publisher performs the SAME checks again before any
private approval is persisted or any event is published.

Only already published physical venues with a nominative OSM node currently
qualify. Other sources remain in the nationwide research queue.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import sys
from collections import Counter
from pathlib import Path
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from automation.concerts import event_site_pair_recheck as pairs
from automation.concerts import official_rss_jsonld_bridge as bridge
from automation.concerts import discover
from automation.concerts import source_cross_domain_corroboration as cross
from automation.concerts import source_cross_domain_live_recheck as cross_live
from automation.concerts import source_admission_intake as intake
from scripts import concert_dynamic_existing_venue as dynamic

SCHEMA = "grossesondes.concert.dynamic-first-party-venue-admission.v1"
REPORT_SCHEMA = cross_live.SCHEMA
MAX_RECHECKS_PER_RUN = 8  # bounded network budget, not a domain/artist quota


def require(ok, reason):
    if not ok:
        raise ValueError("Source admission: " + reason)


def _unique_site(catalogue, row):
    matches = [
        venue for venue in catalogue["venues"]
        if isinstance(venue, dict)
        and cross.clean_venue(venue.get("name")) == row.get("venue")
        and intake.normalized(venue.get("city")) ==
            intake.normalized(row.get("city"))
    ]
    require(len(matches) == 1, "unknown or ambiguous existing physical site")
    return matches[0]


def _individual_event(html, url, when, venue, *, accept_generic=False):
    """Extract exactly one official concert, not genres from unrelated cards.

    Generic Event and HTML microdata are accepted only when a separate
    caller has authenticated the first-party source against named OSM.
    Every alternative still needs named performers and a relevant genre
    on its own individual record. Bad JSON-LD cannot be hidden by microdata.
    """
    matches = []
    for node in dynamic.individual_event_nodes(
            html, accept_generic=accept_generic):
        if not isinstance(node, dict):
            continue
        types = bridge._event_types(node.get("@type"))
        if not ("MusicEvent" in types or
                (accept_generic and "Event" in types)):
            continue
        status = str(node.get("eventStatus") or "").casefold()
        if any(part in status for part in
               ("cancel", "postpon", "resched", "report", "annul")):
            continue
        # A MusicEvent can still represent a festival. This route must never
        # misclassify a festival edition as a single concert.
        if discover.reject_listing(node.get("name")):
            continue
        canonical = node.get("url")
        if canonical is not None and canonical != url:
            continue
        if discover.iso_day(node.get("startDate")) != when:
            continue
        place = node.get("location")
        if not isinstance(place, dict) or (
                intake.normalized(place.get("name")) !=
                intake.normalized(venue["name"])):
            continue
        # Complete the missing schema.org bill only from THIS exact
        # first-party Event detail's unique H1 and per-artist genre labels.
        # Nonempty contradictory structured performers must never be replaced.
        if node.get("performer") in (None, "", []):
            recovered = pairs._visible_artist_genres_from_this_event(
                html, node.get("name"))
            if recovered is not None:
                node = {**node, "performer": recovered}
        bill = bridge.official_named_bill(node.get("performer"))
        if not bill:
            continue
        names, unnamed = bill
        genres, scope = bridge.event_genres_from_own_bill(node)
        # Venue-wide genre tags do NOT qualify. Only Event or own performers.
        if not dynamic.triage.genre_evidence({
                "classification": genres,
                "genreEvidenceScope": scope,
                "officialDetailFound": True}):
            continue
        matches.append((names, genres))
    require(len(matches) == 1, "unique first-party music event not found")
    return matches[0]


def source_proposal(row, catalogue, today, *, fetch=dynamic.safe_fetch):
    """Return one independently verified publisher-bound approval, or fail."""
    require(row.get("crossDomainEventVerified") is True
            and row.get("sourceOwnershipVerified") is False
            and row.get("publicationAllowed") is False
            and row.get("publishedAlreadyKnown") is False
            and row.get("markedPossibleDuplicate") is False,
            "not a new event research lead")
    date = row.get("date")
    require(isinstance(date, str) and
            dt.date.fromisoformat(date) >= today,
            "event date invalid or expired")
    venue = _unique_site(catalogue, row)
    witnesses = row.get("verifiedWitnesses")
    require(isinstance(witnesses, list) and len(witnesses) >= 2,
            "two fresh independently verified individual sources required")
    witnessed = []
    for item in witnesses:
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        if not isinstance(url, str) or (
                intake.valid_https(url) != item.get("host")):
            continue
        witnessed.append(url)
    require(len(set(witnessed)) >= 2, "unique witness URLs missing")
    # The OSM website attribute (verified with TLS) identifies the venue's
    # actual first-party domain. The cross-source lead never chooses authority.
    candidates = []
    cache = {}
    for url in witnessed:
        try:
            dynamic.osm_identity(venue, url, fetch, cache)
            candidates.append(url)
        except (ValueError, TypeError, KeyError, OSError, TimeoutError):
            continue
    require(len(candidates) == 1,
            "venue website identity absent or ambiguous across sources")
    official = candidates[0]
    other = [u for u in witnessed
             if cross.domain(urlsplit(u).hostname or "") !=
                cross.domain(urlsplit(official).hostname or "")]
    require(other, "second source not on independent domain")
    lead = row.get("leadArtist")
    require(isinstance(lead, str) and lead.strip(),
            "lead artist unverified")
    # Try each independent first-party event witness within the bounded
    # discovery set. One expired URL must not suppress another valid source.
    corroboration = None
    evidence = None
    for witness_url in sorted(set(other)):
        try:
            candidate = cross_live.event_page_witness(
                fetch(witness_url, cache),
                url=witness_url, date=date, lead_artist=lead,
                city=venue["city"], venue=venue["name"])
            corroboration, evidence = witness_url, candidate
            break
        except (ValueError, TypeError, KeyError, OSError, TimeoutError):
            continue
    require(corroboration is not None and evidence is not None,
            "independent named event witness no longer verifies")
    names, genres = _individual_event(
        fetch(official, cache), official, date, venue)
    require(intake.normalized(lead) in {
        intake.normalized(n) for n in names},
        "lead artist not present in first-party bill")
    require(intake.normalized(lead) in {
        intake.normalized(n) for n in evidence["names"]},
        "lead artist not independently corroborated")
    artists, fresh = pairs._artists(names, catalogue)
    event_id = (
        "go-c-" + date.replace("-", "") + "-" +
        intake.normalized(venue["city"]).replace(" ", "-")[:72] + "-" +
        intake.normalized(names[0]).replace(" ", "-")[:72]
    )
    require(len(event_id) <= 150 and len(artists) == len(names),
            "unstable official concert identifier")
    require(not any(
        e.get("id") == event_id or
        (e.get("date") == date and e.get("venueId") == venue["id"] and
         (e.get("officialUrl") == official or
          bool(set(e.get("artistIds") or []) & set(artists))))
        for e in catalogue["events"] if isinstance(e, dict)),
        "already published or conflicting concert")
    today_iso = today.isoformat()
    approval = {
        "reviewDecision": "approved",
        "reviewedBy": "independent-official-verifier",
        "reviewedAt": today_iso,
        "officialEvidence": [{
            "url": official,
            "proofType": dynamic.PROFILE,
            "checkedAt": today_iso,
            "checkedFields": list(dynamic.CHECKED),
            "officialArtistNames": names,
            "officialGenreLabels": genres,
            "namedOsmUrl": venue["geoSource"],
            "corroboratingEventUrl": corroboration,
        }],
        "event": {
            "id": event_id, "title": " + ".join(names),
            "date": date, "time": None, "artistIds": artists,
            "venueId": venue["id"], "genres": genres,
            "status": "confirmed", "officialUrl": official,
            "sourceType": "salle",
        },
        "newArtists": fresh,
    }
    dynamic.validate(
        approval,
        {v["id"]: v for v in catalogue["venues"]},
        {a["id"]: a for a in catalogue["artists"]},
        today, fetch=fetch)
    return approval


def build(report, catalogue, before, today, *, limit=MAX_RECHECKS_PER_RUN,
          fetch=dynamic.safe_fetch):
    require(isinstance(report, dict)
            and report.get("schema") == REPORT_SCHEMA
            and report.get("publicationAllowed") is False
            and report.get("sourceOwnershipVerified") is False
            and isinstance(report.get("checks"), list),
            "untrusted cross-domain research report")
    require(isinstance(catalogue, dict)
            and catalogue.get("schemaVersion") == 1
            and isinstance(catalogue.get("venues"), list)
            and isinstance(catalogue.get("artists"), list)
            and isinstance(catalogue.get("events"), list),
            "invalid public catalogue")
    require(isinstance(before, dict)
            and before.get("schema") == "grossesondes.concert.approvals.v1"
            and isinstance(before.get("approvals"), list),
            "invalid approved preview")
    require(type(limit) is int and 1 <= limit <= 16,
            "network recheck budget invalid")
    output = copy.deepcopy(before)
    working = copy.deepcopy(catalogue)
    known = {r["event"]["id"] for r in before["approvals"]
             if isinstance(r, dict) and isinstance(r.get("event"), dict)}
    counts = Counter()
    # Rotate over the WHOLE queue. A failed candidate must not monopolize
    # the first N slots indefinitely; this is only a per-run network budget.
    queue = report["checks"]
    start = today.toordinal() % len(queue) if queue else 0
    sample = [queue[(start + i) % len(queue)]
              for i in range(min(limit, len(queue)))]
    for row in sample:
        if not isinstance(row, dict):
            counts["invalid"] += 1
            continue
        try:
            approval = source_proposal(row, working, today, fetch=fetch)
            ident = approval["event"]["id"]
            require(ident not in known, "already approved")
            known.add(ident)
            output["approvals"].append(approval)
            working["events"].append(approval["event"])
            working["artists"].extend(
                {"id": art["id"], "name": art["name"], "aliases": []}
                for art in approval["newArtists"])
            counts["source_independently_verified"] += 1
            counts["publisher_proposals"] += 1
        except (ValueError, TypeError, KeyError, IndexError, OSError,
                TimeoutError):
            counts["held_needs_other_evidence"] += 1
    return output, {
        "schema": SCHEMA, "asOf": today.isoformat(),
        "examined": len(sample),
        "eligibleQueue": len(queue),
        "stateCounts": dict(sorted(counts.items())),
        "privateApprovalApplied": False, "publicationAllowed": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cross", type=Path, required=True)
    parser.add_argument("--catalogue", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=MAX_RECHECKS_PER_RUN)
    args = parser.parse_args()
    load = lambda p: json.loads(p.read_text(encoding="utf-8"))
    output, report = build(
        load(args.cross), load(args.catalogue), load(args.candidate),
        dt.datetime.now(ZoneInfo("Europe/Paris")).date(),
        limit=args.limit)
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print("Dynamic unknown-source proposals checked privately; publisher still required.")


if __name__ == "__main__":
    main()
