#!/usr/bin/env python3
"""PRIVATE first-party lineup completeness audit for ALL published Concerts.

A source seen for the first time MUST be researchable, not silently omitted
because its venue is missing from published_watch.SOURCES. This is a
READ-ONLY diagnostic: never writes catalogues, artists, private approvals or
a source trust manifest. A missing support band is a named-research lead,
not authority to patch a public show without separate publisher validation.

One unique visible <main>, exact date/venue near one H1, individually named
performer in the bill. No roster or venue allowlist, no band-count cap.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import unicodedata
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo

import source_admission_intake as intake
import source_evidence_probe as probe

SCHEMA = "grossesondes.concert.published-lineup-completeness.v1"
MONTHS = {
    "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5,
    "juin": 6, "juillet": 7, "aout": 8, "septembre": 9, "octobre": 10,
    "novembre": 11, "decembre": 12,
}
MONTH = re.compile(
    r"\b([0-3]?\d)\s+(" + "|".join(MONTHS) + r")\s+(20\d{2})\b")
ISO = re.compile(r"\b(20\d{2})-([01]\d)-([0-3]\d)\b")
SLASH = re.compile(r"\b([0-3]\d)[/.]([01]\d)[/.](20\d{2})\b")
SUPPORT_MARKERS = frozenset({
    "1ere partie", "premiere partie", "1e partie", "1er partie",
    "support", "opening act", "support act", "special guests",
})
NON_ARTISTS = frozenset({
    "guest", "guest surprise", "special guest", "invites surprise",
    "invite surprise", "artiste surprise", "premiere partie surprise",
    "tba", "a confirmer", "surprise",
})


def normal(value):
    return intake.normalized(value)


class _FirstPartyMain(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.main_count = 0
        self.in_main = False
        self.skip_depth = 0
        self.heading_depth = 0
        self.parts = []
        self.headings = []
        self.heading_index = None

    def handle_starttag(self, tag, attrs):
        if tag == "main":
            self.main_count += 1
            self.in_main = True
        if not self.in_main:
            return
        if self.skip_depth:
            self.skip_depth += 1
        elif tag in ("script", "style", "noscript", "template", "nav",
                     "aside", "footer", "svg"):
            self.skip_depth = 1
        elif self.heading_depth:
            self.heading_depth += 1
        elif tag == "h1":
            self.heading_depth = 1
            self.headings.append([])
            self.heading_index = len(self.parts)

    def handle_data(self, text):
        if self.in_main and not self.skip_depth and text.strip():
            clean = " ".join(text.split())
            self.parts.append(clean)
            if self.heading_depth:
                self.headings[-1].append(clean)

    def handle_endtag(self, tag):
        if not self.in_main:
            return
        if self.skip_depth:
            self.skip_depth -= 1
        elif self.heading_depth:
            self.heading_depth -= 1
        if tag == "main":
            self.in_main = False


def _date_matches(visible):
    date_ids = set()
    text = unicodedata.normalize("NFKD", str(visible).casefold())
    text = text.encode("ascii", "ignore").decode("ascii")
    for match in MONTH.finditer(text):
        try:
            date_ids.add(dt.date(int(match[3]), MONTHS[match[2]], int(match[1])))
        except ValueError:
            pass
    for regex, indexes in ((ISO, (1, 2, 3)), (SLASH, (3, 2, 1))):
        for match in regex.finditer(text):
            try:
                date_ids.add(dt.date(*(int(match[i]) for i in indexes)))
            except ValueError:
                pass
    return date_ids


def _headline_names(value):
    if not isinstance(value, str) or not 2 <= len(value) <= 16000:
        raise ValueError("Official event title absent or excessive")
    parts = [v.strip() for v in re.split(r"\s+\+\s+", value)]
    if not parts or any(not 2 <= len(p) <= 120 for p in parts):
        raise ValueError("Ambiguous named artist bill")
    if len(set(map(normal, parts))) != len(parts):
        raise ValueError("Duplicate official artist name")
    named = [n for n in parts if normal(n) not in NON_ARTISTS]
    if not named or any(normal(x) in NON_ARTISTS for x in parts[:-1]):
        raise ValueError("Unnamed musician in the middle of a bill")
    return named


def _extra_supports(parts, first_index, main_names):
    names = list(main_names)
    for i in range(first_index + 1, min(len(parts) - 1, first_index + 120)):
        if normal(parts[i]) not in SUPPORT_MARKERS:
            continue
        candidate = parts[i + 1].strip()
        if (not 2 <= len(candidate) <= 120
                or normal(candidate) in NON_ARTISTS
                or len(candidate.split(" ")) > 15
                or re.search(r"(?i)\b(?:billetterie|sold out|concerts?|tickets?)\b",
                             candidate)):
            continue
        if normal(candidate) not in {normal(x) for x in names}:
            names.append(candidate)
    return names


def bill_from_page(html, event, venue, artists):
    if not isinstance(html, str) or not 100 <= len(html) <= probe.MAX_BYTES:
        raise ValueError("First-party HTML unreadable")
    parser = _FirstPartyMain()
    parser.feed(html)
    parser.close()
    if parser.main_count != 1 or len(parser.headings) != 1:
        raise ValueError("No unique event H1 in exactly one main")
    first = parser.heading_index
    heading = " ".join(parser.headings[0])
    names = _headline_names(heading)
    before = max(0, first - 25)
    near = " ".join(parser.parts[before:first + 25])
    dates = _date_matches(near)
    if (not isinstance(event.get("date"), str)
            or len(dates) != 1
            or next(iter(dates)).isoformat() != event["date"]):
        raise ValueError("Exact event date absent or contradictory")
    if (not isinstance(venue, dict)
            or normal(venue.get("name")) not in normal(near)):
        raise ValueError("Exact published physical venue missing from official event header")
    published_names = []
    for aid in event.get("artistIds", []):
        artist = artists.get(aid)
        if not isinstance(artist, dict) or not isinstance(artist.get("name"), str):
            raise ValueError("Published artist identity missing")
        published_names.append(artist["name"])
    names = _extra_supports(parser.parts, first, names)
    published_identities = {
        normal(alias)
        for aid in event["artistIds"]
        for alias in [artists[aid]["name"]]
            + (artists[aid].get("aliases") or [])
        if isinstance(alias, str)
    }
    if not published_identities.intersection(map(normal, names)):
        raise ValueError("Official bill not bound to a published named artist")
    missing = [name for name in names
               if normal(name) not in published_identities]
    return {"officialNames": names, "missingNamedArtists": missing,
            "publishedArtists": published_names}


def select(events, today, slot, limit):
    if (not isinstance(today, dt.date) or isinstance(today, dt.datetime)
            or type(slot) is not int or slot not in (0, 1, 2)
            or type(limit) is not int or not 1 <= limit <= 8):
        raise ValueError("Invalid nationwide read-only watch")
    candidates = [e for e in events
                  if isinstance(e, dict)
                  and e.get("status") == "confirmed"
                  and intake.valid_https(e.get("officialUrl")) is not None
                  and isinstance(e.get("artistIds"), list)
                  and e["artistIds"] and isinstance(e.get("venueId"), str)
                  and isinstance(e.get("date"), str)
                  and e["date"] >= today.isoformat()]
    candidates.sort(key=lambda x: (x["date"], x.get("id", "")))
    if not candidates:
        return [], 0
    window = min(len(candidates), 3 * limit)
    start = ((today - dt.date(2026, 11, 21)).days * window) % len(candidates)
    low, high = slot * window // 3, (slot + 1) * window // 3
    return [candidates[(start + i) % len(candidates)]
            for i in range(low, high)], len(candidates)


def build(catalogue, today, *, slot=0, limit=6, fetch=probe.safe_fetch):
    if (not isinstance(catalogue, dict)
            or catalogue.get("schemaVersion") != 1
            or not isinstance(catalogue.get("events"), list)
            or not isinstance(catalogue.get("venues"), list)
            or not isinstance(catalogue.get("artists"), list)):
        raise ValueError("Unknown public concert catalogue")
    chosen, total = select(catalogue["events"], today, slot, limit)
    venue_by_id = {v["id"]: v for v in catalogue["venues"]
                   if isinstance(v, dict) and isinstance(v.get("id"), str)}
    artist_by_id = {a["id"]: a for a in catalogue["artists"]
                    if isinstance(a, dict) and isinstance(a.get("id"), str)}
    checks, counts, cache = [], Counter(), {}
    for event in chosen:
        result = {
            "eventId": event.get("id"), "date": event.get("date"),
            "officialUrl": event.get("officialUrl"),
            "state": "held",
            "missingNamedArtists": [],
            "officialBillRechecked": False,
            "correctionAuthorized": False,
            "publicationAllowed": False,
        }
        try:
            html = fetch(event["officialUrl"], cache)
            fields = bill_from_page(
                html, event, venue_by_id.get(event["venueId"]),
                artist_by_id)
            result["officialBillRechecked"] = True
            result["missingNamedArtists"] = fields["missingNamedArtists"]
            result["state"] = ("published_lineup_incomplete"
                               if result["missingNamedArtists"]
                               else "published_lineup_matches_official_title")
        except (ValueError, TypeError, OSError, TimeoutError, KeyError,
                IndexError, RecursionError):
            result["state"] = "held_unverifiable_official_bill"
        checks.append(result)
        counts[result["state"]] += 1
    return {
        "schema": SCHEMA, "asOf": today.isoformat(),
        "futurePublishedConcertsEligible": total,
        "examinedConcerts": len(checks),
        "stateCounts": dict(sorted(counts.items())),
        "correctionAuthorized": False, "publicationAllowed": False,
        "checks": checks,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalogue", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--slot", type=int, choices=(0, 1, 2), default=0)
    parser.add_argument("--max", type=int, default=6)
    args = parser.parse_args()
    day = dt.datetime.now(ZoneInfo("Europe/Paris")).date()
    result = build(json.loads(args.catalogue.read_text(encoding="utf-8")),
                   day, slot=args.slot, limit=args.max)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(
        result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Private published Concert lineup completeness audit saved; "
          "no catalogues or approvals modified.")


if __name__ == "__main__":
    main()
