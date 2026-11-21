"""Find concert-tour stops already published in the Festivals catalogue.

This is a retrospective, purely PRIVATE research handoff: never mutate a
signed Festival row and never approve a Concert. The source is the independently
committed public festival catalogue, but its old artist/venue/source fields are
only nomination hints and MUST be re-proven by Concerts' own first-party
verification. No network requests and no event-specific allowlists.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date, datetime, timezone
from hashlib import sha256
from ipaddress import ip_address
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import triage

SCHEMA = "grossesondes.concert.discovery.v1"
SOURCE = "festival_published_tour_research"
MAX_ROWS = 600
MAX_GROUPS = 200
MAX_CANDIDATES = 75
MAX_LINEUP = 35
MIN_DISTINCT_CITIES = 2
MIN_DISTINCT_DATES = 2
TOUR_WORDS = re.compile(
    r"\b(?:etape(?:s)?\s+francais(?:e|es|es)?\s+du\s+"
    r"festival\s+itinerant|(?:tournee|tourn[eé]e)\s+de\s+concerts?|"
    r"concerts?\s+d'une\s+tournee|tournee\s+europeenne|"
    r"touring\s+festival\s+concert\s+stop)\b"
)


def _public_https_home(url):
    if not isinstance(url, str) or len(url) > 180:
        return None
    try:
        s = urlsplit(url)
        if (s.scheme != "https" or not s.hostname
                or s.username or s.password
                or s.port not in (None, 443)
                or s.path not in ("", "/") or s.query or s.fragment):
            return None
        host = s.hostname.lower()
        if (not re.fullmatch(r"[a-z0-9.-]+", host)
                or host in {"localhost", "local", "example.com", "test"}
                or host.endswith((".localhost", ".local", ".test", ".invalid"))
                or "." not in host):
            return None
        try:
            ip_address(host)
            return None  # No literal IPs in a public catalogue -> Concerts
        except ValueError:
            pass
        return "https://" + host + "/"
    except (ValueError, TypeError):
        return None


def _one_day_future(row, today):
    try:
        first = date.fromisoformat(row["startDate"])
        last = date.fromisoformat(row["endDate"])
        return first if first == last and first >= today else None
    except (KeyError, ValueError, TypeError):
        return None


def _named_lineup(row):
    names = row.get("lineup")
    if (not isinstance(names, list) or not 2 <= len(names) <= MAX_LINEUP
            or not all(isinstance(n, str) and 2 <= len(n.strip()) <= 130
                       for n in names)):
        return None
    normalized_names = tuple(triage.words(n) for n in names)
    if not all(normalized_names) or len(set(normalized_names)) != len(names):
        return None
    return tuple(sorted(normalized_names))


def _qualifies_row(row, today):
    if not isinstance(row, dict):
        return None
    mandatory = ("slug", "name", "city", "department", "venue",
                 "officialSite", "notes")
    if not all(isinstance(row.get(k), str) and
               2 <= len(row[k].strip()) <= 1200 for k in mandatory):
        return None
    if (not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", row["slug"])
            or len(row["slug"]) > 130
            or not re.fullmatch(r"[0-9]{2,3}|2A|2B", row["department"])
            or len(row["venue"]) > 300
            or len(row["name"]) > 200
            or len(row["city"]) > 160):
        return None
    when = _one_day_future(row, today)
    site = _public_https_home(row["officialSite"])
    lineup = _named_lineup(row)
    notes = triage.words(row["notes"])
    if (when is None or site is None or lineup is None
            or not TOUR_WORDS.search(notes)):
        return None
    return {
        "row": row, "day": when.isoformat(), "site": site,
        "lineup": lineup, "cityKey": triage.words(row["city"]),
    }


def find_research(catalogue, today, concert_catalogue=None):
    if (not isinstance(catalogue, dict) or catalogue.get("schema") != 1
            or not isinstance(catalogue.get("festivals"), list)
            or len(catalogue["festivals"]) > MAX_ROWS
            or not isinstance(today, date)):
        raise ValueError("Unsafe signed public festival catalogue")
    groups = defaultdict(list)
    for row in catalogue["festivals"]:
        source = _qualifies_row(row, today)
        if source is not None:
            groups[(source["site"], source["lineup"])].append(source)
    if len(groups) > MAX_GROUPS:
        raise ValueError("Too many touring research cohorts")
    selected = []
    for (site, lineup), sources in groups.items():
        if (len({source["cityKey"] for source in sources}) <
                    MIN_DISTINCT_CITIES
                or len({source["day"] for source in sources}) <
                    MIN_DISTINCT_DATES):
            # A single-town festival must not be relabelled as a concert.
            continue
        for source in sources:
            r = source["row"]
            stable_id = sha256(json.dumps({
                "slug": r["slug"], "date": source["day"], "site": site,
                "city": source["cityKey"],
            }, sort_keys=True).encode("utf-8")).hexdigest()[:24]
            # The festival catalogue is nomination evidence ONLY. It neither
            # establishes an approved concert source nor a verified concert
            # artist, place, date or genre. Preserve exact visible hints
            # while explicitly requiring fresh independent concert proof.
            row = {
                "candidateId": "concert-from-festival-" + stable_id,
                "source": SOURCE,
                "sourceUrl": site, "sourcePage": site,
                # Signed catalogue is nomination provenance, NOT the official
                # source host. Separate the two so the independent source
                # admission queue can research the real organizer domain.
                "festivalCatalogueSource": (
                    "https://sarogal.github.io/Ondes-Catalogues/"
                    "grossesondes/festivals.json"),
                "date": source["day"], "name": r["name"],
                "leadArtist": r["lineup"][0], "venue": r["venue"],
                "city": r["city"], "department": r["department"],
                "venueCatalogueId": None,
                "artistNamesFromFestivalOnly": list(r["lineup"]),
                "festivalReferenceSlug": r["slug"],
                "classification": [],
                "genreToConfirm": True,
                "officialDetailFound": False,
                "publishedFestivalTourFlag": True,
                "requiresArtistAndVenueReproof": True,
                "festivalCatalogueHintsOnly": True,
                "publicationAllowed": False, "reviewRequired": True,
            }
            classified = triage.triage(row)
            if classified["reviewBucket"] != "tour_source_research":
                raise ValueError("Tour review cannot enter publisher source")
            selected.append(classified)
    # A saturated old catalogue must be triaged, not silently truncate
    # a series of genuine touring stops and masquerade as a complete pass.
    if len(selected) > MAX_CANDIDATES:
        raise ValueError("Too many published festival-tour nominations")
    selected.sort(key=lambda row: (row["date"], row["candidateId"]))
    return {
        "schema": SCHEMA,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "publicationAllowed": False, "automaticPublication": False,
        "candidates": selected,
        "triageCounts": {"tour_source_research": len(selected)},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--festivals", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()
    data = json.loads(args.festivals.read_text(encoding="utf-8"))
    report = find_research(data, datetime.now(ZoneInfo("Europe/Paris")).date())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(
        report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Touring concert stops nominated by signed Festival catalogue=" +
          str(len(report["candidates"])) +
          "; private research only, no approvals or map mutations")


if __name__ == "__main__":
    main()
