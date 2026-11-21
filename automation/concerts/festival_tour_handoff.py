"""Consume Festival's PRIVATE touring stop hints inside the Concerts engine.

A referral is NEVER an approval, a network allowlist or a published festival.
The Concerts runner independently fetches a reviewed institutional index,
checks the exact event link, refetches the same-origin detail and repeats the
tour + exact date check. Artist and venue are deliberately left UNKNOWN until
the Concerts' own first-party verifier establishes both.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import sys
from zoneinfo import ZoneInfo

ENGINE = Path(__file__).resolve().parents[2] / "festival-automation"
SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
for path in (str(ENGINE), str(SCRIPTS)):
    if path not in sys.path:
        sys.path.insert(0, path)

from official_watch import get_page
from national_live_index_recheck import live_index_for_exact_link
from grossesondes_institutional_edition import trusted_source
from festival_to_concerts_handoff import (
    SCHEMA as FESTIVAL_SCHEMA, _tour_day, live_tour_card,
)
import triage

SCHEMA = "grossesondes.concert.discovery.v1"
SOURCE = "festival_to_concerts_handoff"
MAX_REFERRALS = 120
MAX_RECHECK = 5


def trusted_referral(row, today):
    if not isinstance(row, dict) or set(row) != {
            "referralId", "dossierId", "title", "dateHint", "indexUrl",
            "indexPage", "detailUrl", "classification", "reviewRequired",
            "publicationAllowed", "eventVerifiedByConcerts",
            "firstSeen", "lastSeen"}:
        return None
    if (row.get("classification") != "EXPLICIT_TOURING_CONCERT_STOP"
            or row.get("reviewRequired") is not True
            or row.get("publicationAllowed") is not False
            or row.get("eventVerifiedByConcerts") is not False
            or not isinstance(row.get("dossierId"), str)
            or not re.fullmatch(r"national-[a-z0-9-]{8,120}",
                                row["dossierId"])):
        return None
    spec = trusted_source(
        row["indexUrl"], row["indexPage"],
        row["detailUrl"], row["title"], today)
    if spec is None:
        return None
    try:
        first = date.fromisoformat(row["firstSeen"])
        last = date.fromisoformat(row["lastSeen"])
        claimed = date.fromisoformat(row["dateHint"])
        current = date.fromisoformat(today)
        if (not first <= last <= current
                or current-last > timedelta(days=45)
                or claimed < current
                or claimed.year != spec["year"]):
            return None
    except (TypeError, ValueError):
        return None
    raw = json.dumps({
        "index": spec["index_url"], "detail": spec["url"],
        "title": spec["title"], "day": claimed.isoformat()
    }, sort_keys=True).encode("utf-8")
    expected = "festival-tour-" + sha256(raw).hexdigest()[:24]
    return spec if row["referralId"] == expected else None


def reverify(input_doc, today, fetch=get_page, limit=MAX_RECHECK):
    if (not isinstance(input_doc, dict) or
            input_doc.get("schema") != FESTIVAL_SCHEMA
            or input_doc.get("publication_authorized") is not False
            or input_doc.get("review_only") is not True
            or not isinstance(input_doc.get("referrals"), list)
            or len(input_doc["referrals"]) > MAX_REFERRALS
            or type(limit) is not int or not 0 <= limit <= MAX_RECHECK):
        raise ValueError("Private Festival referral inbox is not trustworthy")
    date.fromisoformat(today)
    by_id, eligible = set(), []
    for row in input_doc["referrals"]:
        if not isinstance(row, dict) or row.get("referralId") in by_id:
            raise ValueError("Duplicate or malformed festival referral")
        by_id.add(row["referralId"])
        spec = trusted_referral(row, today)
        if spec is not None:
            eligible.append((row, spec))
    # Rotate bounded quota, prioritize new independently typed tour leads.
    eligible.sort(key=lambda x: (x[0]["lastSeen"], x[0]["referralId"]),
                  reverse=True)
    if eligible and limit:
        offset = (date.fromisoformat(today).toordinal() * limit) % len(eligible)
        selected = [eligible[(offset+i) % len(eligible)]
                    for i in range(min(limit, len(eligible)))]
    else:
        selected = []
    candidates = []
    for row, spec in selected:
        try:
            index_html = live_tour_card(spec, today, fetch)
            if index_html is None:
                continue
            html = fetch(spec["url"])
            verified_day = _tour_day(
                html, spec, today, index_html=index_html)
            if verified_day != row["dateHint"]:
                continue
        except (OSError, ValueError, TypeError, UnicodeError, KeyError):
            continue
        # A festival-sounding TOUR TITLE is not an artist. Never invent the
        # named band, support act, date venue, municipality, or official genre.
        proposed = {
            "candidateId": "concert-from-" + row["referralId"],
            "source": SOURCE, "sourceUrl": spec["url"],
            "sourcePage": spec["index_page"],
            "date": verified_day, "name": spec["title"],
            "leadArtist": None, "venue": None, "city": None,
            "department": None, "venueCatalogueId": None,
            "classification": [], "genreToConfirm": True,
            "officialDetailFound": True,
            "touringEventRechecked": True,
            "requiresArtistAndVenueReproof": True,
            "publicationAllowed": False, "reviewRequired": True,
        }
        classified = triage.triage(proposed)
        if classified["reviewBucket"] != "tour_source_research":
            raise ValueError("Concert research triage refused safe tour handoff")
        candidates.append(classified)
    return {
        "schema": SCHEMA,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "publicationAllowed": False, "automaticPublication": False,
        "candidates": candidates,
        "triageCounts": {"tour_source_research": len(candidates)},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--limit", type=int, default=MAX_RECHECK)
    args = ap.parse_args()
    now = datetime.now(ZoneInfo("Europe/Paris")).date().isoformat()
    if args.input.is_file():
        inbox = json.loads(args.input.read_text(encoding="utf-8"))
    else:
        inbox = {
            "schema": FESTIVAL_SCHEMA, "review_only": True,
            "publication_authorized": False, "referrals": [],
        }
    result = reverify(inbox, now, limit=args.limit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(
        result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print("Festival tour handoff independently rechecked by Concerts: " +
          str(len(result["candidates"])) +
          " private research candidates; no approvals/publication")


if __name__ == "__main__":
    main()
