"""National cultural venue registry -> official festival detail, private research only.

The public data.gouv.fr tabular API exposes the Ministry of Culture's open
cultural venues register. A city and region from a fresh OpenAgenda lead are
selectors, not edition or location evidence. Only registry website links
are visited, and the same exact festival/ticket backlink validators apply.
"""
from datetime import date
import json
import re
import ssl
from urllib.parse import urlencode, urlsplit

from dns_pinned_https import DNSPinnedHTTPSConnection, fetch_public_html, safe_public_url
from national_openagenda_research import _safe_city_hint, _valid_professional_hints, REGIONS
from national_professional_profile_discovery import ticket_variants, ALLOWED_WEBSITE_ROLES
from national_professional_official_detail import examine, MAX_SITES, MAX_PAGES
from source_qualification import classify, normalized

HOST = "tabular-api.data.gouv.fr"
ENDPOINT = "/api/resources/4bd1a20e-4dfd-40ff-bd4d-c714f7085de8/data/"
PAGE_SIZE = 25
MAX_BYTES = 1_500_000
MAX_PAGES_AVAILABLE = 100


def registry_path(city, region, page=1):
    if (_safe_city_hint(city) != city or city is None or region not in REGIONS
            or type(page) is not int or not 1 <= page <= MAX_PAGES_AVAILABLE):
        return None
    return ENDPOINT + "?" + urlencode({
        "commune__exact": city.upper(),
        "region__exact": region,
        "domaines__contains": "Arts du spectacle",
        "page_size": PAGE_SIZE,
        "page": page,
    })


def fetch_registry(city, region, page=1):
    path = registry_path(city, region, page)
    if path is None:
        raise ValueError("Invalid cultural registry selector")
    conn = DNSPinnedHTTPSConnection(HOST, port=443, timeout=10,
                                    context=ssl.create_default_context())
    try:
        conn.request("GET", path, headers={
            "Host": HOST, "User-Agent": "GrossesOndesCulturalVenueResearch/1.0",
            "Accept": "application/json", "Accept-Encoding": "identity",
        })
        response = conn.getresponse()
        raw = response.read(MAX_BYTES + 1)
        if (response.status != 200 or len(raw) > MAX_BYTES
                or response.getheader("content-type", "").split(";", 1)[0].strip().lower()
                   != "application/json"
                or response.getheader("content-encoding", "identity").lower() != "identity"):
            raise ValueError("Unusable cultural registry response")
        return json.loads(raw.decode("utf-8"))
    finally:
        conn.close()


def _list(value):
    if isinstance(value, str) and len(value) <= 6000:
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return []
    return value if isinstance(value, list) and len(value) <= 30 else []


def _rows(payload, page):
    if not isinstance(payload, dict) or not isinstance(payload.get("meta"), dict):
        raise ValueError("Invalid cultural registry response")
    meta = payload["meta"]
    total, rows = meta.get("total"), payload.get("data")
    if (type(total) is not int or not 0 <= total <= PAGE_SIZE * MAX_PAGES_AVAILABLE
            or meta.get("page") != page or meta.get("page_size") != PAGE_SIZE
            or not isinstance(rows, list) or len(rows) > PAGE_SIZE
            or len(rows) != max(0, min(PAGE_SIZE, total - (page - 1) * PAGE_SIZE))):
        raise ValueError("Invalid cultural registry pagination")
    return total, rows


def sites_from_rows(rows, city, region):
    ranked = {}
    for row in rows:
        if (not isinstance(row, dict)
                or normalized(str(row.get("commune") or "")) != normalized(city)
                or row.get("region") != region
                or not re.fullmatch(r"[0-9A-B]{5}", str(row.get("code_commune") or ""))
                or "Arts du spectacle" not in _list(row.get("domaines"))):
            continue
        sub = " ".join(str(x) for x in _list(row.get("sous_domaines")))
        rank = 0 if re.search(r"\b(?:musique|cabaret|concert)\b", normalized(sub)) else 1
        for url in _list(row.get("site_internet_et_autres_liens")):
            if not isinstance(url, str) or safe_public_url(url) is None:
                continue
            if classify(url) not in ALLOWED_WEBSITE_ROLES:
                continue
            root = "https://" + urlsplit(url).hostname + "/"
            if safe_public_url(root) != root:
                continue
            ranked[root] = min(rank, ranked.get(root, rank))
    return sorted(ranked, key=lambda u: (ranked[u], u))


def cultural_detail(lead, title, year, today, *, fetch=fetch_public_html,
                    registry_fetch=fetch_registry):
    """Use registry discovery only; re-prove exact official details independently."""
    result = {"status": "NO_OFFICIAL_DETAIL_PROOF", "requests": 0, "proofs": [],
              "review_only": True, "safe_to_publish": False,
              "publication_authorized": False, "research_route": "CULTURAL_REGISTRY",
              "registry_requests": 0, "sites_selected": 0}
    if not isinstance(lead, dict):
        return result
    city, region = lead.get("city_hint_review_only"), lead.get("region_hint")
    hints = lead.get("professional_source_hints_review_only")
    if registry_path(city, region) is None or not _valid_professional_hints(hints):
        return result
    tickets = []
    for item in hints["links"]:
        if item["field"] in ("registration", "links"):
            for ticket in ticket_variants(item["url"]):
                if ticket not in tickets:
                    tickets.append(ticket)
    if not tickets:
        return result
    try:
        result["registry_requests"] += 1
        total, rows = _rows(registry_fetch(city, region, 1), 1)
        pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        selected = 1 + date.fromisoformat(today).toordinal() % pages
        if selected != 1:
            result["registry_requests"] += 1
            total2, rows = _rows(registry_fetch(city, region, selected), selected)
            if total2 != total:
                return result
        websites = sites_from_rows(rows, city, region)
        if len(websites) > MAX_SITES:
            offset = (date.fromisoformat(today).toordinal() * MAX_SITES) % len(websites)
            websites = websites[offset:] + websites[:offset]
        websites = websites[:MAX_SITES]
        result["sites_selected"] = len(websites)
        if not websites:
            return result
        cache = {}
        def read(url):
            if url not in cache:
                if len(cache) >= MAX_PAGES:
                    raise ValueError("Cultural research budget exhausted")
                cache[url] = None
                cache[url] = fetch(url)
            if cache[url] is None:
                raise ValueError("Unavailable cultural website")
            return cache[url]
        # Only the registry websites are fetched. Ticket variants are
        # selectors for an exact visible backlink, never requested here.
        for ticket in tickets[:2]:
            research = {"status": "PROFESSIONAL_WEBSITE_HINTS", "review_only": True,
                        "safe_to_publish": False, "publication_authorized": False,
                        "websites": [{"website_url": site, "ticket_url": ticket,
                                      "verified": False, "publication_authorized": False}
                                     for site in websites]}
            report = examine(research, title, year, today, fetch=read)
            if report["status"] == "CONFLICTING_OFFICIAL_DETAILS":
                result["status"] = report["status"]
                result["proofs"] = []
                break
            if report["status"] == "OFFICIAL_DETAIL_PROOF_REVIEW_ONLY":
                result["proofs"].extend(report["proofs"])
        result["requests"] = len(cache)
        if len({(p["start_date"], p["end_date"]) for p in result["proofs"]}) > 1:
            result["proofs"] = []
            result["status"] = "CONFLICTING_OFFICIAL_DETAILS"
        elif result["proofs"]:
            result["proofs"] = result["proofs"][:MAX_SITES]
            result["status"] = "OFFICIAL_DETAIL_PROOF_REVIEW_ONLY"
        return result
    except (OSError, ValueError, TypeError, UnicodeError, KeyError, RecursionError):
        return result
