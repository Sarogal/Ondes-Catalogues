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

from ptitesondes_municipal_event_venue_ban import mint_municipal_event_location_proof
from ptitesondes_generic_venue_official_geocode import extract_official_address
from ptitesondes_html_independent_venue_geo import _coordinates_from_ban
from ptitesondes_delegated_source_authority import _url_host, _same_host
from ptitesondes_independent_venue_site_proof import _osm_website_host
from ptitesondes_generic_venue_osm_preflight import osm_hints

MAX_GROUPS = 3
MAX_PAGES = 4
MAX_EXTERNAL_PAGES = 2
ERRORS = (OSError, ValueError, TypeError, KeyError, TimeoutError)


def _external_location(group, url, html, ign_get, osm_get):
    """Research-only exact venue/address + BAN + named OSM website.

    A historical source URL is an untrusted discovery hint. It becomes
    attributable only via a separate matching named OSM object with the
    same website host. Neither an old catalogue pin nor a city centroid
    can supply the search centre. This returns no Publisher proof.
    """
    host = _url_host(url)
    if host is None:
        return None
    candidate = extract_official_address(group, html)
    if candidate is None:
        return None
    address = (candidate["housenumber"], candidate["street"],
               candidate["postcode"], candidate["city"], ())
    point = _coordinates_from_ban(ign_get(candidate), address)
    if point is None or (candidate.get("official_coordinates_hint") is not None
                         and meters(point, candidate["official_coordinates_hint"]) > 65):
        return None
    response = osm_get(point)
    named = {**group, "key": [norm(group["city"]), norm(group["venue"])]}
    hits = osm_hints(named, point, response)
    if len(hits) != 1:
        return None
    hit = hits[0]
    objects = [x for x in response["elements"] if isinstance(x, dict)
               and "%s/%s" % (x.get("type"), x.get("id")) == hit["osm_object_hint"]]
    if len(objects) != 1:
        return None
    tags = objects[0].get("tags")
    if not isinstance(tags, dict):
        return None
    if (tags.get("addr:country") and norm(tags["addr:country"]) not in ("fr", "france")
            or tags.get("addr:postcode") and str(tags["addr:postcode"]) != candidate["postcode"]
            or tags.get("addr:street") and norm(tags["addr:street"]) != norm(candidate["street"])
            or tags.get("addr:housenumber") and norm(tags["addr:housenumber"]) != norm(candidate["housenumber"])):
        return None
    websites = [_osm_website_host(tags[k]) for k in ("website", "contact:website") if k in tags]
    if not websites or any(x is None or not _same_host(x, host) for x in websites):
        return None
    return dict(lat=hit["lat_unverified"], lng=hit["lng_unverified"],
                official=url, geo_source="Exact venue address + IGN/BAN + named OSM website")


def research_group(group, today, *, directory_get=fetch_dila,
                   html_get=read_unknown_https, ign_get=fetch_ign,
                   osm_get=fetch_overpass):
    result = dict(city=group["city"], venue=group["venue"],
                  active_ids=group["active_ids"], missing_ids=group["missing_ids"],
                  status="venue_proof_not_found", publication_ready=False)
    try:
        directory = directory_get(group["city"])
    except ERRORS:
        directory = {}
        result["status"] = "directory_unavailable"
    hosts = municipal_site_hosts(group["city"], directory)
    if not hosts:
        if result["status"] != "directory_unavailable":
            result["status"] = "municipality_not_independently_identified"
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
            if proof is None:
                proof = mint_municipal_event_location_proof(
                    group, directory, url, html, ign_get, today, source_center=None)
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
    # Existing event source URLs are discovery hints only. Rotate a bounded
    # selection by date so larger venue histories are not permanently cut off.
    external = sorted({u for u in group["source_urls"]
                       if _url_host(u) is not None
                       and not approved_municipal_page_host(u, group["city"], directory)})
    start = today.toordinal() % len(external) if external else 0
    external = external[start:] + external[:start]
    external_examined = 0
    for url in external[:MAX_EXTERNAL_PAGES]:
        external_examined += 1
        try:
            loc = _external_location(group, url, html_get(url), ign_get, osm_get)
            if loc is not None:
                locations.append(loc)
        except ERRORS:
            continue
    result["pages_examined"] = len(seen)
    result["external_pages_examined"] = external_examined
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
