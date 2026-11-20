#!/usr/bin/env python3
"""National, read-only proof preview for existing venues not in the fixed verifier map.

A committed first-party source and a published venue are DISCOVERY HINTS, not
permission to approve anything. Independently re-fetch the exact official
concert page, require one dated/named/genre-qualified Event, and corroborate
the named location with a fresh independent OSM point or BAN + OSM match.
Do not create trusted venue specs, event approvals, location approvals or
publisher input. Output ONLY to the private intake.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
from collections import Counter
from pathlib import Path
from zoneinfo import ZoneInfo

import discover
import event_site_pair_recheck as site_review
import independent_named_site_geo as independent_geo
import generic_music_event
import official_rss_jsonld_bridge as bridge
import structured_first_party_preflight as structured
import triage

SCHEMA = "grossesondes.concert.dynamic-venue-evidence-preview.v1"
INTAKE = "grossesondes.concert.intake.v1"
SOURCES = "grossesondes.concert.sourcelist.v1"
APPROVALS = "grossesondes.concert.approvals.v1"


def _known_venue(candidate, source, catalogue):
    """The exact public venue already exists; ambiguity always fails closed."""
    matches = [
        v for v in catalogue.get("venues", [])
        if isinstance(v, dict)
        and triage.words(v.get("name")) == triage.words(source.get("name"))
        and triage.words(v.get("city")) == triage.words(source.get("city"))
        and str(v.get("department")) == str(source.get("department"))
        and v.get("id")
    ]
    if len(matches) != 1:
        return None
    venue = matches[0]
    if (triage.words(candidate.get("venue")) != triage.words(venue["name"])
            or triage.words(candidate.get("city")) != triage.words(venue["city"])
            or str(candidate.get("department")) != str(venue.get("department"))):
        return None
    return venue


def _select(rows, today, scan_slot, limit):
    """Disjoint slots, daily rotating windows, without an arbitrary venue list."""
    if (type(scan_slot) is not int or scan_slot not in (0, 1, 2)
            or type(limit) is not int or not 1 <= limit <= 12
            or not isinstance(today, dt.date)
            or isinstance(today, dt.datetime)):
        raise ValueError("Invalid national venue preview scan")
    rows = sorted(rows, key=lambda c: (
        str(c.get("date") or "9999-12-31"),
        str(c.get("candidateId") or ""),
        str(c.get("sourceUrl") or ""),
    ))
    if not rows:
        return []
    n = len(rows)
    window = min(n, 3 * limit)
    days = (today - dt.date(2026, 11, 20)).days
    offset = (days * window) % n
    start = scan_slot * window // 3
    end = (scan_slot + 1) * window // 3
    return [rows[(offset + i) % n] for i in range(start, end)]


def _coordinates(site, geo_fetch):
    """The official event's location must match an independent named OSM object."""
    if site.get("geoSource"):
        lat, lon = site_review._read_osm_node(
            site["geoSource"], site, geo_fetch)
        kind = "named-osm-node"
    else:
        _, lat, lon, kind = independent_geo.verify(site, geo_fetch)
    return lat, lon, kind


def _public_geo_consistent(venue, lat, lon):
    existing_lat, existing_lon = venue.get("latitude"), venue.get("longitude")
    if (type(existing_lat) not in (int, float)
            or type(existing_lon) not in (int, float)
            or not math.isfinite(existing_lat) or not math.isfinite(existing_lon)):
        return False, "public_site_coordinate_missing"
    distance = independent_geo._distance_meters(
        float(existing_lat), float(existing_lon), lat, lon)
    if distance > independent_geo.MAX_DISTANCE_METERS:
        return False, "public_site_coordinate_conflict"
    return True, "independent_official_event_and_named_geo_matched"


def build(registry, sources, catalogue, approvals, today, *,
          fetch=discover.download, robots=discover.robots_allow,
          geo_fetch=None, limit=8, scan_slot=0):
    if (not isinstance(registry, dict) or registry.get("schema") != INTAKE
            or not isinstance(registry.get("items"), dict)
            or not isinstance(sources, dict) or sources.get("schema") != SOURCES
            or not isinstance(sources.get("venues"), list)
            or not isinstance(catalogue, dict)
            or catalogue.get("schemaVersion") != 1
            or catalogue.get("mode") != "preview-public-unlisted"
            or not isinstance(catalogue.get("venues"), list)
            or not isinstance(catalogue.get("events"), list)
            or not isinstance(approvals, dict) or approvals.get("schema") != APPROVALS
            or not isinstance(approvals.get("approvals"), list)):
        raise ValueError("Untrusted venue admission preview inputs")
    # Validate even on empty input.
    _select([], today, scan_slot, limit)
    published = {(e.get("officialUrl"), e.get("date"))
                 for e in catalogue["events"] if isinstance(e, dict)}
    approved = {(a["event"].get("officialUrl"), a["event"].get("date"))
                for a in approvals["approvals"]
                if isinstance(a, dict) and a.get("reviewDecision") == "approved"
                and isinstance(a.get("event"), dict)}
    eligible = []
    for record in registry["items"].values():
        if not isinstance(record, dict):
            continue
        c = record.get("candidate")
        if (not isinstance(c, dict)
                or c.get("source") != "agenda_officiel_structuré"
                or c.get("reviewBucket") not in {"genre_unknown", "genre_tag_review"}
                or c.get("publicationAllowed") is not False
                or c.get("reviewRequired") is not True
                or c.get("possibleExistingConcert") is True
                or record.get("status", "pending_review") != "pending_review"
                or type(record.get("stableObservations")) is not int
                or record["stableObservations"] < 2):
            continue
        try:
            when = dt.date.fromisoformat(c.get("date"))
        except (ValueError, TypeError):
            continue
        if when < today or (c.get("sourceUrl"), c.get("date")) in approved | published:
            continue
        eligible.append(c)

    selected = _select(eligible, today, scan_slot, limit)
    robots_cache, counts, results = {}, Counter(), []
    for candidate in selected:
        result = {
            "candidateId": candidate.get("candidateId"),
            "status": "held",
            "reason": "not_rechecked",
            "publisherTrustGranted": False,
            "publicationAllowed": False,
        }
        source = structured.trusted_source(candidate, sources)
        venue = _known_venue(candidate, source, catalogue) if source else None
        if source is None:
            result["reason"] = "first_party_source_identity_unmatched"
        elif venue is None:
            result["reason"] = "public_venue_identity_unmatched"
        elif generic_music_event.trusted_spec(candidate) is not None:
            result["reason"] = "already_covered_by_reviewed_venue_verifier"
        else:
            url = candidate["sourceUrl"]
            result["venueId"] = venue["id"]
            try:
                if not robots(url, robots_cache):
                    result["reason"] = "official_page_robots_disallowed"
                else:
                    html, actual = fetch(url, timeout=12, cap=900_000)
                    if not bridge.official_event_url(url, source["url"]) or actual != url:
                        result["reason"] = "official_event_url_redirect_or_mismatch"
                    else:
                        # Exact event name, full date, explicit relevant genre,
                        # named performers, French postal place and full address.
                        _, names, unnamed, genres, site = site_review._official_event(
                            candidate, html, url, today)
                        result["individualOfficialEventVerified"] = True
                        if triage.words(candidate.get("leadArtist")) != triage.words(
                                " + ".join(names)):
                            result["reason"] = "official_bill_not_exactly_correlated"
                        else:
                            if geo_fetch is None:
                                def guarded_geo_fetch(geo_url, cap):
                                    return site_review.fetch_verified(
                                        geo_url, cap, robots_cache)
                                reader = guarded_geo_fetch
                            else:
                                reader = geo_fetch
                            lat, lon, kind = _coordinates(site, reader)
                            ok, why = _public_geo_consistent(venue, lat, lon)
                            result["independentNamedGeoVerified"] = True
                            result["geoPrecision"] = kind
                            result["reason"] = why
                            if ok:
                                result["status"] = "independently_correlated_private_only"
                                result["officialEventGenreProven"] = True
            except (ValueError, TypeError, KeyError):
                result["reason"] = "official_event_or_geography_unconfirmed"
            except Exception:
                # Never expose transport exceptions, private candidate data or URLs.
                result["reason"] = "external_verification_unavailable"
        counts[result["reason"]] += 1
        results.append(result)
    return {
        "schema": SCHEMA, "asOf": today.isoformat(),
        "eligible": len(eligible), "attempted": len(selected),
        "scanSlot": scan_slot,
        "officialEventEvidenceVerified": sum(
            r.get("individualOfficialEventVerified") is True for r in results),
        "independentNamedGeoVerified": sum(
            r.get("independentNamedGeoVerified") is True for r in results),
        "fullyCorrelatedPrivateOnly": sum(
            r["status"] == "independently_correlated_private_only"
            for r in results),
        "reasonCounts": dict(sorted(counts.items())),
        "results": results,
        "approvalsProposed": 0, "publisherTrustGranted": False,
        "publicationAllowed": False,
        "note": "Private diagnostic: cannot grant a source, a venue or a concert publication authority",
    }


def main():
    parser = argparse.ArgumentParser()
    for name in ("registry", "sources", "catalogue", "approvals", "out"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    read = lambda p: json.loads(p.read_text(encoding="utf-8"))
    today = dt.datetime.now(ZoneInfo("Europe/Paris"))
    slot = 0 if today.hour < 12 else 1 if today.hour < 18 else 2
    report = build(
        read(args.registry), read(args.sources), read(args.catalogue),
        read(args.approvals), today.date(), scan_slot=slot)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2)
                        + "\n", encoding="utf-8")
    print("Venue admission preflight: "
          + str(report["attempted"]) + " official pages rechecked; "
          + str(report["fullyCorrelatedPrivateOnly"])
          + " independently corroborated venue/event leads; no approvals.")


if __name__ == "__main__":
    main()
