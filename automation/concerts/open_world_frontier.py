#!/usr/bin/env python3
"""Open-world Concerts exploration frontier: venues <-> shows <-> artists <-> tours.

This builds a PRIVATE, deterministic research queue from public concerts and
the entire private intake. It never fetches a user-supplied URL, validates
a venue, identifies an artist or proposes publication. Downstream discovery
workers must resolve identities and independently re-fetch official sources.

No artist, venue, genre, tour URL, or historic concert is an allowlist.
Disbanded/solo/renamed artists remain distinct until explicit first-party
evidence establishes a relationship; lack of future shows is NOT closure.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

SCHEMA = "grossesondes.concert.open-world-frontier.v1"
MAX_RESEARCH_TASKS = 96


def normalized(text):
    value = unicodedata.normalize("NFKD", str(text or "")).casefold()
    return " ".join(re.findall(
        r"[a-z0-9]+", value.encode("ascii", "ignore").decode("ascii")))


def readable_name(value):
    if not isinstance(value, str) or not 2 <= len(value.strip()) <= 160:
        return None
    item = value.strip()
    key = normalized(item)
    if (not 2 <= len(key) <= 130
            or key in {"tba", "guest", "a confirmer", "unknown", "artiste inconnu"}
            or len(re.findall(r"[a-z0-9]", key)) < 2):
        return None
    return item


def identity(kind, *parts):
    raw = "|".join(normalized(p) for p in parts)
    return kind + ":" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def observed_artists(candidate):
    """Names are investigation leads, never automatic genre/identity proof."""
    named = candidate.get("officialArtistNames")
    if isinstance(named, list) and named:
        names = named
    else:
        lead = candidate.get("leadArtist")
        if not isinstance(lead, str):
            return []
        names = re.split(r"\s+\+\s+", lead)
    output, seen = [], set()
    # Preserve the complete named bill; only downstream research requests
    # have a bounded budget. No lineup-length gate or truncated lead list.
    for name in names:
        clean = readable_name(name)
        if clean and normalized(clean) not in seen:
            seen.add(normalized(clean))
            output.append(clean)
    return output


def rotating_cohort(rows, day, slot, limit):
    """Give unseen identities bounded priority, but rotate through ALL old ones."""
    if not isinstance(day, dt.date) or isinstance(day, dt.datetime):
        raise ValueError("Invalid day")
    if slot not in (0, 1, 2) or type(limit) is not int or not 1 <= limit <= MAX_RESEARCH_TASKS:
        raise ValueError("Invalid research budget")
    fresh = sorted((r for r in rows if r["firstSeen"] == "private_lead"),
                   key=lambda r: r["key"])
    known = sorted((r for r in rows if r["firstSeen"] != "private_lead"),
                   key=lambda r: r["key"])
    take_fresh = min(len(fresh), limit if not known else max(1, limit // 3))
    take_known = min(len(known), limit - take_fresh)
    tick = day.toordinal() * 3 + slot
    def select(pool, quota):
        if not pool or not quota:
            return []
        start = (tick * quota) % len(pool)
        return [pool[(start + i) % len(pool)] for i in range(quota)]
    selected = select(fresh, take_fresh) + select(known, take_known)
    if len(selected) < min(limit, len(rows)):
        seen = {x["key"] for x in selected}
        for pool in (fresh, known):
            for row in select(pool, len(pool)):
                if len(selected) >= min(limit, len(rows)):
                    break
                if row["key"] not in seen:
                    selected.append(row)
                    seen.add(row["key"])
    return selected


def build(catalogue, registry, day, *, slot=0, artist_limit=96, venue_limit=96):
    if (not isinstance(catalogue, dict) or catalogue.get("schemaVersion") != 1
            or not all(isinstance(catalogue.get(k), list)
                       for k in ("events", "artists", "venues"))
            or not isinstance(registry, dict)
            or registry.get("schema") != "grossesondes.concert.intake.v1"
            or not isinstance(registry.get("items"), dict)):
        raise ValueError("Open-world frontier requires real public catalogue and private registry")
    if not isinstance(day, dt.date) or isinstance(day, dt.datetime):
        raise ValueError("Invalid date")
    if not all(type(x) is int and 1 <= x <= MAX_RESEARCH_TASKS
               for x in (artist_limit, venue_limit)):
        raise ValueError("Invalid frontier network-independent budgets")

    artists, venues = {}, {}
    artist_by_id, venue_by_id = {}, {}
    named_artists = defaultdict(set)
    named_venues = defaultdict(set)
    for a in catalogue["artists"]:
        if not isinstance(a, dict) or not a.get("id"):
            continue
        name = readable_name(a.get("name"))
        if not name:
            continue
        key = identity("artist", name)
        a_id = a["id"]
        named_artists[normalized(name)].add(a_id)
        artist_by_id[a_id] = key
        artists.setdefault(key, {
            "key": key, "name": name, "firstSeen": "public_catalogue",
            "knownArtistId": a_id, "researchOnly": True})
    for v in catalogue["venues"]:
        if not isinstance(v, dict) or not v.get("id"):
            continue
        name, city = readable_name(v.get("name")), readable_name(v.get("city"))
        if not name or not city:
            continue
        key = identity("venue", name, city, v.get("department"))
        venues.setdefault(key, {
            "key": key, "name": name, "city": city,
            "department": str(v.get("department") or ""),
            "firstSeen": "public_catalogue",
            "knownVenueId": v["id"], "researchOnly": True})
        venue_by_id[v["id"]] = key
        named_venues[(normalized(name), normalized(city))].add(key)

    relations = set()
    # Historical published concerts contribute graph edges but NEVER certify
    # a genre for all members of a multi-artist bill.
    for e in catalogue["events"]:
        if not isinstance(e, dict):
            continue
        vkey = venue_by_id.get(e.get("venueId"))
        if not vkey:
            continue
        for artist_id in e.get("artistIds", []):
            akey = artist_by_id.get(artist_id)
            if akey:
                relations.add((akey, vkey, str(e.get("date") or ""),
                               "published_concert"))

    for entry in registry["items"].values():
        if (not isinstance(entry, dict)
                or entry.get("status") != "pending_review"
                or not isinstance(entry.get("candidate"), dict)):
            continue
        c = entry["candidate"]
        if (c.get("publicationAllowed") is not False
                or c.get("reviewRequired") is not True
                or c.get("cancellationNotice") is True):
            continue
        try:
            when = dt.date.fromisoformat(c.get("date"))
            if when < day:
                continue
        except (TypeError, ValueError):
            continue
        name, city = readable_name(c.get("venue")), readable_name(c.get("city"))
        vkey = None
        if name and city:
            matching = named_venues.get((normalized(name), normalized(city)), set())
            if len(matching) == 1:
                vkey = next(iter(matching))
            elif len(matching) == 0:
                dept = str(c.get("department") or "")
                vkey = identity("venue", name, city, dept)
                if vkey not in venues:
                    venues[vkey] = {
                        "key": vkey, "name": name, "city": city,
                        "department": dept, "knownVenueId": None,
                        "firstSeen": "private_lead", "researchOnly": True}
                    named_venues[(normalized(name), normalized(city))].add(vkey)
            # Ambiguous same-name and same-city physical sites: never infer.
        for artist in observed_artists(c):
            normalized_artist = normalized(artist)
            matching = named_artists.get(normalized_artist, set())
            akey = identity("artist", artist)
            if akey not in artists:
                artists[akey] = {
                    "key": akey, "name": artist,
                    "firstSeen": "private_lead",
                    "knownArtistId": (next(iter(matching))
                                      if len(matching) == 1 else None),
                    "ambiguousKnownIdentity": len(matching) > 1,
                    "researchOnly": True}
            if vkey:
                relations.add((akey, vkey, when.isoformat(), "private_unverified_lead"))

    # Each selected artist launches research for additional tour dates and
    # identity/genre evidence. Each selected venue launches source discovery.
    # These tasks do NOT carry candidate URLs as approved fetch targets.
    selected_artists = rotating_cohort(
        list(artists.values()), day, slot, artist_limit)
    selected_venues = rotating_cohort(
        list(venues.values()), day, slot, venue_limit)
    return {
        "schema": SCHEMA,
        "asOf": day.isoformat(),
        "scanSlot": slot,
        "publicationAllowed": False,
        "approvalsProposed": 0,
        "networkRequests": 0,
        "venueResearch": [{**v, "nextAction": "verify_official_site_and_programme"}
                          for v in selected_venues],
        "artistResearch": [{**a, "nextAction": "verify_artist_identity_genre_and_tour_dates"}
                           for a in selected_artists],
        "counts": {
            "totalArtistIdentities": len(artists),
            "unlistedArtists": sum(v["firstSeen"] == "private_lead"
                                   for v in artists.values()),
            "totalVenueIdentities": len(venues),
            "unlistedVenues": sum(v["firstSeen"] == "private_lead"
                                  for v in venues.values()),
            "artistVenueDateRelations": len(relations),
            "artistResearchSelected": len(selected_artists),
            "venueResearchSelected": len(selected_venues),
        },
        "rules": {
            "historicalClosedWorldArtistList": False,
            "historicalClosedWorldVenueList": False,
            "soloActInheritsBandIdentity": False,
            "venueClosesWhenNoShows": False,
            "candidateIsOfficialProof": False,
            "genreInheritedFromOtherArtistsOnBill": False,
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalogue", required=True, type=Path)
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--day", required=True)
    parser.add_argument("--scan-slot", type=int, default=0)
    args = parser.parse_args()
    today = dt.date.fromisoformat(args.day)
    result = build(
        json.loads(args.catalogue.read_text("utf-8")),
        json.loads(args.registry.read_text("utf-8")),
        today, slot=args.scan_slot)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", "utf-8")
    counts = result["counts"]
    # No private identities or untrusted URLs in public GitHub logs.
    print("Open-world research frontier, private-only, no publication:",
          counts["artistResearchSelected"], "artists,",
          counts["venueResearchSelected"], "venues")


if __name__ == "__main__":
    main()
