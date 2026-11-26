"""Bounded independent venue research for the published catalogue.

Rebuild the queue from the current catalogue; never approve or write an event.
Existing coordinates are deliberately not used to mint an independent proof.
"""
import argparse
from datetime import date
import json
import re
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import Request, build_opener
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
    _visible_unnumbered_official_address,
)

from ptitesondes_municipal_event_venue_ban import mint_municipal_event_location_proof
from ptitesondes_generic_venue_official_geocode import extract_official_address
from ptitesondes_html_independent_venue_geo import _coordinates_from_ban
from ptitesondes_delegated_source_authority import _url_host, _same_host
from ptitesondes_independent_venue_site_proof import _osm_website_host
from ptitesondes_generic_venue_osm_preflight import (
    osm_hints, ENDPOINTS, NoRedirect, MAX_ELEMENTS, MAX_BYTES,
)
from ptitesondes_shared_venue_location_evidence import _coordinates
from ptitesondes_dynamic_municipal_source_links import _safe_url
from ptitesondes_generic_venue_ign_corroboration import POSTCODE

COMMUNE_API = "https://geo.api.gouv.fr/communes"
INSEE_CODE = re.compile(r"(?:[0-9]{5}|2[AB][0-9]{3})")
MAX_COMMUNE_BYTES = 100_000
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
    host = _url_host(url) or _osm_website_host(url)
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


def _commune_code(group, directory):
    """Use one independently authenticated DILA municipality, never old GPS."""
    if not municipal_site_hosts(group["city"], directory):
        return None
    rows = directory.get("results", [])
    codes = {str(row.get("code_insee_commune", "")) for row in rows
             if isinstance(row, dict)
             and norm(row.get("nom")) == norm("Mairie - " + group["city"])}
    if len(codes) != 1:
        return None
    code = next(iter(codes))
    return code if INSEE_CODE.fullmatch(code) else None


def _department_code(group):
    value = group.get("department")
    if not isinstance(value, str):
        return None
    m = re.search(r"\(([0-9]{2}|97[1-6]|2[AB])\)$", value)
    return m.group(1) if m else None


def fetch_commune(group):
    """Fixed national administrative API, not a municipality-site trust grant."""
    city, dep = group.get("city"), _department_code(group)
    if (not isinstance(city, str) or not 2 <= len(city) <= 120
            or not norm(city) or any(ord(c) < 32 for c in city) or dep is None):
        return []
    url = COMMUNE_API + "?" + urlencode({
        "nom": city, "codeDepartement": dep, "fields": "nom,code,codeDepartement"})
    req = Request(url, headers={"Accept": "application/json",
                               "User-Agent": "PtitesOndesAdministrativeGeo/1.0"})
    with build_opener(NoRedirect()).open(req, timeout=15) as response:
        if response.status != 200 or response.geturl() != url:
            raise ValueError("invalid_administrative_geo_response")
        raw = response.read(MAX_COMMUNE_BYTES + 1)
    if not raw or len(raw) > MAX_COMMUNE_BYTES:
        raise ValueError("oversized_administrative_geo_response")
    return json.loads(raw)


def fetch_administrative_unit(code):
    """Read the official parent relationship for one exact INSEE identifier."""
    if not isinstance(code, str) or not INSEE_CODE.fullmatch(code):
        raise ValueError("invalid_administrative_unit")
    url = COMMUNE_API + "/" + code + "?" + urlencode({
        "fields": "nom,code,codeDepartement,codeParent"})
    req = Request(url, headers={"Accept": "application/json",
                               "User-Agent": "PtitesOndesAdministrativeGeo/1.0"})
    with build_opener(NoRedirect()).open(req, timeout=15) as response:
        if response.status != 200 or response.geturl() != url:
            raise ValueError("invalid_administrative_unit_response")
        raw = response.read(MAX_COMMUNE_BYTES + 1)
    if not raw or len(raw) > MAX_COMMUNE_BYTES:
        raise ValueError("oversized_administrative_unit_response")
    return json.loads(raw)


def administrative_unit_matches(group, municipality_code, unit_code, unit_get):
    """Exact code, or independently documented direct child of the commune.

    Never infer parenthood by common prefixes, postal codes or a city list.
    """
    dep = _department_code(group)
    if (dep is None or not isinstance(municipality_code, str)
            or not isinstance(unit_code, str)
            or not INSEE_CODE.fullmatch(municipality_code)
            or not INSEE_CODE.fullmatch(unit_code)
            or not municipality_code.startswith(dep) or not unit_code.startswith(dep)):
        return False
    if municipality_code == unit_code:
        return True
    unit = unit_get(unit_code)
    return (isinstance(unit, dict) and unit.get("code") == unit_code
            and unit.get("codeDepartement") == dep
            and unit.get("codeParent") == municipality_code
            and isinstance(unit.get("nom"), str) and bool(unit["nom"].strip()))


def administrative_commune_code(group, response):
    """Match exact name and department; ambiguous or incomplete results fail."""
    dep = _department_code(group)
    if dep is None or not isinstance(response, list) or len(response) > 100:
        return None
    matches = []
    for row in response:
        if not isinstance(row, dict):
            return None
        if not isinstance(row.get("nom"), str) or norm(row["nom"]) != norm(group["city"]):
            continue
        if row.get("codeDepartement") != dep:
            continue
        code = row.get("code")
        if not isinstance(code, str) or not INSEE_CODE.fullmatch(code) or not code.startswith(dep):
            return None
        matches.append(code)
    return matches[0] if len(matches) == 1 else None


def named_osm_query(code, venue):
    if (not isinstance(code, str) or not INSEE_CODE.fullmatch(code)
            or not isinstance(venue, str) or not 2 <= len(venue) <= 180
            or not norm(venue) or any(ord(c) < 32 for c in venue)):
        raise ValueError("invalid_named_search")
    # Exact INSEE boundary and literal name (no untrusted regex or query code).
    return ('[out:json][timeout:20];area["boundary"="administrative"]'
            '["admin_level"="8"]["ref:INSEE"="' + code + '"]->.a;'
            'nwr(area.a)["name"=' + json.dumps(venue, ensure_ascii=False)
            + '];out center tags ' + str(MAX_ELEMENTS) + ';')


def fetch_named_osm(code, venue):
    query = named_osm_query(code, venue)
    for endpoint in ENDPOINTS:
        try:
            url = endpoint + "?" + urlencode({"data": query})
            req = Request(url, headers={"Accept": "application/json",
                "User-Agent": "PtitesOndesPrivateNamedVenue/1.0 (read-only)"})
            with build_opener(NoRedirect()).open(req, timeout=26) as response:
                if response.status != 200 or response.geturl() != url:
                    raise ValueError("bad_named_provider_response")
                raw = response.read(MAX_BYTES + 1)
            if not raw or len(raw) > MAX_BYTES:
                raise ValueError("oversized_named_provider_response")
            return json.loads(raw)
        except (OSError, UnicodeError, ValueError):
            continue
    raise ValueError("named_provider_unavailable")


def _discover_named_location(group, directory, named_osm_get, html_get, ign_get, commune_get):
    """Independently find a named place and its website in the commune.

    The OSM coordinate is only a discovery hint. A second live website
    must explicitly corroborate the named location by a numbered BAN
    address, structured point, or exact street/postcode without a number.
    The result is private research only, never a publication proof.
    """
    code = _commune_code(group, directory)
    if code is None:
        code = administrative_commune_code(group, commune_get(group))
    if code is None:
        return None
    response = named_osm_get(code, group["venue"])
    if (not isinstance(response, dict) or response.get("remark")
            or not isinstance(response.get("elements"), list)
            or len(response["elements"]) >= MAX_ELEMENTS):
        return None
    items = [x for x in response["elements"] if isinstance(x, dict)
             and isinstance(x.get("tags"), dict)
             and norm(x["tags"].get("name")) == norm(group["venue"])]
    if len(items) != 1:
        return None
    obj = items[0]
    tags = obj["tags"]
    if (tags.get("addr:city") and norm(tags["addr:city"]) != norm(group["city"])
            or tags.get("addr:country") and norm(tags["addr:country"]) not in ("fr", "france")):
        return None
    raw = obj if obj.get("type") == "node" else obj.get("center")
    if not isinstance(raw, dict):
        return None
    point = _coordinates((raw.get("lat"), raw.get("lon")))
    if point is None or point == (0, 0):
        return None
    named = {**group, "key": [norm(group["city"]), norm(group["venue"])]}
    if len(osm_hints(named, point, response)) != 1:
        return None
    websites = [tags[k] for k in ("website", "contact:website") if k in tags]
    hosts = [_osm_website_host(u) for u in websites]
    if not hosts or any(h is None or not _same_host(h, hosts[0]) for h in hosts):
        return None
    # Only one website is read; safe reader rejects nonpublic DNS and redirects.
    u = urlsplit(websites[0])
    url = urlunsplit(("https", u.hostname, u.path or "/", "", ""))
    if _safe_url(url) is None:
        return None
    page = html_get(url)
    # Reuse exact numbered-address and named OSM attribution logic.
    loc = _external_location(group, url, page, ign_get, lambda _: response)
    if loc is not None:
        return loc
    if extract_official_address(group, page) is not None:
        return None
    # No street number needed if the independent venue page supplies an exact
    # named structured point or exact street/postcode matching OSM.
    official_point = _exact_official_point(group, page)
    if official_point is not None:
        if meters(official_point, point) > 65:
            return None
        method = "Named OSM in INSEE commune + venue website exact coordinates"
    else:
        address = _visible_unnumbered_official_address(group, page)
        if (address is None or not POSTCODE.fullmatch(str(tags.get("addr:postcode", "")))
                or str(tags["addr:postcode"]) != address["postcode"]
                or norm(tags.get("addr:street")) != address["street_normalized"]):
            return None
        method = "Named OSM in INSEE commune + venue website unnumbered street"
    return dict(lat=point[0], lng=point[1], official=url, geo_source=method)


def research_group(group, today, *, directory_get=fetch_dila,
                   html_get=read_unknown_https, ign_get=fetch_ign,
                   osm_get=fetch_overpass, named_osm_get=fetch_named_osm,
                   commune_get=fetch_commune):
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
        try:
            loc = _discover_named_location(group, directory, named_osm_get, html_get, ign_get, commune_get)
            if loc is not None:
                locations.append(loc)
        except ERRORS:
            pass
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
