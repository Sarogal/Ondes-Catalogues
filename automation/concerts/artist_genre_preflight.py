#!/usr/bin/env python3
"""Read-only first-party artist genre discovery for the PRIVATE Concerts intake.

Loads the committed artist tour source registry, independently fetches permitted
official artist pages, checks fresh structured MusicGroup/Person musician tags
and writes explicit, dated artist-level evidence to PRIVATE Git only.
This is NOT an approval, and DOES NOT change the publisher or candidate genre.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from collections import Counter
from pathlib import Path
from zoneinfo import ZoneInfo

import artist_genre_knowledge as knowledge
import artist_official_bio as official_bio
import discover

SCHEMA = "grossesondes.concert.artist-genre-source-preflight.v1"
SOURCE_SCHEMA = "grossesondes.concert.artist_tour_sources.v1"


def build(sources, catalogue, today, *, fetch=discover.download,
          robots=discover.robots_allow, limit=6, scan_slot=0):
    if (not isinstance(sources, dict)
            or sources.get("schema") != SOURCE_SCHEMA
            or not isinstance(sources.get("sources"), list)
            or not isinstance(catalogue, dict)
            or catalogue.get("schemaVersion") != 1
            or not isinstance(catalogue.get("artists"), list)
            or not isinstance(today, dt.date)
            or not isinstance(limit, int) or not 1 <= limit <= 12
            or scan_slot not in (0, 1, 2)):
        raise ValueError("Invalid committed artist source or catalogue")
    artists = {a.get("id") for a in catalogue["artists"]
               if isinstance(a, dict) and isinstance(a.get("id"), str)}
    candidates = []
    for source in sources["sources"]:
        if not isinstance(source, dict):
            continue
        if (source.get("sourceRole") != "artist_official"
                or source.get("enabled") is not True
                or source.get("artistId") not in artists):
            continue
        url = source.get("url")
        if not isinstance(url, str) or not url.startswith("https://"):
            continue
        candidates.append(source)
    # Fixed cohort selection rotates artist sources across daily slots.
    candidates.sort(key=lambda s: (s["artistId"], s["url"]))
    if candidates:
        offset = ((today.toordinal() * 3 + scan_slot) * limit) % len(candidates)
        selected = [candidates[(offset + i) % len(candidates)]
                    for i in range(min(limit, len(candidates)))]
    else:
        selected = []
    counters = Counter()
    evidence = []
    robots_cache = {}
    for source in selected:
        url = source["url"]
        try:
            if not robots(url, robots_cache):
                counters["robots_disallowed"] += 1
                continue
            page, actual_url = fetch(url, timeout=12, cap=900_000)
            try:
                fact = knowledge.independently_verify_artist_profile(
                    source, catalogue, page, actual_url, today)
                counters["structured_profile_verified"] += 1
            except ValueError:
                # Source-wide HTML fallback: discover ONE `Bio` link from
                # the exact official tour page, not a guessed artist URL.
                biography = official_bio.linked_official_biography(
                    page, url, actual_url)
                if biography is None:
                    raise
                if not robots(biography, robots_cache):
                    counters["biography_robots_disallowed"] += 1
                    continue
                bio_page, actual_bio = fetch(
                    biography, timeout=12, cap=600_000)
                fact = official_bio.verify_official_biography(
                    source, catalogue, bio_page, actual_bio, biography, today)
                counters["linked_biography_verified"] += 1
        except (ValueError, TypeError, KeyError):
            counters["profile_not_independently_proven"] += 1
            continue
        except Exception:
            # Do not disclose source URL or network exceptions in public logs.
            counters["network_or_source_unavailable"] += 1
            continue
        evidence.append(fact)
        counters["official_artist_genre_verified"] += 1
    return {
        "schema": SCHEMA,
        "asOf": today.isoformat(),
        "sourceManifest": "committed-public-artist-tour-sources",
        "artistSourcesEligible": len(candidates),
        "artistSourcesChecked": len(selected),
        "verifiedArtistCount": len({fact["artistId"] for fact in evidence}),
        "verifiedArtists": evidence,
        "reasonCounts": dict(sorted(counters.items())),
        "publicationAllowed": False,
        "approvalsProposed": 0,
        "note": (
            "Individual artist genres only. Event date, line-up, location "
            "and approval still need independent official proof."
        ),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", required=True, type=Path)
    parser.add_argument("--catalogue", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    read = lambda path: json.loads(path.read_text(encoding="utf-8"))
    local_now = dt.datetime.now(ZoneInfo("Europe/Paris"))
    scan_slot = 0 if local_now.hour < 12 else (1 if local_now.hour < 18 else 2)
    report = build(read(args.sources), read(args.catalogue),
                   local_now.date(), scan_slot=scan_slot)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n", encoding="utf-8")
    # NEVER print IDs, names, source URLs, or full records to public CI logs.
    print("Artist genre preflight: " + str(report["artistSourcesChecked"])
          + " pages official-source rechecked; "
          + str(report["verifiedArtistCount"])
          + " independently evidenced profiles; private diagnosis only.")


if __name__ == "__main__":
    main()
