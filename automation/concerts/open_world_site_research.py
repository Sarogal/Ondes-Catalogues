#!/usr/bin/env python3
"""Bounded OPEN-WORLD research of previously unknown venue and artist websites.

Research-only: private leads provide navigation hints, NEVER proof that a host
belongs to a venue/artist. DNS-pinned TLS, robots and no redirects are enforced
by source_evidence_probe. Any resulting concert remains quarantined and still
needs an independent official-source and geographic Publisher verification.
No site/artist-specific selectors, no manual source allowlist, no publication.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import artist_tour_discovery as tours
import discover
import generic_visible_bill
import official_rss_jsonld_bridge as bridge
import open_world_frontier as frontier
import source_admission_intake as intake
import source_evidence_probe as probe
import triage
import venue_osm_self_discovery as osm

SCHEMA = "grossesondes.concert.discovery.v1"
MAX_SITES = 5
MAX_DETAILS = 4
# A syndicated event directory cannot prove that its domain belongs to the
# named room or artist. Dedicated OpenAgenda discovery already handles it.
SHARED_EVENT_PLATFORMS = frozenset({
    "openagenda.com", "www.openagenda.com", "ticketmaster.fr",
    "www.ticketmaster.fr", "ticketmaster.com", "www.ticketmaster.com",
})


def safe_page(value):
    host = intake.valid_https(value)
    if not host or host in SHARED_EVENT_PLATFORMS:
        return None
    try:
        probe.checked_uri(value, host)
    except (ValueError, TypeError):
        return None
    return value


def select_sources(frontier_report, registry, day, *, slot=0, limit=3):
    """Choose claims overlapping the rotating open-world frontier; no trust."""
    if (not isinstance(frontier_report, dict)
            or frontier_report.get("schema") != frontier.SCHEMA
            or frontier_report.get("publicationAllowed") is not False
            or not isinstance(frontier_report.get("venueResearch"), list)
            or not isinstance(frontier_report.get("artistResearch"), list)
            or not isinstance(registry, dict)
            or registry.get("schema") != "grossesondes.concert.intake.v1"
            or not isinstance(registry.get("items"), dict)
            or not isinstance(day, dt.date) or isinstance(day, dt.datetime)
            or slot not in (0, 1, 2) or type(limit) is not int
            or not 1 <= limit <= MAX_SITES):
        raise ValueError("Invalid open-world site-research inputs")
    venues = {
        (frontier.normalized(row.get("name")),
         frontier.normalized(row.get("city"))): row
        for row in frontier_report["venueResearch"]
        if isinstance(row, dict) and row.get("researchOnly") is True
    }
    artists = {
        frontier.normalized(row.get("name")): row
        for row in frontier_report["artistResearch"]
        if isinstance(row, dict) and row.get("researchOnly") is True
    }
    seeds = {}
    for record in registry["items"].values():
        if (not isinstance(record, dict)
                or record.get("status") != "pending_review"
                or not isinstance(record.get("candidate"), dict)):
            continue
        lead = record["candidate"]
        if (lead.get("publicationAllowed") is not False
                or lead.get("reviewRequired") is not True
                or lead.get("cancellationNotice") is True):
            continue
        try:
            if dt.date.fromisoformat(lead.get("date")) < day:
                continue
        except (ValueError, TypeError):
            continue
        source = lead.get("source")
        if not isinstance(source, str):
            continue
        # An artist's first-party MusicEvent may name a previously unseen
        # room and supply its own URL. This is ONLY an unverified website hint.
        # The NEXT cycle must visit the room separately, not infer ownership
        # from the artist's tour page or whitelist.
        if source == "open_world_artist_tour_research":
            hint = safe_page(lead.get("venueWebsiteHint"))
            room = venues.get((frontier.normalized(lead.get("venue")),
                               frontier.normalized(lead.get("city"))))
            if hint and room:
                hint_host = urlsplit(hint).hostname
                key = ("venue", room["key"], hint_host)
                seeds.setdefault(key, {
                    "kind": "venue", "identity": room, "url": hint,
                    "host": hint_host, "claimedOfficial": False,
                })
            continue
        url = safe_page(lead.get("sourcePage")) or safe_page(lead.get("sourceUrl"))
        if not url:
            continue
        host = urlsplit(url).hostname
        if source.startswith("agenda_officiel_"):
            row = venues.get((frontier.normalized(lead.get("venue")),
                              frontier.normalized(lead.get("city"))))
            if row:
                key = ("venue", row["key"], host)
                seeds.setdefault(key, {
                    "kind": "venue", "identity": row, "url": url,
                    "host": host, "claimedOfficial": False,
                })
        elif source.startswith(("artist_official_", "promoter_official_")):
            for name in frontier.observed_artists(lead):
                row = artists.get(frontier.normalized(name))
                if row:
                    key = ("artist", row["key"], host)
                    seeds.setdefault(key, {
                        "kind": "artist", "identity": row, "url": url,
                        "host": host, "claimedOfficial": False,
                    })
    ordered = sorted(seeds.values(),
                     key=lambda x: (x["kind"], x["identity"]["key"], x["host"]))
    if not ordered:
        return []
    offset = ((day.toordinal() * 3 + slot) * limit) % len(ordered)
    return [ordered[(offset + j) % len(ordered)]
            for j in range(min(limit, len(ordered)))]


def venue_leads(body, url, seed, catalogue, today):
    room = seed["identity"]
    source = {
        "id": room["key"], "name": room["name"],
        "city": room["city"], "department": room.get("department", ""),
        "url": url,
    }
    # Shared generic first-party structured reader works for ANY venue.
    structured = osm.event_leads(body, url, dict(source), catalogue, today)
    if structured:
        for lead in structured:
            # Source room names can repeat in multiple cities. Never reuse a
            # legacy room-name-only candidate ID for an unlisted site.
            fingerprint = "|".join((room["key"], str(lead.get("date")),
                                    str(lead.get("name")), url))
            lead["candidateId"] = "open-world-structured:" + hashlib.sha256(
                fingerprint.encode("utf-8")).hexdigest()[:24]
            lead["venueCatalogueId"] = None
            lead["sourceAuthorityVerified"] = False
            lead["openWorldSourceUnverified"] = True
            lead["publicationAllowed"] = False
            lead["reviewRequired"] = True
        return structured

    # Same generic visible-bill parser used by already known rooms, but no
    # trusted-site manifest. It creates a RESEARCH lead, not official proof.
    visible = generic_visible_bill._visible_event(body, source, today)
    if not visible:
        return []
    fingerprint = "|".join((room["key"], visible["date"], visible["title"]))
    cid = "open-world-visible:" + hashlib.sha256(
        fingerprint.encode("utf-8")).hexdigest()[:24]
    return [{
        "candidateId": cid, "source": "open_world_visible_research",
        "sourceUrl": url, "sourcePage": url,
        "name": visible["title"], "date": visible["date"],
        "leadArtist": " + ".join(visible["names"]),
        "officialArtistNames": list(visible["names"]),
        "classification": visible["genres"], "venue": room["name"],
        "city": room["city"], "department": room.get("department", ""),
        "genreToConfirm": True, "sourceAuthorityVerified": False,
        "openWorldSourceUnverified": True,
        "publicationAllowed": False, "reviewRequired": True,
    }]


def artist_leads(body, url, seed, catalogue, today):
    artist = seed["identity"]
    source = {
        "url": url, "artistId": artist["key"],
        "sourceRole": "artist_official",
    }
    found = []
    for raw in discover.read_ld(body):
        if (not isinstance(raw, dict)
                or "MusicEvent" not in bridge._event_types(raw.get("@type"))):
            continue
        row = tours.event_candidate(raw, source, artist["name"], catalogue, today)
        if row is None:
            continue
        # The Place.url field is a next-cycle NAVIGATION HINT, not evidence
        # of venue domain ownership. Require a named French place already
        # validated by event_candidate; exclude shared ticketing domains and
        # the artist's own tour domain. Follow-up fetches remain TLS pinned.
        place = raw.get("location")
        if isinstance(place, list):
            place = next((v for v in place if isinstance(v, dict)), None)
        if isinstance(place, dict):
            room_hint = safe_page(place.get("url"))
            if (room_hint and urlsplit(room_hint).hostname
                    != urlsplit(url).hostname):
                row["venueWebsiteHint"] = room_hint
        # A registry lead is NEVER allowed to authenticate an artist domain.
        row.update({
            "source": "open_world_artist_tour_research",
            "sourceAuthorityVerified": False,
            "openWorldSourceUnverified": True,
            "publicationAllowed": False, "reviewRequired": True,
        })
        found.append(row)
    return found


def scan(catalogue, registry, frontier_report, day, *, slot=0,
         max_sites=3, max_details=3, fetch=probe.safe_fetch):
    if (not isinstance(catalogue, dict)
            or catalogue.get("schemaVersion") != 1
            or not all(isinstance(catalogue.get(k), list)
                       for k in ("events", "venues", "artists"))
            or type(max_details) is not int
            or not 1 <= max_details <= MAX_DETAILS):
        raise ValueError("Invalid catalogue or detail budget")
    seeds = select_sources(frontier_report, registry, day,
                           slot=slot, limit=max_sites)
    candidates = {}
    counters = Counter()
    for seed in seeds:
        cache, seen = {}, set()
        queue = [seed["url"]]
        # Per-site budget counts ALL pages, not only successful detail pages.
        while queue and len(seen) < max_details + 1:
            url = queue.pop(0)
            if (url in seen or safe_page(url) is None
                    or urlsplit(url).hostname != seed["host"]):
                continue
            seen.add(url)
            counters["pagesAttempted"] += 1
            try:
                body = fetch(url, cache)
                if not isinstance(body, str) or len(body) > probe.MAX_BYTES:
                    raise ValueError("Invalid or oversized page")
                rows = (venue_leads(body, url, seed, catalogue, day)
                        if seed["kind"] == "venue" else
                        artist_leads(body, url, seed, catalogue, day))
                for row in rows:
                    candidates.setdefault(row["candidateId"], row)
                counters["pagesRead"] += 1
                if len(seen) >= max_details + 1:
                    continue
                # Explore one extra navigation depth on the exact same
                # DNS-audited origin. No URL from the content is trusted.
                links = osm.detail_links(body, url, day, slot, max_details)
                for link in links:
                    if (link not in seen and link not in queue
                            and safe_page(link) is not None
                            and urlsplit(link).hostname == seed["host"]):
                        queue.append(link)
            except (ValueError, TypeError, KeyError, OSError, TimeoutError):
                counters["pagesHeld"] += 1
    classified, shortlist, counts = triage.classify(
        list(candidates.values()), catalogue)
    return {
        "schema": SCHEMA,
        "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "publicationAllowed": False, "automaticPublication": False,
        "sourceChannel": "open_world_research",
        "sitesConsidered": len(seeds), "sourceChecks": dict(counters),
        "triageCounts": counts, "shortlistReviewCount": len(shortlist),
        "candidates": classified,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--catalogue", required=True, type=Path)
    p.add_argument("--registry", required=True, type=Path)
    p.add_argument("--frontier", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--day", default=None)
    p.add_argument("--scan-slot", type=int, choices=(0, 1, 2), default=0)
    p.add_argument("--max-sites", type=int, default=3)
    p.add_argument("--max-details", type=int, default=3)
    args = p.parse_args()
    today = (dt.date.fromisoformat(args.day) if args.day else
             dt.datetime.now(ZoneInfo("Europe/Paris")).date())
    report = scan(
        json.loads(args.catalogue.read_text("utf-8")),
        json.loads(args.registry.read_text("utf-8")),
        json.loads(args.frontier.read_text("utf-8")),
        today, slot=args.scan_slot, max_sites=args.max_sites,
        max_details=args.max_details)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    # NEVER log private room names, artist identities or candidate URLs.
    print("Open-world website research complete; candidates quarantined.",
          len(report["candidates"]), "research leads only.")


if __name__ == "__main__":
    main()
