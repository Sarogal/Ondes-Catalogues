#!/usr/bin/env python3
"""Open-world concert proposals from independently OSM-attributed venue sites.

This is NOT admission from an untrusted registry source name. A candidate
must be stable across distinct days, and the published venue's named OSM
node must freshly attribute the event's HTTPS domain to the venue.
The exact event must freshly contain a single full MusicEvent with a
matching date, named performers, individually/event-scoped relevant genres,
French location and exact address. The independent Publisher re-fetches
the OSM node and event page AGAIN before persisting any private approval.

A second event on another website is not required. Other venue/organizer
discoveries remain in research until independently tied to their real sites.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import re
import sys
from collections import Counter, defaultdict, deque
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from automation.concerts import discover
from automation.concerts import event_site_pair_recheck as pairs
from automation.concerts import official_rss_jsonld_bridge as bridge
from automation.concerts import source_admission_intake as intake
from automation.concerts import source_cross_domain_corroboration as cross
from automation.concerts import dynamic_first_party_venue_proposals as official
from automation.concerts import venue_address_osm_source as address_osm
from scripts import concert_dynamic_existing_venue as verified

SCHEMA = "grossesondes.concert.single-official-osm-proposals.v1"
MAX_CHECKS = 8  # requests per run, never a cap on sources or bands
REVIEW_BUCKETS = frozenset({"genre_tag_review", "genre_unknown"})


def require(ok, reason):
    if not ok:
        raise ValueError("OSM official concert: " + reason)


def _site(catalogue, c):
    matching = [venue for venue in catalogue["venues"]
                if isinstance(venue, dict)
                and cross.clean_venue(venue.get("name")) ==
                    cross.clean_venue(c.get("venue"))
                and intake.normalized(venue.get("city")) ==
                    intake.normalized(c.get("city"))
                and (not c.get("department") or
                     str(venue.get("department")) == str(c["department"]))
                and (verified.OSM_NODE.fullmatch(
                    str(venue.get("geoSource", "")))
                    or address_osm.eligible_address(venue))]
    require(len(matching) == 1,
            "exact published venue with independently verifiable geography required")
    return matching[0]


def _detail(c):
    url = c.get("eventDetailUrl") or c.get("sourceUrl")
    host = intake.valid_https(url)
    require(host and bridge.official_event_url(url, "https://" + host + "/"),
            "individual first-party HTTPS event page required")
    # A discovery page on a different host is not a first-party attribution.
    page = c.get("sourcePage") or c.get("sourceUrl")
    require(intake.valid_https(page) == host,
            "event and discovery page must be on the same HTTPS origin")
    return url


def eligible(registry, catalogue, today, *, diagnostics=None):
    require(isinstance(today, dt.date) and not isinstance(today, dt.datetime),
            "invalid day")
    require(isinstance(registry, dict)
            and registry.get("schema") == intake.REGISTRY_SCHEMA
            and isinstance(registry.get("items"), dict),
            "untrusted private registry")
    require(isinstance(catalogue, dict)
            and catalogue.get("schemaVersion") == 1
            and all(isinstance(catalogue.get(k), list)
                    for k in ("venues", "events", "artists")),
            "invalid public catalogue")
    published = {(e.get("officialUrl"), e.get("date"))
                 for e in catalogue["events"] if isinstance(e, dict)}
    leads = []
    # Diagnostic-only counts: never grant authority based on this report.
    def held(reason):
        if diagnostics is not None:
            diagnostics[reason] += 1

    for entry in registry["items"].values():
        if not isinstance(entry, dict) or not isinstance(
                entry.get("candidate"), dict):
            held("malformed_candidate")
            continue
        c = entry["candidate"]
        if entry.get("status") != "pending_review":
            held("not_pending_review")
            continue
        if (type(entry.get("stableObservations")) is not int
                or entry["stableObservations"] < 2):
            held("insufficient_stability")
            continue
        if (c.get("publicationAllowed") is not False
                or c.get("reviewRequired") is not True):
            held("unsafe_discovery_flags")
            continue
        if c.get("possibleExistingConcert") is not False:
            held("possible_duplicate")
            continue
        if c.get("reviewBucket") not in REVIEW_BUCKETS:
            held("other_review_bucket")
            continue
        if not intake.official_claim(c.get("source")):
            held("not_official_source_claim")
            continue
        try:
            date = dt.date.fromisoformat(c.get("date"))
        except (TypeError, ValueError):
            held("invalid_date")
            continue
        if date < today:
            held("past_event")
            continue
        try:
            url = _detail(c)
        except (TypeError, ValueError, KeyError):
            held("not_individual_first_party_url")
            continue
        try:
            venue = _site(catalogue, c)
        except (TypeError, ValueError, KeyError):
            held("no_unique_published_osm_venue")
            continue
        if (url, date.isoformat()) in published:
            held("already_published")
            continue
        leads.append((url, date.isoformat(), venue["id"], c))
    # Rotate across distinct ACTUAL published venues, not contiguous
    # alphabetical URL cohorts. An agenda with fifty undated/pop events
    # must never consume eight consecutive rechecks while a verified rock
    # show from another room is still waiting. Every candidate stays in
    # the queue and the daily/slot offset eventually rechecks them all.
    # Only network workload is bounded, not the number of venues or bands.
    # Spend the first checks on candidates with an explicit genre signal,
    # while retaining unknown-genre leads for later independent rechecks.
    # A "genre_unknown" observation is NOT a rejection; first-party event
    # or artist proof may still establish an eligible concert.
    leads.sort(key=lambda row: (
        row[3].get("reviewBucket") != "genre_tag_review",
        row[0], row[1], row[2]))
    queues = defaultdict(deque)
    for item in leads:
        queues[item[2]].append(item)
    venue_ids = sorted(queues)
    ordered = []
    while len(ordered) < len(leads):
        for venue_id in venue_ids:
            if queues[venue_id]:
                ordered.append(queues[venue_id].popleft())
    return ordered


def propose(row, catalogue, today, *, fetch=verified.safe_fetch):
    url, date, vid, candidate = row
    venue = next((v for v in catalogue["venues"] if v["id"] == vid), None)
    require(isinstance(venue, dict), "published venue disappeared")
    require(_detail(candidate) == url
            and _site(catalogue, candidate)["id"] == vid,
            "source or physical venue changed")
    cache = {}
    try:
        body = fetch(url, cache)
    except (ValueError, OSError, TimeoutError) as exc:
        raise ValueError("official_event_fetch: " + str(exc)) from exc
    require(isinstance(body, str) and 100 <= len(body) <= 400_000,
            "missing individual official event page")
    try:
        names, genres = official._individual_event(
            body, url, date, venue, accept_generic=True)
    except (ValueError, TypeError, KeyError) as exc:
        raise ValueError("official_event_content: " + str(exc)) from exc
    lead = candidate.get("leadArtist")
    require(isinstance(lead, str) and bool(lead.strip()),
            "missing named lead in original observation")
    # Discovery may list just the headliner while the official page carries
    # the complete multi-artist bill. Never assume the whole event shares
    # the same genre or that a musician is already known.
    initial = intake.normalized(lead.split(" + ")[0])
    require(initial in {intake.normalized(name) for name in names},
            "fresh bill does not contain the observed headliner")
    artists, newly_named = pairs._artists(names, catalogue)
    eid = ("go-c-" + date.replace("-", "") + "-" +
           intake.normalized(venue["city"]).replace(" ", "-")[:72] + "-" +
           intake.normalized(names[0]).replace(" ", "-")[:72])
    require(len(eid) <= 150 and len(artists) == len(names),
            "invalid or colliding artist identities")
    require(not any(
        e.get("id") == eid or e.get("officialUrl") == url or
        (e.get("date") == date and e.get("venueId") == vid and
         bool(set(e.get("artistIds") or []) & set(artists)))
        for e in catalogue["events"] if isinstance(e, dict)),
        "already published or overlapping concert")
    # Unrelated, non-musical and incomplete events must not spend an OSM
    # network budget. Geography remains mandatory BEFORE any approval.
    # The OSM claim is independent of the event page; do not read a domain
    # from a candidate as publisher authority.
    has_named_node = bool(verified.OSM_NODE.fullmatch(
        str(venue.get("geoSource", ""))))
    try:
        if has_named_node:
            feature = verified.osm_identity(venue, url, fetch, cache)
            website = None
        else:
            feature, website = verified.address_identity(
                venue, url, fetch, cache)
    except (ValueError, OSError, TimeoutError) as exc:
        raise ValueError("osm_identity: " + str(exc)) from exc
    now = today.isoformat()
    proof = {
        "url": url,
        "proofType": (verified.OSM_SINGLE_PROFILE if has_named_node
                      else verified.OSM_ADDRESS_PROFILE),
        "checkedAt": now,
        "checkedFields": (list(verified.CHECKED) if has_named_node else
                          list(verified.ADDRESS_CHECKED)),
        "officialArtistNames": names,
        "officialGenreLabels": genres,
        "namedOsmUrl": feature,
    }
    if not has_named_node:
        proof.update({
            "publishedVenueGeoSource": venue["geoSource"],
            "sourceWebsite": website,
        })
    approval = {
        "reviewDecision": "approved",
        "reviewedBy": "independent-official-verifier",
        "reviewedAt": now,
        "officialEvidence": [proof],
        "event": {
            "id": eid, "title": " + ".join(names),
            "date": date, "time": None, "artistIds": artists,
            "venueId": vid, "genres": genres,
            "status": "confirmed", "officialUrl": url,
            "sourceType": "salle",
        },
        "newArtists": newly_named,
    }
    # A second full replay here plus a third one inside approval_preflight
    # prevent discovery claims or a stale source from becoming a signature.
    try:
        verified.validate(
            approval, {v["id"]: v for v in catalogue["venues"]},
            {a["id"]: a for a in catalogue["artists"]}, today, fetch=fetch)
    except (ValueError, OSError, TimeoutError, KeyError, TypeError) as exc:
        raise ValueError("publisher_recheck: " + str(exc)) from exc
    return approval


def build(registry, catalogue, before, today, *, slot=0, limit=MAX_CHECKS,
          fetch=verified.safe_fetch):
    require(type(slot) is int and slot in (0, 1, 2)
            and type(limit) is int and 1 <= limit <= 16,
            "invalid bounded scan")
    require(isinstance(before, dict)
            and before.get("schema") == "grossesondes.concert.approvals.v1"
            and isinstance(before.get("approvals"), list),
            "invalid private approval preview")
    eligibility_rejections = Counter()
    selected = eligible(registry, catalogue, today,
                        diagnostics=eligibility_rejections)
    # Non-overlapping daily slots; rotate through ANY number of candidates.
    start = (((today - dt.date(2026, 11, 21)).days * 3 + slot) *
             limit) % len(selected) if selected else 0
    window = [selected[(start + i) % len(selected)]
              for i in range(min(limit, len(selected)))]
    output = copy.deepcopy(before)
    working = copy.deepcopy(catalogue)
    known = {row["event"]["id"] for row in output["approvals"]
             if isinstance(row, dict) and isinstance(row.get("event"), dict)}
    counts = Counter()
    reason_counts = Counter()
    checks = []
    for row in window:
        candidate = row[3]
        identifier = str(candidate.get("candidateId", ""))[:120]
        check = {"candidateId": identifier, "date": row[1],
                 "venueId": row[2]}
        try:
            approval = propose(row, working, today, fetch=fetch)
            require(approval["event"]["id"] not in known,
                    "already privately approved")
            output["approvals"].append(approval)
            known.add(approval["event"]["id"])
            working["events"].append(approval["event"])
            working["artists"].extend(
                {"id": a["id"], "name": a["name"], "aliases": []}
                for a in approval["newArtists"])
            counts["independently_verified_proposal"] += 1
            check["state"] = "independently_verified_proposal"
        except (ValueError, KeyError, TypeError, IndexError, OSError,
                TimeoutError) as exc:
            counts["held_event_or_source_not_verified"] += 1
            # Exception messages may embed hostile input. Do not expose URLs
            # or multiline payloads; private, bounded diagnostics only.
            detail = " ".join(str(exc).split()) if isinstance(
                exc, ValueError) else type(exc).__name__
            detail = re.sub(r"https?://\S+", "[url]", detail)[:180]
            reason = detail or type(exc).__name__
            check.update(state="held_event_or_source_not_verified",
                         reason=reason)
            reason_counts[reason] += 1
        checks.append(check)
    return output, {
        "schema": SCHEMA,
        "asOf": today.isoformat(),
        "scanSlot": slot,
        "eligibleQueue": len(selected),
        "examined": len(window),
        "stateCounts": dict(sorted(counts.items())),
        "eligibilityRejections": dict(sorted(eligibility_rejections.items())),
        "candidateChecks": checks,
        "rejectionReasons": dict(sorted(reason_counts.items())),
        "privateApprovalApplied": False,
        "publicationAllowed": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--catalogue", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--scan-slot", choices=(0, 1, 2), type=int, default=0)
    parser.add_argument("--limit", type=int, default=MAX_CHECKS)
    opts = parser.parse_args()
    data = lambda p: json.loads(p.read_text(encoding="utf-8"))
    proposal, summary = build(
        data(opts.registry), data(opts.catalogue),
        data(opts.candidate),
        dt.datetime.now(ZoneInfo("Europe/Paris")).date(),
        slot=opts.scan_slot, limit=opts.limit)
    opts.output.write_text(json.dumps(
        proposal, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    opts.report.write_text(json.dumps(
        summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("OSM first-party official concert proposals kept private; "
          "Publisher recheck required.")


if __name__ == "__main__":
    main()
