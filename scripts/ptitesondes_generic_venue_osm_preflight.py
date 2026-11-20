#!/usr/bin/env python3
"""Generic, bounded, PRIVATE-ONLY independent OSM location discovery.

No whitelist of cities, venues or event types. This is a discovery stage:
OSM matches do NOT grant official-venue attestation, audience eligibility,
publisher approval, or permission to use an unverified coordinate.
"""
import argparse
from collections import defaultdict
from datetime import date
import json
import math
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler

from proof import meters, norm
from ptitesondes_candidate_promotion import admission_failure_group, api_record

SCHEMA = "ptitesondes.generic_venue_osm_preflight.v1"
ENDPOINTS = ("https://lz4.overpass-api.de/api/interpreter",
             "https://overpass.private.coffee/api/interpreter")
MAX_BACKLOG = 4000
MAX_PER_RUN = 12
MAX_ELEMENTS = 100
MAX_BYTES = 160000
RADIUS_M = 120
MAX_SOURCE_DISTANCE_M = 65


def groups_for_review(backlog, today):
    """Group strictly eligible *but unregistered* leads by exact venue/city."""
    if not isinstance(backlog, list) or len(backlog) > MAX_BACKLOG:
        raise ValueError("invalid_private_backlog")
    groups = defaultdict(list)
    for lead in backlog:
        if admission_failure_group(lead, today) != "venue_gps_unverified":
            continue
        city, venue = lead["city"], lead["venue"]
        key = (norm(city), norm(venue))
        if not all(key):
            continue
        groups[key].append(lead)
    return [
        {"city": items[0]["city"], "venue": items[0]["venue"],
         "key": list(key), "lead_count": len(items),
         "uids": sorted({item["external_id"] for item in items})}
        for key, items in sorted(groups.items(),
                                 key=lambda p: (-len(p[1]), p[0]))
    ]


def private_rotation(groups, today, max_places=MAX_PER_RUN):
    if not isinstance(today, date) or type(max_places) is not int or not 1 <= max_places <= MAX_PER_RUN:
        raise ValueError("invalid_rotation")
    if not groups:
        return []
    # Independent of the lexical venue name; spreads the bounded workload.
    start = (today.toordinal() * max_places) % len(groups)
    return [groups[(start + i) % len(groups)]
            for i in range(min(max_places, len(groups)))]


def source_center(group, record_fetch=api_record):
    """ODS/OA metadata supplies an UNTRUSTED search centre, never GPS proof.

    Require exact UID + city + venue for up to three distinct UID records;
    any missing/contradictory sampled record blocks the private probe. More
    records may exist: this is NEVER a full registry or GPS attestation.
    """
    uids = group["uids"]
    if not uids:
        return None, "no_exact_uid_for_probe"
    centers = []
    try:
        for uid in uids[:3]:
            row = record_fetch(uid)
            if (str(row.get("uid")) != uid
                    or norm(row.get("location_city")) != group["key"][0]
                    or norm(row.get("location_name")) != group["key"][1]):
                return None, "source_identity_mismatch"
            loc = row.get("location_coordinates")
            if not isinstance(loc, dict):
                return None, "source_coordinates_missing"
            lat, lng = float(loc["lat"]), float(loc["lon"])
            if (not math.isfinite(lat) or not math.isfinite(lng)
                    or not -90 <= lat <= 90 or not -180 <= lng <= 180):
                return None, "source_coordinates_invalid"
            centers.append((lat, lng))
    except (ValueError, KeyError, TypeError, OSError):
        return None, "source_record_unavailable"
    if any(meters(centers[0], point) > MAX_SOURCE_DISTANCE_M
           for point in centers[1:]):
        return None, "source_coordinates_disagree"
    return centers[0], None


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def overpass_query(lat, lng):
    if not all(math.isfinite(x) for x in (lat, lng)):
        raise ValueError("invalid_center")
    if not -90 <= lat <= 90 or not -180 <= lng <= 180:
        raise ValueError("invalid_center")
    return ('[out:json][timeout:20];'
            'nwr(around:%d,%.7f,%.7f)["name"];out center tags %d;'
            % (RADIUS_M, lat, lng, MAX_ELEMENTS))


def fetch_overpass(center):
    """Fixed trusted endpoints, no redirects, strict response size limits."""
    query = overpass_query(*center)
    for endpoint in ENDPOINTS:
        try:
            url = endpoint + "?" + urlencode({"data": query})
            req = Request(url, headers={
                "Accept": "application/json",
                "User-Agent": "PtitesOndes-PrivateVenueEvidence/1.0 (read-only)",
            })
            with build_opener(NoRedirect()).open(req, timeout=26) as response:
                if response.status != 200 or response.geturl() != url:
                    raise ValueError("bad_provider_response")
                content = response.read(MAX_BYTES + 1)
            if not content or len(content) > MAX_BYTES:
                raise ValueError("oversized_provider_response")
            return json.loads(content)
        except (OSError, UnicodeError, ValueError):
            continue
    raise ValueError("independent_provider_unavailable")


def osm_hints(group, center, response):
    """Only exact-name OSM features near centre; NOT an approved GPS."""
    if (not isinstance(response, dict)
            or not isinstance(response.get("elements"), list)
            or response.get("remark")
            or len(response["elements"]) >= MAX_ELEMENTS):
        raise ValueError("incomplete_independent_provider_response")
    found = []
    seen = set()
    for item in response["elements"]:
        if not isinstance(item, dict):
            continue
        typ, oid, tags = item.get("type"), item.get("id"), item.get("tags")
        if (typ not in ("node", "way", "relation") or type(oid) is not int
                or oid <= 0 or not isinstance(tags, dict)
                or norm(tags.get("name")) != group["key"][1]):
            continue
        # Explicitly conflicting municipality is a hard reject. Absence is
        # still a hint but not independent municipality attestation.
        tagged_city = tags.get("addr:city") or tags.get("is_in:city")
        if tagged_city and norm(tagged_city) != group["key"][0]:
            continue
        loc = item if typ == "node" else item.get("center")
        if not isinstance(loc, dict):
            continue
        try:
            lat, lng = float(loc["lat"]), float(loc["lon"])
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        if (not math.isfinite(lat) or not math.isfinite(lng)
                or not -90 <= lat <= 90 or not -180 <= lng <= 180
                or meters(center, (lat, lng)) > MAX_SOURCE_DISTANCE_M):
            continue
        oidtext = "%s/%d" % (typ, oid)
        if oidtext in seen:
            continue
        seen.add(oidtext)
        found.append({
            "osm_object_hint": oidtext,
            "osm_url_hint": "https://www.openstreetmap.org/" + oidtext,
            "lat_unverified": lat, "lng_unverified": lng,
            "city_tag_confirmed": bool(tagged_city),
            "official_venue_verified": False,
            "gps_verified": False,
        })
    return sorted(found, key=lambda x: x["osm_object_hint"])


def inspect_group(group, record_fetch=api_record, osm_fetch=fetch_overpass,
                  ign_fetch=None, official_page_get=None,
                  approved_official_hosts=()):
    center, why = source_center(group, record_fetch)
    if why:
        return {"status": why, "osm_candidates_unverified": []}
    try:
        response = osm_fetch(center)
        evidence = osm_hints(group, center, response)
    except (ValueError, OSError, TypeError, KeyError):
        return {"status": "independent_provider_unavailable_or_incomplete",
                "osm_candidates_unverified": []}
    if len(evidence) == 1:
        status = "single_osm_hint_requires_official_venue_and_address_proof"
    elif evidence:
        status = "multiple_osm_hints_ambiguous"
    else:
        status = "no_exact_osm_venue_found"
    result = {"status": status, "osm_candidates_unverified": evidence}
    if len(evidence) == 1 and ign_fetch is not None:
        from ptitesondes_generic_venue_ign_corroboration import (
            corroborate_osm_records,
        )
        independent = corroborate_osm_records(
            group, response, center, ign_fetch)
        # A matching BAN address is geography corroboration only.
        # Never use this flag to modify VENUES or authorize publication.
        result["independent_address"] = independent
        if (independent.get("address_correlated") is True
                and official_page_get is not None):
            from ptitesondes_generic_venue_official_proof import (
                official_venue_page_proof,
            )
            try:
                page_url, html = official_page_get(group)
            except (OSError, ValueError, TypeError, KeyError, UnicodeError):
                page_url, html = None, None
            result["official_page"] = official_venue_page_proof(
                group, independent["address_candidate_private"],
                independent, page_url, html, approved_official_hosts)
    return result


def audit(backlog, today, record_fetch=api_record,
          osm_fetch=fetch_overpass, live=False, ign_fetch=None,
          official_page_get=None, approved_official_hosts=()):
    groups = groups_for_review(backlog, today)
    chosen = private_rotation(groups, today)
    checked = []
    for group in chosen:
        result = (inspect_group(group, record_fetch, osm_fetch,
                                ign_fetch, official_page_get,
                                approved_official_hosts)
                  if live else {"status": "not_scanned_preview",
                                "osm_candidates_unverified": []})
        checked.append({"city": group["city"], "venue": group["venue"],
                        "lead_count": group["lead_count"],
                        "uids": group["uids"], **result})
    address_matched = [
        x for x in checked
        if x.get("independent_address", {}).get("address_correlated") is True
    ]
    official_matched = [
        x for x in checked
        if x.get("official_page", {}).get(
            "location_evidence_complete_for_private_review") is True
    ]
    return {
        "schema": SCHEMA, "day": today.isoformat(),
        "mode": "private_osm_hints_no_publisher_access",
        "total_backlog": len(backlog),
        "unknown_venue_leads": sum(x["lead_count"] for x in groups),
        "unknown_unique_venues": len(groups),
        "selected_venues": len(checked),
        "queried_venues": len(checked) if live else 0,
        "independent_hints": sum(
            x["status"] == "single_osm_hint_requires_official_venue_and_address_proof"
            for x in checked),
        "independent_address_matches": len(address_matched),
        "leads_with_independent_address_hint": sum(
            x["lead_count"] for x in address_matched),
        "official_identity_address_matches": len(official_matched),
        "leads_with_private_official_place_evidence": sum(
            x["lead_count"] for x in official_matched),
        "verified_venue_leads": 0,
        "records": checked,
        "gps_verified": False, "official_venue_verified": False,
        "publication_ready": False, "public_writes": 0,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backlog", type=Path, required=True)
    parser.add_argument("--output-private-report", type=Path, required=True)
    parser.add_argument("--day", type=date.fromisoformat,
                        default=date.today())
    parser.add_argument("--live-probe", action="store_true")
    args = parser.parse_args()
    # Block BOTH private input and output paths inside the public checkout.
    # A future workflow must explicitly use a private runner workspace and
    # must never upload the report as a public Actions artifact.
    repository = Path(__file__).resolve().parents[1]
    if (args.output_private_report.resolve().is_relative_to(repository)
            or args.backlog.resolve().is_relative_to(repository)):
        raise ValueError("private_backlog_and_report_outside_public_repo_required")
    if args.backlog.stat().st_size > 1_000_000:
        raise ValueError("oversized_private_backlog")
    backlog = json.loads(args.backlog.read_text(encoding="utf-8"))
    if args.live_probe:
        from ptitesondes_generic_venue_ign_corroboration import fetch_ign
        report = audit(backlog, args.day, live=True, ign_fetch=fetch_ign)
    else:
        report = audit(backlog, args.day, live=False)
    args.output_private_report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    # Never log private venue names, coordinates, URLs or exception details.
    print(json.dumps({
        "unknown_venue_leads": report["unknown_venue_leads"],
        "unknown_unique_venues": report["unknown_unique_venues"],
        "selected_venues": report["selected_venues"],
        "publication_ready": False, "public_writes": 0,
    }))


if __name__ == "__main__":
    main()
