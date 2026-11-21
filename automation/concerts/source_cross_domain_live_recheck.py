#!/usr/bin/env python3
"""Fresh cross-domain *event* corroboration for unknown Concert sources.

The PRIVATE cross-source discovery report is merely a lead. Two distinct
first-party HTTPS pages must each be independently fetched, checked for
a single exact named event, and agree on date, named lead, city and named
physical venue. At least one page must demonstrate a per-event musical
genre relevant to Grosses Ondes.

No organizer/venue/artist allowlist. No source ownership claim, publisher
trust, new source authority, event approval, or catalogue mutation.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from collections import Counter
from pathlib import Path
from zoneinfo import ZoneInfo

import discover
import generic_music_event
import official_rss_jsonld_bridge as bridge
import source_admission_intake as intake
import source_cross_domain_corroboration as cross
import source_evidence_probe as probe

SCHEMA = "grossesondes.concert.cross-domain-fresh-evidence.v1"


def _venue(value):
    return cross.clean_venue(value)


def event_page_witness(html, *, url, date, lead_artist, city, venue):
    """Read a fresh, individual first-party Event; never join unrelated nodes."""
    if not isinstance(html, str) or not 100 <= len(html) <= probe.MAX_BYTES:
        raise ValueError("Unreadable individual official event page")
    events = [v for v in discover.read_ld(html)
              if isinstance(v, dict)
              and bridge._event_types(v.get("@type")) & {"Event", "MusicEvent"}]
    witnesses = []
    for raw in events:
        canonical = raw.get("url")
        if canonical is not None and canonical.rstrip("/") != url.rstrip("/"):
            continue
        if discover.iso_day(raw.get("startDate")) != date:
            continue
        status = raw.get("eventStatus", "")
        if isinstance(status, dict):
            status = status.get("@id") or status.get("name") or ""
        if not isinstance(status, str) or any(
            token in status.casefold()
            for token in ("cancel", "postpon", "reschedul", "annul", "report")
        ):
            continue
        bill = bridge.official_named_bill(raw.get("performer"))
        if not bill:
            continue
        names, unnamed = bill
        if intake.normalized(lead_artist) not in {
            intake.normalized(name) for name in names
        }:
            continue
        location = raw.get("location")
        if isinstance(location, list):
            location = location[0] if len(location) == 1 else None
        if not isinstance(location, dict):
            continue
        address = location.get("address")
        if not isinstance(address, dict):
            continue
        country = address.get("addressCountry")
        if isinstance(country, dict):
            country = country.get("name")
        if (intake.normalized(country) not in {"fr", "france"}
                or intake.normalized(address.get("addressLocality"))
                    != intake.normalized(city)
                or _venue(location.get("name")) != _venue(venue)):
            continue
        genre_labels, _ = bridge.event_genres_from_own_bill(raw)
        witnesses.append({
            "exactUrl": url, "date": date, "names": names,
            "city": city, "venue": venue, "genreLabels": genre_labels,
            "qualifyingGenre": generic_music_event.independently_relevant_genre(
                genre_labels),
        })
    if len(witnesses) != 1:
        raise ValueError("No unique exact dated/named site and band bill")
    return witnesses[0]


def select_groups(groups, today, slot, limit):
    if (not isinstance(today, dt.date) or isinstance(today, dt.datetime)
            or type(slot) is not int or slot not in (0, 1, 2)
            or type(limit) is not int or not 1 <= limit <= 3):
        raise ValueError("Invalid evidence review budget")
    eligible = sorted([
        item for item in groups
        if isinstance(item, dict)
        and item.get("reviewState")
            == "cross_domain_stable_observation_needs_live_proof"
        and isinstance(item.get("sources"), list)
        and len(item["sources"]) >= 2
        and item.get("normalizedVenue")
    ], key=lambda item: (item["date"], item["leadArtist"], item["city"]))
    if not eligible:
        return [], 0
    window = min(len(eligible), 3 * limit)
    index = (today - dt.date(2026, 11, 21)).days * window
    low = slot * window // 3
    high = (slot + 1) * window // 3
    return [eligible[(index + i) % len(eligible)]
            for i in range(low, high)], len(eligible)


def build(source_report, today, *, slot=0, limit=3, fetch=probe.safe_fetch):
    if (not isinstance(source_report, dict)
            or source_report.get("schema") != cross.SCHEMA
            or source_report.get("automaticTrustGranted") is not False
            or source_report.get("publicationAllowed") is not False
            or not isinstance(source_report.get("groups"), list)):
        raise ValueError("Invalid cross-domain candidate report")
    chosen, total = select_groups(source_report["groups"], today, slot, limit)
    results, counts, cache = [], Counter(), {}
    for row in chosen:
        result = {
            "date": row["date"], "leadArtist": row["leadArtist"],
            "city": row["city"], "venue": row["normalizedVenue"],
            "state": "held", "freshIndividualEventWitnesses": 0,
            "crossDomainEventVerified": False,
            "sourceOwnershipVerified": False,
            "publisherAuthorityGranted": False, "publicationAllowed": False,
        }
        try:
            signed = []
            for lead in row["sources"]:
                host = lead.get("host")
                url = lead.get("eventUrl")
                if (not isinstance(host, str)
                        or intake.valid_https(url) != host
                        or not isinstance(url, str)
                        or not url.split("https://" + host, 1)[1].strip("/")
                        or lead.get("stableOnDistinctDays") is not True):
                    continue
                text = fetch(url, cache)
                proof = event_page_witness(
                    text, url=url, date=row["date"],
                    lead_artist=row["leadArtist"], city=row["city"],
                    venue=row["normalizedVenue"])
                signed.append({"host": host,
                               "domainHint": lead["independentDomainHint"],
                               "url": url, "genre": proof["qualifyingGenre"]})
            # Two separate registrable-domain HINTS, each with its OWN named
            # event/date/location and one genre-qualified official Event.
            if (len({x["domainHint"] for x in signed}) >= 2
                    and any(x["genre"] for x in signed)):
                result["state"] = "fresh_cross_domain_event_confirmed"
                result["crossDomainEventVerified"] = True
            else:
                result["state"] = "needs_second_fresh_event_witness"
            result["freshIndividualEventWitnesses"] = len(signed)
        except (ValueError, TypeError, OSError, TimeoutError,
                StopIteration, KeyError):
            result["state"] = "held_unverifiable_cross_domain_event"
        counts[result["state"]] += 1
        results.append(result)
    return {
        "schema": SCHEMA, "asOf": today.isoformat(),
        "eligibleCrossDomainGroups": total,
        "examinedGroups": len(results),
        "stateCounts": dict(sorted(counts.items())),
        "sourceOwnershipVerified": False,
        "publisherAuthorityGranted": False, "publicationAllowed": False,
        "checks": results,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--scan-slot", type=int, choices=(0, 1, 2),
                        default=0)
    parser.add_argument("--max-groups", type=int, default=3)
    args = parser.parse_args()
    report = build(
        json.loads(args.input.read_text(encoding="utf-8")),
        dt.datetime.now(ZoneInfo("Europe/Paris")).date(),
        slot=args.scan_slot, limit=args.max_groups)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print("Private fresh first-party cross-domain event check complete. "
          "No authority or concert approved.")


if __name__ == "__main__":
    main()
