"""National dynamic mairie website research for previously unknown festivals.

Find a municipality from the official geo API and its published town-hall
website from the DILA's *official* national directory, not a hand-written
allowlist of towns or hosts. This is ONLY a private lead: a mairie website
does not prove a festival date, organizer, genre, venue or permission to
publish. No discovered site is fetched by this module. Never use these
observations as the publisher's independent proof.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime
import json
from pathlib import Path
import re
import ssl
import sys
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

SCRIPTS = str(Path(__file__).resolve().parents[1] / "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from dns_pinned_https import DNSPinnedHTTPSConnection, safe_public_url
from official_admin_communes import verified_commune, normalize

SCHEMA = "grossesondes.national-dynamic-municipal-research-private.v1"
HOST = "api-lannuaire.service-public.gouv.fr"
DATASET = "/api/explore/v2.1/catalog/datasets/api-lannuaire-administration/records"
MAX_BYTES = 170_000
MAX_RESULTS = 20
MAX_CHECKS = 3
INSEE = re.compile(r"^[0-9A-B]{5}$")
SAFE_ID = re.compile(r"^national-[a-f0-9]{20}$")
EXCLUDED_WEBSITE_FAMILIES = frozenset((
    "facebook.com", "instagram.com", "twitter.com", "x.com",
    "youtube.com", "linktr.ee", "helloasso.com", "billetweb.fr",
    "shotgun.live", "weezevent.com",
))


def mairie_records_url(code):
    """Never send a candidate title, private URL, domain, or HTML to the API."""
    if not isinstance(code, str) or INSEE.fullmatch(code) is None:
        raise ValueError("Invalid official INSEE commune identifier")
    query = urlencode({
        "where": 'code_insee_commune LIKE "' + code +
                 '" AND search(nom, "Mairie")',
        "limit": str(MAX_RESULTS),
        "select": "nom,code_insee_commune,site_internet,pivot,statut_de_diffusion",
    })
    return "https://" + HOST + DATASET + "?" + query


def _expected_request_path(url):
    from urllib.parse import parse_qs, urlsplit
    try:
        parts = urlsplit(url)
        if (parts.scheme != "https" or parts.netloc != HOST
                or parts.path != DATASET or parts.fragment):
            raise ValueError("Unapproved DILA API origin")
        query = parse_qs(parts.query, strict_parsing=True)
        if set(query) != {"where", "limit", "select"}:
            raise ValueError("Unapproved DILA query")
        if any(len(v) != 1 for v in query.values()):
            raise ValueError("Ambiguous DILA query")
        match = re.fullmatch(
            r'code_insee_commune LIKE "([0-9A-B]{5})" AND search\(nom, "Mairie"\)',
            query["where"][0])
        if match is None or url != mairie_records_url(match.group(1)):
            raise ValueError("Unapproved DILA query")
        return parts.path + "?" + parts.query
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError("Unapproved DILA request") from exc


def fetch_dila_records(url):
    """HTTPS pinned to a reviewed government API; no redirects or proxies."""
    path = _expected_request_path(url)
    conn = DNSPinnedHTTPSConnection(HOST, port=443, timeout=10,
                                    context=ssl.create_default_context())
    try:
        conn.request("GET", path, headers={
            "User-Agent": "GrossesOndesMunicipalResearch/1.0",
            "Accept": "application/json",
            "Accept-Encoding": "identity",
        })
        response = conn.getresponse()
        raw = response.read(MAX_BYTES + 1)
        if (response.status != 200 or len(raw) > MAX_BYTES
                or response.getheader("Content-Encoding", "identity").lower() != "identity"
                or response.getheader("Content-Type", "").split(";", 1)[0].lower()
                   != "application/json"):
            raise ValueError("Invalid DILA directory response")
        return json.loads(raw.decode("utf-8"))
    finally:
        conn.close()


def _municipal_site(url):
    """Canonical homepage of one genuine HTTPS municipality website."""
    from urllib.parse import urlsplit
    if not isinstance(url, str) or safe_public_url(url) != url:
        return None
    parts = urlsplit(url)
    host = parts.hostname
    if (not host or any(host == blocked or host.endswith("." + blocked)
                        for blocked in EXCLUDED_WEBSITE_FAMILIES)):
        return None
    root = "https://" + host + "/"
    return root if safe_public_url(root) == root else None


def _sites_field(value):
    # Opendatasoft publishes this collection as text on the DILA dataset.
    if isinstance(value, str):
        if len(value) > 7000:
            return []
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return []
    if not isinstance(value, list) or len(value) > 12:
        return []
    return [x["valeur"] for x in value
            if isinstance(x, dict) and isinstance(x.get("valeur"), str)]


def verified_mairie_site(payload, insee, city):
    """Only an exactly matched DILA mairie record may suggest a website.

    A generic service office, promotional record, different city or multiple
    conflicting town-hall websites cannot become an institutional lead.
    """
    if (not isinstance(payload, dict)
            or type(payload.get("total_count")) is not int
            or payload["total_count"] > MAX_RESULTS
            or not isinstance(payload.get("results"), list)
            or len(payload["results"]) > MAX_RESULTS):
        return None
    websites = set()
    for row in payload["results"]:
        if not isinstance(row, dict):
            continue
        name = row.get("nom")
        if (row.get("code_insee_commune") != insee
                or not isinstance(name, str) or not name.startswith("Mairie - ")
                or normalize(name[len("Mairie - "):]) != normalize(city)
                or row.get("statut_de_diffusion") not in ("Publiable", None)):
            continue
        # The mairie type is part of the DILA locally published schema.
        pivots = row.get("pivot")
        if isinstance(pivots, str):
            try:
                pivots = json.loads(pivots)
            except (TypeError, ValueError):
                continue
        if not isinstance(pivots, list) or not any(
                isinstance(p, dict) and p.get("type_service_local") == "mairie"
                and insee in p.get("code_insee_commune", [])
                for p in pivots):
            continue
        for value in _sites_field(row.get("site_internet")):
            root = _municipal_site(value)
            if root is not None:
                websites.add(root)
    if len(websites) != 1:
        return None
    return next(iter(websites))


def select_dossiers(queue, today, limit=MAX_CHECKS):
    """Rotate all eligible city hints; no region, city or festival allowlist."""
    if (not isinstance(queue, dict)
            or queue.get("schema") != "grossesondes.national-festival-discovery-private.v1"
            or not isinstance(queue.get("dossiers"), list)
            or type(limit) is not int or not 0 <= limit <= MAX_CHECKS):
        raise ValueError("Invalid private national dossier queue")
    current = date.fromisoformat(today)
    eligible = []
    for row in queue["dossiers"][:200]:
        if not isinstance(row, dict):
            continue
        name, city, ident, year = (
            row.get("name_hint"), row.get("city_hint"),
            row.get("id"), row.get("edition_year_hint"))
        if (not isinstance(ident, str) or SAFE_ID.fullmatch(ident) is None
                or not isinstance(city, str) or not 2 <= len(city) <= 80
                or not isinstance(name, str) or not 7 <= len(name) <= 160
                or type(year) is not int
                or not current.year <= year <= current.year + 2):
            continue
        eligible.append(row)
    eligible.sort(key=lambda x: x["id"])
    if not eligible:
        return [], 0
    # Daily rotation; all dossiers are visited, not just first known towns.
    offset = (current.toordinal() * max(1, limit)) % len(eligible)
    return [eligible[(offset + i) % len(eligible)]
            for i in range(min(limit, len(eligible)))], len(eligible)


def research(queue, today, commune_lookup=verified_commune,
             directory_fetch=fetch_dila_records, limit=MAX_CHECKS):
    chosen, eligible = select_dossiers(queue, today, limit=limit)
    rows = []
    for item in chosen:
        ident, city = item["id"], item["city_hint"]
        entry = {"dossier_id": ident, "city_hint": city,
                 "status": "COMMUNE_NOT_IDENTIFIED"}
        try:
            admin = commune_lookup(city)
            if admin is not None:
                insee = admin.get("codeInsee")
                verified_city = admin.get("city")
                if (not isinstance(insee, str) or INSEE.fullmatch(insee) is None
                        or normalize(verified_city) != normalize(city)):
                    raise ValueError("Invalid government commune match")
                entry.update(code_insee=insee, status="MAIRIE_NOT_ATTRIBUTED")
                endpoint = mairie_records_url(insee)
                municipal = verified_mairie_site(
                    directory_fetch(endpoint), insee, verified_city)
                if municipal is not None:
                    entry.update(
                        municipal_website=municipal,
                        municipal_directory_source=endpoint,
                        status="MUNICIPAL_WEBSITE_RESEARCH_ONLY")
        except (OSError, TimeoutError, ValueError, UnicodeError,
                TypeError, KeyError):
            entry["status"] = "GOVERNMENT_DIRECTORY_UNAVAILABLE"
        rows.append(entry)
    return {
        "schema": SCHEMA, "as_of": today, "review_only": True,
        "publication_authorized": False, "publications": 0,
        "eligible_city_dossiers_count": eligible,
        "checked_count": len(rows),
        "municipal_websites_found_count": sum(
            r["status"] == "MUNICIPAL_WEBSITE_RESEARCH_ONLY" for r in rows),
        "rows": rows,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--intake", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=MAX_CHECKS)
    args = parser.parse_args()
    folder = args.intake
    queue = json.loads(
        (folder / "national-festival-discovery-review.json")
        .read_text(encoding="utf-8"))
    today = datetime.now(ZoneInfo("Europe/Paris")).date().isoformat()
    result = research(queue, today, limit=args.limit)
    (folder / "national-municipal-source-research.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print("Dynamic municipal research: eligible="
          + str(result["eligible_city_dossiers_count"])
          + ", checked=" + str(result["checked_count"])
          + ", municipal_websites=" + str(result["municipal_websites_found_count"])
          + ", publications=0")


if __name__ == "__main__":
    main()
