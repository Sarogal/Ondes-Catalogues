#!/usr/bin/env python3
"""Independently verify municipality website domains using the DILA directory.

No city/venue allowlist: the first-party municipality site is taken ONLY from
the official public administration directory, never OpenAgenda or OSM fields.
This authenticates a municipal WEB DOMAIN, not a venue, event, rights, or GPS.
"""
import ipaddress
import json
import re
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

from proof import norm

DILA_RECORDS = ("https://api-lannuaire.service-public.gouv.fr/api/explore/"
                "v2.1/catalog/datasets/api-lannuaire-administration/records")
SCHEMA = "ptitesondes.dila_municipal_domain_proof.v1"
MAX_RECORDS = 30
MAX_BYTES = 240_000
MAX_SOURCE_SITES = 5
BLOCKED_SHARED = frozenset((
    "facebook.com", "instagram.com", "wordpress.com", "blogspot.com",
    "wixsite.com", "sites.google.com", "google.com", "linktr.ee",
    "youtube.com", "x.com", "twitter.com", "github.io", "netlify.app",
    "webflow.io", "canva.site",
))
NAME = re.compile(r"[\w\u00C0-\u024F .\-'’]{1,120}\Z", re.UNICODE)
DNS_NAME = re.compile(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+\Z")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _host(url):
    if not isinstance(url, str) or len(url) > 600:
        return None
    try:
        p = urlsplit(url)
        if (p.scheme != "https" or not p.hostname or p.username
                or p.password or p.port not in (None, 443)
                or p.fragment or not DNS_NAME.fullmatch(p.hostname)
                or p.hostname.endswith((".local", ".localhost", ".internal"))
                or p.hostname in ("localhost",)):
            return None
        try:
            ipaddress.ip_address(p.hostname)
            return None
        except ValueError:
            pass
        host = p.hostname
        if any(host == blocked or host.endswith("." + blocked)
               for blocked in BLOCKED_SHARED):
            return None
        return host
    except ValueError:
        return None


def _structured(value, max_items=50):
    if isinstance(value, str):
        if len(value) > 50000:
            return None
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return None
    return value if isinstance(value, list) and len(value) <= max_items else None


def dila_query(city):
    """Restrict user-derived query to a documented ODS search expression."""
    if (not isinstance(city, str) or not NAME.fullmatch(city)
            or any(c in city for c in ('"', "\\", "\n", "\r"))
            or not norm(city)):
        raise ValueError("invalid_municipality")
    condition = 'nom LIKE "' + city + '" AND pivot LIKE "mairie"'
    return DILA_RECORDS + "?" + urlencode({
        "where": condition, "limit": MAX_RECORDS,
        "select": ("nom,pivot,code_insee_commune,adresse,categorie,"
                   "statut_de_diffusion,site_internet,url_service_public,copyright"),
    })


def fetch_dila(city, opener=None):
    url = dila_query(city)
    fetch = opener or build_opener(NoRedirect()).open
    with fetch(Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "PtitesOndesDILAMunicipalSource/1.0 (read-only)",
    }), timeout=18) as response:
        if response.status != 200 or response.geturl() != url:
            raise ValueError("dila_redirect_or_bad_status")
        raw = response.read(MAX_BYTES + 1)
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError("dila_response_oversized")
    return json.loads(raw)


def municipal_site_hosts(city, response):
    """Return exactly identified mairie site domains; empty = fail closed.

    A self-described OpenAgenda 'official=1', claimed OA location website or
    OSM website tag can NEVER create this evidence.
    """
    if not isinstance(city, str) or not norm(city):
        return frozenset()
    if (not isinstance(response, dict)
            or not isinstance(response.get("results"), list)
            or type(response.get("total_count")) is not int
            or not 0 <= response["total_count"] <= MAX_RECORDS
            or len(response["results"]) > MAX_RECORDS):
        return frozenset()
    matching = []
    for row in response["results"]:
        if not isinstance(row, dict):
            continue
        url = row.get("url_service_public")
        try:
            parsed = urlsplit(url)
        except (TypeError, ValueError):
            continue
        if (parsed.scheme != "https"
                or parsed.hostname != "lannuaire.service-public.gouv.fr"
                or parsed.username or parsed.password
                or parsed.port not in (None, 443)
                or norm(row.get("nom")) != norm("Mairie - " + city)
                or row.get("categorie") != "SL"
                or row.get("statut_de_diffusion") != "Publiable"
                or row.get("copyright") !=
                    "Direction de l'information légale et administrative (Premier ministre)"):
            continue
        pivots = _structured(row.get("pivot"))
        addresses = _structured(row.get("adresse"))
        if pivots is None or addresses is None:
            continue
        code = str(row.get("code_insee_commune") or "")
        if not re.fullmatch(r"[0-9]{5}", code):
            continue
        if not any(
                isinstance(item, dict)
                and item.get("type_service_local") == "mairie"
                and isinstance(item.get("code_insee_commune"), list)
                and code in item["code_insee_commune"]
                for item in pivots):
            continue
        if not any(
                isinstance(item, dict)
                and norm(item.get("nom_commune")) == norm(city)
                and item.get("pays") == "France"
                for item in addresses):
            continue
        matching.append(row)
    # A homonymous municipality, multiple mairie records, or partial API
    # results must not cause us to silently pick an arbitrary site.
    if len(matching) != 1:
        return frozenset()
    sites = _structured(matching[0].get("site_internet"),
                        max_items=MAX_SOURCE_SITES)
    if sites is None:
        return frozenset()
    result = set()
    for site in sites:
        if not isinstance(site, dict):
            return frozenset()
        host = _host(site.get("valeur"))
        if host is None:
            continue
        result.add(host)
    return frozenset(result) if 1 <= len(result) <= MAX_SOURCE_SITES else frozenset()


def approved_municipal_page_host(page_url, city, directory_response):
    """Return the page host only if it falls under an independently listed site.

    Prefix 'www.' is normalized only for subdomain checks; domain is never
    inferred by removing arbitrary public suffixes or project keywords.
    """
    p = _host(page_url)
    if p is None:
        return None
    sites = municipal_site_hosts(city, directory_response)
    for site in sites:
        root = site[4:] if site.startswith("www.") else site
        if p in (site, root) or p.endswith("." + root):
            return p
    return None


def redacted_directory_status(city, directory_response, page_url):
    host = approved_municipal_page_host(page_url, city, directory_response)
    return {
        "schema": SCHEMA, "mode": "independent_municipal_host_only",
        "directory_municipality_matched": bool(municipal_site_hosts(city, directory_response)),
        "candidate_page_host_correlated": host is not None,
        "official_venue_verified": False,
        "event_sessions_verified": False,
        "publication_ready": False,
        "public_writes": 0,
    }
