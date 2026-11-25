"""Bounded independent venue research for the published catalogue.

Rebuild the queue from the current catalogue; never approve or write an event.
Existing coordinates are deliberately not used to mint an independent proof.
"""
import argparse
from datetime import date
import json
from pathlib import Path
from proof import meters, norm
from ptitesondes_catalogue_geo_research import research_queue
from ptitesondes_dila_municipal_domains import (
    fetch_dila, municipal_site_hosts, approved_municipal_page_host,
)
from ptitesondes_unlisted_source_safe_recheck import read_unknown_https
from ptitesondes_municipal_venue_link_discovery import exact_named_venue_page
from ptitesondes_shared_venue_location_evidence import (
    mint_private_location_proof, location_from_proof,
)
from ptitesondes_generic_venue_ign_corroboration import fetch_ign
from ptitesondes_generic_venue_osm_preflight import fetch_overpass
from ptitesondes_unnumbered_official_geo_proof import (
    _exact_official_point, mint_private_unnumbered_location_proof,
)

MAX_GROUPS = 3
MAX_PAGES = 4
ERRORS = (OSError, ValueError, TypeError, KeyError, TimeoutError)


def research_group(group, today, *, directory_get=fetch_dila,
                   html_get=read_unknown_https, ign_get=fetch_ign,
                   osm_get=fetch_overpass):
    result = dict(city=group["city"], venue=group["venue"],
                  active_ids=group["active_ids"], missing_ids=group["missing_ids"],
                  status="venue_proof_not_found", publication_ready=False)
    try:
        directory = directory_get(group["city"])
    except ERRORS:
        return dict(result, status="directory_unavailable")
    hosts = municipal_site_hosts(group["city"], directory)
    if not hosts:
        return dict(result, status="municipality_not_independently_identified")
    urls = [u for u in group["source_urls"]
            if approved_municipal_page_host(u, group["city"], directory)]
    urls += ["https://" + h + "/" for h in sorted(hosts)]
    todo = list(dict.fromkeys(urls))
    seen, locations = set(), []
    osm_cache = {}
    while todo and len(seen) < MAX_PAGES:
        url = todo.pop(0)
        if url in seen or not approved_municipal_page_host(url, group["city"], directory):
            continue
        seen.add(url)
        try:
            html = html_get(url)
            proof = mint_private_location_proof(
                group, directory, url, html, ign_get, today)
            # For a place without a street number, use only its explicitly
            # named official point as a search centre. No old catalogue pin
            # or street/city centroid may substitute for that source.
            if proof is None:
                official_point = _exact_official_point(group, html)
                if official_point is not None:
                    center = tuple(official_point)
                    if center not in osm_cache:
                        osm_cache[center] = osm_get(center)
                    named_group = {**group, "key": [
                        norm(group["city"]), norm(group["venue"])]}
                    proof = mint_private_unnumbered_location_proof(
                        named_group, directory, url, html, osm_cache[center],
                        source_center=None, checked_on=today)
            loc = location_from_proof(proof, group["city"], group["venue"], today)
            if loc is not None:
                locations.append(loc)
            link = exact_named_venue_page(group["venue"], url, html,
                                          group["city"], directory)
            if link and link not in seen:
                todo.insert(0, link)
        except ERRORS:
            continue
    result["pages_examined"] = len(seen)
    if not locations:
        return result
    first = locations[0]
    if any(meters((first["lat"], first["lng"]), (p["lat"], p["lng"])) > 65
           for p in locations[1:]):
        return dict(result, status="independent_points_conflict")
    return dict(result, status="independent_venue_point_found",
                venue_point=dict(lat=first["lat"], lng=first["lng"],
                                 official=first["official"], geo_source=first["geo_source"]),
                event_identity_recheck_required=True)


def run_batch(catalogue, today, offset=0, *, researcher=research_group):
    groups = research_queue(catalogue, today)["research_groups"]
    if type(offset) is not int or offset < 0:
        raise ValueError("invalid_offset")
    start = offset % len(groups) if groups else 0
    batch = groups[start:start + MAX_GROUPS]
    results = [researcher(group, today) for group in batch]
    return dict(schema="ptitesondes.catalogue_geo_proof_research.v1",
                day=today.isoformat(), group_count=len(groups), offset=start,
                next_offset=(start + len(batch)) % len(groups) if groups else 0,
                results=results, publication_ready=False, public_writes=0)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--catalogue", type=Path, required=True)
    p.add_argument("--day", type=date.fromisoformat, required=True)
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--live", action="store_true")
    a = p.parse_args()
    if not a.live:
        p.error("Explicit --live required for network research")
    doc = json.loads(a.catalogue.read_text(encoding="utf-8"))
    print(json.dumps(run_batch(doc, a.day, a.offset), ensure_ascii=False, indent=2))
