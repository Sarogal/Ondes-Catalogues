#!/usr/bin/env python3
"""Discover new French concerts from reviewed ORGANIZERS, not known artist IDs.

A first-party event lead is NEVER an approval. Only committed organizer
authority and exact event scope may be crawled; each discovery is quarantined
for two separate days, then independently re-fetched with named artists,
event genre and physical site corroborated by the publisher.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

import discover
import event_site_microdata
import official_rss_jsonld_bridge as bridge
import organizer_source_contract as authority
import triage

SCHEMA = "grossesondes.concert.discovery.v1"


class _Links(HTMLParser):
    def __init__(self, official):
        super().__init__(convert_charrefs=True)
        self.official = official
        self.links = []
        self.seen = set()
        self.elements = 0

    def handle_starttag(self, tag, attrs):
        self.elements += 1
        if self.elements > 12000:
            raise ValueError("Organiser page has too many elements")
        if tag != "a":
            return
        uri = dict(attrs).get("href")
        if not isinstance(uri, str) or len(uri) > 2048:
            return
        url = urljoin(self.official["url"], uri)
        if authority.scoped_event_url(self.official, url) and url not in self.seen:
            self.seen.add(url)
            self.links.append(url)


def listing_urls(page, source):
    if not isinstance(page, str) or len(page) > 2_000_000:
        raise ValueError("Official organizer page too large")
    parser = _Links(source)
    parser.feed(page)
    parser.close()
    return parser.links


def choose_urls(urls, day, slot, limit):
    """All event URLs rotate over 3 daily scans without a head-only bias."""
    if (not isinstance(day, dt.date) or isinstance(day, dt.datetime)
            or type(slot) is not int or slot not in (0, 1, 2)
            or type(limit) is not int or not 1 <= limit <= 12):
        raise ValueError("Invalid organizer discovery budget")
    if not urls:
        return []
    start = (((day - dt.date(2026, 11, 20)).days * 3 + slot) * limit) % len(urls)
    return [urls[(start + i) % len(urls)]
            for i in range(min(limit, len(urls)))]


def _event_nodes(body):
    nodes = [x for x in discover.read_ld(body) if isinstance(x, dict)
             and bridge._event_types(x.get("@type")) & {"Event", "MusicEvent"}]
    # Identical to independent review: never use microdata to hide a broken
    # JSON-LD Event in the same official document.
    return nodes if nodes else event_site_microdata.read_microdata_events(body)


def _one_event(body, exact_url):
    nodes = _event_nodes(body)
    if len(nodes) == 1:
        raw = nodes[0]
        if raw.get("url") not in (None, exact_url):
            return None
        return raw
    matched = [n for n in nodes if n.get("url") == exact_url]
    return matched[0] if len(matched) == 1 else None


def candidate(raw, source, url, catalogue, today):
    """First-party Event proof must name its OWN bands and precise FR place."""
    if not isinstance(raw, dict) or not authority.scoped_event_url(source, url):
        return None
    title = raw.get("name")
    date = discover.iso_day(raw.get("startDate"))
    if not isinstance(title, str) or not 4 <= len(title.strip()) <= 220:
        return None
    if not date or date < today.isoformat():
        return None
    status = str(raw.get("eventStatus") or "").casefold()
    if any(word in status for word in ("cancel", "postpon", "resched")):
        return None
    bill = bridge.official_named_bill(raw.get("performer"))
    if not bill:
        # Unknown artists are OK; unknown IDENTITIES are not. A title
        # alone must not invent lineups from punctuation or festival cards.
        return None
    names, unnamed = bill
    place = raw.get("location")
    if not isinstance(place, dict):
        return None
    address = place.get("address")
    if not isinstance(address, dict):
        return None
    country = address.get("addressCountry")
    if isinstance(country, dict):
        country = country.get("name")
    if triage.words(country) not in {"fr", "france"}:
        return None
    name, city = place.get("name"), address.get("addressLocality")
    postal = address.get("postalCode")
    if not isinstance(name, str) or not name.strip():
        return None
    if not isinstance(city, str) or len(city.strip()) < 2:
        return None
    # The official location must have at least a precise postcode; the
    # independent rechecker still requires street, region, OSM/BAN evidence.
    if not isinstance(postal, str) or not re.fullmatch(r"\d{5}", postal):
        return None
    dept = postal[:3] if postal.startswith(("97", "98")) else postal[:2]
    if postal.startswith("20"):
        dept = str(address.get("department") or "")  # Corsica: no inference.
    genres = raw.get("genre") or []
    if isinstance(genres, str):
        genres = [genres]
    if not isinstance(genres, list):
        genres = []
    if (any(not isinstance(x, str) for x in genres)
            or len(genres) > 20):
        genres = []
    key = source["id"] + "|" + url + "|" + date
    cid = "organizer:" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
    known = {
        (triage.words(v.get("name")), triage.words(v.get("city")),
         str(v.get("department") or "")): v.get("id")
        for v in catalogue.get("venues", []) if isinstance(v, dict)
    }
    venue_id = known.get((triage.words(name), triage.words(city), dept))
    row = {
        "candidateId": cid, "source": "organizer_official_event_detail",
        "sourceRole": "organizer_official",
        "organizerSourceId": source["id"],
        "sourcePage": source["url"], "sourceUrl": url,
        "eventDetailUrl": url, "date": date,
        "name": title.strip(), "leadArtist": names[0],
        "venue": name.strip(), "city": city.strip(),
        "department": dept, "venueIdIfKnown": venue_id,
        "newVenueToReview": venue_id is None,
        "classification": genres,
        "genreEvidenceScope": "official_event_card",
        "officialDetailFound": True,
        "lineupToConfirm": True, "genreToConfirm": True,
        "venueAddressToVerify": True,
        "coordinatesToVerify": True,
        "publicationAllowed": False, "reviewRequired": True,
        "sourceConfidence": "Individual official organizer Event; independent recheck required",
    }
    if unnamed:
        row["unannouncedSupportLabel"] = unnamed
    return row


def scan(catalogue, today, *, max_detail=6, slot=0,
         sources=None, fetch=discover.download, robots=discover.robots_allow):
    sources = authority.read_sources() if sources is None else sources
    if (not isinstance(catalogue, dict)
            or catalogue.get("schemaVersion") != 1
            or not isinstance(catalogue.get("artists"), list)
            or not isinstance(catalogue.get("venues"), list)
            or not isinstance(catalogue.get("events"), list)):
        raise ValueError("Invalid published catalogue")
    choose_urls([], today, slot, max_detail)  # validate budget before HTTP.
    checks, found, cache = [], {}, {}
    for source in sources:
        if source.get("enabled") is not True:
            continue
        checked = {"organizerSourceId": source["id"],
                   "listingPageFetched": False, "candidateCount": 0,
                   "individualPagesRead": 0}
        try:
            if not robots(source["url"], cache):
                raise ValueError("robots.txt source disallows")
            page, final = fetch(source["url"], timeout=12, cap=1_200_000)
            if final != source["url"]:
                raise ValueError("Unreviewed listing redirect")
            checked["listingPageFetched"] = True
            links = listing_urls(page, source)
            checked["eventDetailLinks"] = len(links)
            for url in choose_urls(links, today, slot, max_detail):
                try:
                    if not robots(url, cache):
                        raise ValueError("robots.txt detail disallows")
                    document, final_detail = fetch(url, timeout=12, cap=1_000_000)
                    if final_detail != url:
                        raise ValueError("Unreviewed event redirect")
                    checked["individualPagesRead"] += 1
                    raw = _one_event(document, url)
                    lead = candidate(raw, source, url, catalogue, today)
                    if lead:
                        found[lead["candidateId"]] = lead
                        checked["candidateCount"] += 1
                except Exception:
                    checked["individualPagesHeld"] = (
                        checked.get("individualPagesHeld", 0) + 1)
            checked["status"] = "read"
        except Exception:
            checked["status"] = "held_source_unavailable"
        checks.append(checked)
    items, shortlist, triage_counts = triage.classify(found.values(), catalogue)
    return {
        "schema": SCHEMA,
        "publicationAllowed": False, "automaticPublication": False,
        "sourceChannel": "official_organizer_first_party",
        "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "sourceChecks": checks,
        "triageCounts": triage_counts,
        "shortlistReviewCount": len(shortlist),
        "candidates": items,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--slot", type=int, default=None)
    parser.add_argument("--max-detail", type=int, default=6)
    args = parser.parse_args()
    today = discover.today_fr()
    slot = (dt.datetime.now(dt.timezone.utc).hour // 8
            if args.slot is None else args.slot)
    try:
        catalogue = discover.json_url(discover.CATALOG)
        report = scan(catalogue, today,
                      max_detail=args.max_detail, slot=slot)
    except Exception as ex:
        parser.exit(2, "Organizer discovery: fail closed, "
                    + type(ex).__name__ + "\n")
    dest = Path(args.output)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "candidates.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    print("First-party organizers scanned:", len(report["sourceChecks"]),
          "quarantined candidate count:", len(report["candidates"]))


if __name__ == "__main__":
    main()
