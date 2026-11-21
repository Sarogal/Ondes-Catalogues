#!/usr/bin/env python3
"""PRIVATE, read-only reconciliation of festival-tour nominations and concert leads.

Nothing here proves a concert, validates a venue/artist, transfers trust,
changes a source classification, or authorizes a catalogue mutation.

Sources may have *different* titles, but a same-date/same-city/same-exact-
venue lead with independently named shared artists is worth fresh rechecking.
An institutional referral missing place/artist may only provide a weak title
link, and must NOT be silently promoted to a verified stage.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
import json
from pathlib import Path
import re
import unicodedata
from urllib.parse import urlsplit

SCHEMA = "grossesondes.concert.festival-tour-stage-reconciliation.v1"
REGISTRY_SCHEMA = "grossesondes.concert.intake.v1"
MAX_ROWS = 30000


def normalized(value):
    if not isinstance(value, str):
        return ""
    s = unicodedata.normalize("NFKD", value.casefold())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(re.findall(r"[a-z0-9]+", s))


def exact_venue_identity(value):
    """Discard only an explicitly comma-separated address, not room suffixes."""
    if not isinstance(value, str):
        return ""
    return normalized(value.split(",", 1)[0])


def exact_city(value):
    return normalized(value)


def contains_artist(haystack, artist):
    candidate = normalized(artist)
    text = normalized(haystack)
    if not text or len(candidate) < 4:
        return False
    return re.search(r"(?<![a-z0-9])" + re.escape(candidate)
                     + r"(?![a-z0-9])", text) is not None


def safe_https(url):
    if not isinstance(url, str) or len(url) > 2048:
        return False
    try:
        u = urlsplit(url)
        return (u.scheme == "https" and bool(u.hostname)
                and not u.username and not u.password
                and u.port in (None, 443)
                and u.hostname not in ("localhost", "127.0.0.1")
                and "." in u.hostname)
    except (TypeError, ValueError):
        return False


def title_prefix_match(a, b):
    """Weak *nomination* only, not event identity or artist evidence."""
    p, q = normalized(a), normalized(b)
    short, long = sorted((p, q), key=len)
    return (len(short) >= 10 and len(short.split()) >= 2
            and (long == short or long.startswith(short + " ")))


def candidates(registry):
    if (not isinstance(registry, dict) or registry.get("schema") != REGISTRY_SCHEMA
            or not isinstance(registry.get("items"), dict)
            or len(registry["items"]) > MAX_ROWS):
        raise ValueError("Unknown or oversized private registry")
    result = []
    for key, record in registry["items"].items():
        if not isinstance(key, str) or not isinstance(record, dict):
            continue
        c = record.get("candidate")
        if (not isinstance(c, dict) or record.get("candidateId") != key
                or c.get("candidateId") != key
                or record.get("status") != "pending_review"
                or c.get("publicationAllowed") is not False
                or c.get("reviewRequired") is not True):
            continue
        try:
            day = date.fromisoformat(c["date"])
        except (TypeError, ValueError, KeyError):
            continue
        if not safe_https(c.get("sourceUrl")):
            continue
        result.append((key, record, c, day))
    return result


def build(registry, today):
    if type(today) is not date:
        raise ValueError("Invalid review date")
    rows = candidates(registry)
    refs, venue_leads, institutional = [], [], []
    for key, rec, c, day in rows:
        if day < today:
            continue
        if (c.get("source") == "festival_published_tour_research"
                and c.get("festivalCatalogueHintsOnly") is True
                and c.get("requiresArtistAndVenueReproof") is True
                and c.get("reviewBucket") == "tour_source_research"
                and isinstance(c.get("artistNamesFromFestivalOnly"), list)
                and 1 <= len(c["artistNamesFromFestivalOnly"]) <= 35
                and all(normalized(a) for a in c["artistNamesFromFestivalOnly"])
                and normalized(c.get("city")) and exact_venue_identity(c.get("venue"))):
            refs.append((key, rec, c))
        elif (c.get("reviewBucket") == "festival_overlap_review"
              and normalized(c.get("city")) and exact_venue_identity(c.get("venue"))):
            venue_leads.append((key, rec, c))
        elif (c.get("source") == "festival_to_concerts_handoff"
              and c.get("reviewBucket") == "tour_source_research"
              and c.get("requiresArtistAndVenueReproof") is True
              and not c.get("leadArtist") and not c.get("venue")):
            institutional.append((key, rec, c))
    result, counts = [], Counter()
    for rid, rr, ref in sorted(refs):
        matches = []
        for lid, lr, lead in venue_leads:
            if (ref["date"] != lead.get("date")
                    or exact_city(ref["city"]) != exact_city(lead["city"])
                    or exact_venue_identity(ref["venue"]) != exact_venue_identity(lead["venue"])
                    or ref.get("sourceUrl") == lead.get("sourceUrl")):
                continue
            names = sorted({a for a in ref["artistNamesFromFestivalOnly"]
                            if contains_artist(" ".join((lead.get("name") or "",
                                                       lead.get("leadArtist") or "")), a)},
                           key=normalized)
            required = min(2, len(ref["artistNamesFromFestivalOnly"]))
            if len(names) < required:
                counts["insufficient_artist_overlap"] += 1
                continue
            matches.append({
                "candidateId": lid, "sourceUrl": lead["sourceUrl"],
                "sharedArtistHintsFromFestival": names,
                "stableOnDistinctDays": lr.get("stableObservations", 0) >= 2,
                "reviewState": "venue_and_lineup_hint_needs_fresh_reproof",
            })
        # Without a city or venue, even title+date is a WEAK research link.
        weak = [(iid, ir, i) for iid, ir, i in institutional
                if (i.get("date") == ref["date"]
                    and title_prefix_match(ref.get("name"), i.get("name"))
                    and i.get("sourceUrl") != ref.get("sourceUrl"))]
        # A title alone cannot distinguish two festivals on one day; do not
        # present ambiguous title links as a stage reconciliation.
        for iid, ir, i in weak:
            same_title_ref_count = sum(
                r["date"] == ref["date"]
                and title_prefix_match(r.get("name"), i.get("name"))
                for _, _, r in refs)
            if same_title_ref_count != 1:
                counts["ambiguous_title_links"] += 1
                continue
            matches.append({
                "candidateId": iid, "sourceUrl": i["sourceUrl"],
                "stableOnDistinctDays": ir.get("stableObservations", 0) >= 2,
                "reviewState": "same_date_title_only_missing_city_venue_artists",
            })
        if matches:
            counts["archive_stages_with_research_links"] += 1
            result.append({
                "festivalReferenceSlug": ref.get("festivalReferenceSlug"),
                "archivedCandidateId": rid, "date": ref["date"],
                "city": ref["city"], "venueHint": ref["venue"],
                "archiveStableOnDistinctDays": rr.get("stableObservations", 0) >= 2,
                "possibleSameShowLeads": sorted(matches, key=lambda m: m["candidateId"]),
                "independentEventVerified": False,
                "sourceAuthorityVerified": False,
                "canRemoveFestival": False,
                "publicationAllowed": False,
            })
    return {
        "schema": SCHEMA, "asOf": today.isoformat(),
        "archiveTourStageCandidates": len(refs),
        "venueOverlapReviewCandidates": len(venue_leads),
        "institutionalTourResearchCandidates": len(institutional),
        "linkedArchiveStages": len(result), "counts": dict(sorted(counts.items())),
        "independentEventVerified": False, "automaticTrustGranted": False,
        "publicationAllowed": False, "canRemoveFestival": False,
        "matches": result,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--registry", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    from zoneinfo import ZoneInfo
    from datetime import datetime
    report = build(json.loads(a.registry.read_text(encoding="utf-8")),
                   datetime.now(ZoneInfo("Europe/Paris")).date())
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                     encoding="utf-8")
    print("Private stage reconciliation generated; no event approval or catalogue mutation.")


if __name__ == "__main__":
    main()
