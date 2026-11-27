"""Independently locate a named physical event site without an OSM URL in JSON-LD.

The first-party EVENT already proves a named site, French postal address,
date, lineup and genre. Only if its direct OSM link is absent, corroborate the
*exact postal street* via France's BAN (IGN Géoplateforme), then look for a
single, identically named OSM node or way near that verified street address.
No BAN point, neighbourhood centroid, generic map pin or similarly named
feature is by itself a site approval. This is intentionally bounded to a tiny
map extent and only runs on already qualified individual official events.
"""
from __future__ import annotations

import json
import math
import re
from urllib.parse import urlencode, urlsplit
from xml.etree import ElementTree

import triage
import osm_read_only_fallback as readonly

BAN = "https://data.geopf.fr/geocodage/search/"
OSM_MAP = "https://api.openstreetmap.org/api/0.6/map"
OSM_PUBLIC = "https://www.openstreetmap.org"
ESTABLISHMENTS = "https://recherche-entreprises.api.gouv.fr/search"
# Bounded < 200m box; no city-wide map queries or city centroid fallback.
LAT_HALF = 0.00065
LON_HALF = 0.00110
MAX_DISTANCE_METERS = 95


class NamedFeatureHeld(ValueError):
    """Fixed, non-sensitive reason for a failed independent feature match."""
    CODES = frozenset({"osm_name_not_found", "osm_postal_fields_conflict",
                      "osm_house_number_conflict", "osm_geometry_missing",
                      "osm_feature_outside_radius", "osm_street_conflict",
                      "osm_multiple_named_features"})

    def __init__(self, code):
        if code not in self.CODES:
            raise ValueError("Invalid named feature diagnostic")
        self.code = code
        # Preserve the existing shared consumer contract and exception type.
        super().__init__("Independent BAN/OSM site: one independent named OSM feature at exact address required")


class GovernmentAddressHeld(ValueError):
    """Fixed diagnostic, preserving the original strict rejection contract."""
    CODES = ("ban_no_valid_point", "ban_postal_identity_mismatch",
             "ban_street_name_mismatch", "ban_address_type_mismatch",
             "ban_house_number_mismatch", "ban_score_insufficient",
             "ban_multiple_exact_addresses")

    def __init__(self, code):
        if code not in self.CODES:
            raise ValueError("Invalid government address diagnostic")
        self.code = code
        super().__init__("Independent BAN/OSM site: one exact government street address required")


def require(ok, reason):
    if not ok:
        raise ValueError("Independent BAN/OSM site: " + reason)


def clean(value):
    return triage.words(value)


def _street_parts(value):
    text = str(value or "").strip()
    match = re.match(r"^([0-9]{1,4}(?:\s*(?:bis|ter|quater|[a-z]))?)\s+(.+)$",
                     text, flags=re.I)
    if not match:
        return None, clean(text)
    return clean(match[1]), clean(match[2])


def _distance_meters(lat1, lon1, lat2, lon2):
    radius = 6371008.8
    a1, a2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((a2-a1)/2)**2
         + math.cos(a1)*math.cos(a2)
         *math.sin(math.radians(lon2-lon1)/2)**2)
    return 2*radius*math.asin(min(1, math.sqrt(a)))


def _geo(valid):
    return (isinstance(valid, (list, tuple)) and len(valid) == 2
            and all(type(x) in (int, float) and math.isfinite(x)
                    for x in valid)
            and -180 <= valid[0] <= 180 and -56 <= valid[1] <= 52)


def _ban_result(site, fetch, *, include_region=False, min_score=0.78):
    # BAN ranking is not proof of location. Even a low-scored match must
    # agree EXACTLY on postcode, city, street and house number, followed by
    # an independently named OSM feature before Publisher validation.
    require(type(min_score) in (int, float) and math.isfinite(min_score)
            and 0.78 <= min_score <= 0.99,
            "invalid French address confidence policy")
    postcode = site["postalCode"]
    city = site["city"]
    house, street = _street_parts(site["address"])
    require(street and len(street) >= 4 and re.fullmatch(r"\d{5}", postcode),
            "incomplete official postal address")
    params = urlencode({
        "q": f"{site['address']} {postcode} {city}, France",
        "limit": 5, "autocomplete": 0,
    })
    url = BAN + "?" + params
    body, final = fetch(url, 130_000)
    require(final == url and isinstance(body, str) and len(body) <= 130_000,
            "French government address lookup unavailable")
    report = json.loads(body)
    require(isinstance(report, dict)
            and isinstance(report.get("features"), list)
            and len(report["features"]) <= 5,
            "ambiguous or invalid government response")
    eligible = []
    deepest = 0
    for item in report["features"]:
        if not isinstance(item, dict):
            continue
        props, geom = item.get("properties"), item.get("geometry")
        if not isinstance(props, dict) or not isinstance(geom, dict):
            continue
        coords = geom.get("coordinates")
        if not _geo(coords) or geom.get("type") != "Point":
            continue
        deepest = max(deepest, 1)
        if props.get("postcode") != postcode or clean(props.get("city")) != clean(city):
            continue
        deepest = max(deepest, 2)
        if clean(props.get("street")) != street:
            continue
        deepest = max(deepest, 3)
        if props.get("type") != ("housenumber" if house else "street"):
            continue
        deepest = max(deepest, 4)
        if house and clean(props.get("housenumber")) != house:
            continue
        deepest = max(deepest, 5)
        if (type(props.get("score")) not in (int, float)
                or not math.isfinite(props["score"])
                or props["score"] < min_score):
            continue
        eligible.append(((coords[1], coords[0]), props.get("context")))
    if len(eligible) != 1:
        raise GovernmentAddressHeld(GovernmentAddressHeld.CODES[
            6 if len(eligible) > 1 else deepest])
    center, context = eligible[0]
    if not include_region:
        return center
    # Government BAN context: "<department>, <department name>, <region>"
    # (in some overseas departments the region is also the department).
    # Unlike the untrusted event page this is an independent, exact-address
    # and high-score government response. Never guess the region from city.
    require(isinstance(context, str) and len(context) <= 180,
            "independent government region unavailable")
    parts = [x.strip() for x in context.split(",")]
    dept = str(site.get("department") or "").upper()
    require(len(parts) in (2, 3) and parts[0].upper() == dept
            and (len(parts) == 3 or dept.startswith(("97", "98"))),
            "independent government department mismatch")
    region = parts[-1]
    require(3 <= len(region) <= 90
            and all(ch.isalpha() or ch in " -'" for ch in region),
            "independent government region invalid")
    return center, region


def independently_attested_region(site, fetch):
    """A missing OPTIONAL first-party region can be sourced from exact BAN.

    Return the validated region and exact-address point for optional
    cross-checking of the separately named OSM feature; no city centroid,
    approximate match or postcode-only inference is accepted.
    """
    return _ban_result(site, fetch, include_region=True)


def _node_tags(obj):
    return {t.get("k"): t.get("v") for t in obj.findall("tag")
            if t.get("k") and t.get("v")}


def _website_host(value):
    if not isinstance(value, str):
        return None
    try:
        parts = urlsplit(value)
        if (parts.scheme != "https" or not parts.hostname or parts.username
                or parts.password or parts.port not in (None, 443)
                or parts.query or parts.fragment):
            return None
        return parts.hostname.casefold().removeprefix("www.")
    except ValueError:
        return None


def _registered_address(site, tags, position, fetch, website, min_score):
    """Resolve an old OSM street ONLY by an exact active public establishment.

    The caller already has an independently registered official venue origin.
    A matching name alone, business name search, coordinates alone, or an
    approximate postcode is never enough. SIRET is read from the actual
    named OSM feature, not from a candidate's description.
    """
    host = _website_host(website)
    links = [tags[k] for k in ("website", "contact:website") if tags.get(k)]
    siret = tags.get("ref:FR:SIRET")
    house, street = _street_parts(site["address"])
    osm_house = tags.get("addr:housenumber")
    if (not host or not links or any(_website_host(link) != host for link in links)
            or not isinstance(siret, str) or not re.fullmatch(r"\d{14}", siret)
            or clean(tags.get("addr:city")) != clean(site["city"])
            or tags.get("addr:postcode") != site["postalCode"]
            or not isinstance(osm_house, str) or not re.fullmatch(r"\d{1,4}", osm_house)
            or (house is not None and house != osm_house)):
        return False
    # Only public establishment fields are used; never persist raw responses,
    # legal representatives, or any unneeded administrative data.
    url = ESTABLISHMENTS + "?" + urlencode({"q": siret})
    try:
        body, final = fetch(url, 130_000)
        if final != url or not isinstance(body, str) or len(body) > 130_000:
            return False
        data = json.loads(body)
        results = data.get("results")
        if not isinstance(results, list) or len(results) != 1:
            return False
        entity = results[0]
        if entity.get("siren") != siret[:9]:
            return False
        establishments = entity.get("matching_etablissements") or []
        if not isinstance(establishments, list):
            return False
        rows = [entity.get("siege")] + establishments
        matches = [row for row in rows if isinstance(row, dict) and row.get("siret") == siret]
        if not matches:
            return False
        for row in matches:
            if (row.get("etat_administratif") != "A"
                    or row.get("statut_diffusion_etablissement") != "O"
                    or row.get("code_pays_etranger")
                    or row.get("code_postal") != site["postalCode"]
                    or clean(row.get("libelle_commune")) != clean(site["city"])
                    or row.get("numero_voie") != osm_house
                    or row.get("indice_repetition")
                    or clean(str(row.get("type_voie") or "") + " " +
                             str(row.get("libelle_voie") or "")) != street):
                return False
        # Require a separate exact BAN house-number lookup at the actual
        # named building. The original street lookup and radius still apply.
        numbered = dict(site, address=osm_house + " " + re.sub(
            r"^\d{1,4}\s+", "", site["address"]))
        center = _ban_result(numbered, fetch, min_score=min_score)
        return _distance_meters(*center, *position) <= MAX_DISTANCE_METERS
    except (ValueError, TypeError, KeyError, AttributeError, OSError, TimeoutError):
        return False


def _osm_map(site, center, fetch, *, official_website=None, min_score=0.78):
    lat, lon = center
    require(-56 <= lat <= 52 and -180 <= lon <= 180,
            "address geocode outside territorial bounds")
    bbox = ",".join(f"{v:.6f}" for v in (
        lon-LON_HALF, lat-LAT_HALF, lon+LON_HALF, lat+LAT_HALF))
    url = OSM_MAP + "?bbox=" + bbox
    try:
        body, final = fetch(url, 650_000)
    except (ValueError, OSError, TimeoutError):
        # OSM editing API may reject unattended requests. Use only these
        # reviewed read-only transports with the SAME bounded bbox. Each
        # fetch independently enforces DNS pinning, TLS, robots and caps.
        # A successful but contradictory geometry never triggers failover:
        # only failures of the transport may select another provider.
        for provider in range(len(readonly.ENDPOINTS)):
            fallback = readonly.nearby(
                lat-LAT_HALF, lon-LON_HALF, lat+LAT_HALF, lon+LON_HALF,
                provider=provider)
            try:
                body, final = fetch(fallback, 650_000)
                url = fallback
                break
            except (ValueError, OSError, TimeoutError):
                continue
        else:
            raise ValueError("All reviewed OSM read-only transports unavailable")
    require(final == url and isinstance(body, str)
            and len(body) <= 650_000
            and "<!DOCTYPE" not in body.upper()
            and "<!ENTITY" not in body.upper(),
            "OSM map unavailable or unsafe")
    root = ElementTree.fromstring(body)
    require(root.tag == "osm" and root.get("version") == "0.6",
            "OSM feature collection invalid")
    nodes = {}
    for n in root.findall("node"):
        ident = n.get("id")
        if not ident or not ident.isdigit():
            continue
        try:
            nla, nlo = float(n.get("lat")), float(n.get("lon"))
        except (ValueError, TypeError):
            continue
        if _geo((nlo, nla)):
            nodes[ident] = (nla, nlo)
    house, official_street = _street_parts(site["address"])
    matches = []
    conflicting_street = []
    stages = set()
    for kind in ("node", "way"):
        for feature in root.findall(kind):
            ident = feature.get("id")
            if not ident or not ident.isdigit() or int(ident) < 1:
                continue
            tags = _node_tags(feature)
            # OSM POIs frequently omit address tags. The exact official
            # street is already independently verified by BAN, and the named
            # feature must be unique within 95 m. Never treat an explicitly
            # contradictory OSM city or postal code as missing information.
            if clean(tags.get("name")) != clean(site["name"]):
                continue
            stages.add("name")
            if ((tags.get("addr:city") is not None
                        and clean(tags["addr:city"]) != clean(site["city"]))
                    or (tags.get("addr:postcode") is not None
                        and tags["addr:postcode"] != site["postalCode"])
                    or tags.get("addr:country", "FR").upper() != "FR"):
                continue
            stages.add("postal")
            different_street = bool(tags.get("addr:street")
                                    and clean(tags["addr:street"]) != official_street)
            if house and tags.get("addr:housenumber") and clean(
                    tags["addr:housenumber"]) != house:
                continue
            stages.add("house")
            if kind == "node":
                position = nodes.get(ident)
            else:
                references = [nd.get("ref") for nd in feature.findall("nd")]
                unique = list(dict.fromkeys(references))
                refs = [nodes.get(x) for x in unique]
                position = (sum(x[0] for x in refs) / len(refs),
                            sum(x[1] for x in refs) / len(refs)) if (
                                len(refs) >= 3 and all(refs)) else None
            if position:
                stages.add("geometry")
            if position and _distance_meters(
                    lat, lon, position[0], position[1]) <= MAX_DISTANCE_METERS:
                stages.add("distance")
                match = (f"{OSM_PUBLIC}/{kind}/{ident}",
                         position[0], position[1],
                         "named-site-point" if kind == "node" else "named-site-area")
                if different_street:
                    conflicting_street.append((match, tags, position))
                else:
                    matches.append(match)
    # Default route remains unchanged. Never resolve ambiguous named
    # features by picking an establishment from several conflicting ones.
    if not matches and official_website and len(conflicting_street) == 1:
        match, tags, position = conflicting_street[0]
        if _registered_address(site, tags, position, fetch, official_website, min_score):
            matches.append(match)
    if len(matches) != 1:
        if len(matches) > 1 or len(conflicting_street) > 1:
            code = "osm_multiple_named_features"
        elif "distance" in stages:
            code = "osm_street_conflict"
        elif "geometry" in stages:
            code = "osm_feature_outside_radius"
        elif "house" in stages:
            code = "osm_geometry_missing"
        elif "postal" in stages:
            code = "osm_house_number_conflict"
        elif "name" in stages:
            code = "osm_postal_fields_conflict"
        else:
            code = "osm_name_not_found"
        raise NamedFeatureHeld(code)
    return matches[0]


def verify(site, fetch, *, min_score=0.78, official_website=None):
    """The caller must have verified a single dated first-party Event beforehand.

    fetch(url, byte_cap) -> (body, final_url); the production fetch honours
    HTTPS, robots restrictions, and exact destination URLs. This module does
    not grant concert approvals and has no arbitrary host/URL input.
    """
    require(isinstance(site, dict) and all(
        isinstance(site.get(field), str) and site[field].strip()
        for field in ("name", "city", "address", "postalCode", "region")),
        "official event site identity absent")
    center = _ban_result(site, fetch, min_score=min_score)
    return _osm_map(site, center, fetch, official_website=official_website,
                    min_score=min_score)
