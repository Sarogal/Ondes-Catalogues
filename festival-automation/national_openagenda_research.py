"""Bounded nationwide public OpenAgenda OPEN-DATA discovery, private hints only.

This is NOT the authenticated OpenAgenda API. It reads the public Opendatasoft
dataset with a fixed, code-reviewed HTTPS origin and no caller-supplied URLs.
The metadata is third-party, NEVER an edition, genre, organizer, city, artist,
date or publisher proof. No URL extracted from records is fetched here.
"""
from __future__ import annotations

from datetime import date, datetime
from hashlib import sha256
import http.client
import json
from pathlib import Path
import re
import ssl
from urllib.parse import urlencode, urlsplit
from zoneinfo import ZoneInfo

from dns_pinned_https import DNSPinnedHTTPSConnection
from regional_festival_discovery import APPROVED
from source_qualification import normalized

SCHEMA = "grossesondes.national-openagenda-research-private.v1"
RESEARCH_RULESET = "event-title-and-published-edition-dedup.v2"
STATE_KEY = "national_openagenda_research_private"
SOURCE = "https://public.opendatasoft.com/api/explore/v2.1/catalog/datasets/evenements-publics-openagenda/records"
HOST = "public.opendatasoft.com"
ENDPOINT = "/api/explore/v2.1/catalog/datasets/evenements-publics-openagenda/records"
SELECT = ("uid,canonicalurl,title_fr,description_fr,keywords_fr,"
          "firstdate_begin,lastdate_begin,updatedat,location_region,"
          "location_countrycode,status")
QUERIES = (
    'search(title_fr,"festival")',
    'search(title_fr,"metal")',
    'search(title_fr,"rock")',
    'search(title_fr,"punk")',
    'search(title_fr,"hardcore")',
    'search(description_fr,"metal festival")',
)
MAX_BYTES = 450_000
PER_PAGE = 25
# Read at most 200 results from the broad festival category each day.
# Future events beyond the first page were frequently missed despite valid
# institutionally published metadata. This is bounded discovery only.
FESTIVAL_PAGE_OFFSETS = tuple(range(0, 200, PER_PAGE))
MAX_LEADS = 60
YEAR = re.compile(r"(?<![0-9])20[2-4][0-9](?![0-9])")
FEST = re.compile(r"(?:\bfestival\b|\bfest\b|\b[a-z]{3,30}fest\b)")
STYLE = re.compile(r"\b(?:metal|hard rock|hardcore|punk|post punk|"
                   r"rock|stoner|doom|grindcore|deathcore|metalcore|"
                   r"sludge|thrash|black metal|death metal)\b")
FORBIDDEN = re.compile(r"[<>{}\x00-\x1f]")
INDIVIDUAL_EVENT = re.compile(
    r"^(?:concerts?|spectacles?|soirees?|ateliers?|expositions?|"
    r"projections?|rencontres?|visites?|show|live)\b")
OVERSEAS = {
    "RE": "La Réunion", "GP": "Guadeloupe", "MQ": "Martinique",
    "GF": "Guyane", "YT": "Mayotte", "NC": "Nouvelle-Calédonie",
    "PF": "Polynésie française",
}
COUNTRIES = frozenset({"FR", *OVERSEAS})
REGIONS = frozenset(APPROVED.values())


def fixed_query_urls(today=None):
    """Code-reviewed queries with a validated, calendar-bounded date window.

    The only dynamic value is the Europe/Paris calendar date. No event, user
    or private state can supply a query term, URL, host, or date literal.
    """
    current = (date.fromisoformat(today) if today is not None
               else datetime.now(ZoneInfo("Europe/Paris")).date())
    last_year = current.year + 3
    views = ([(QUERIES[0], offset) for offset in FESTIVAL_PAGE_OFFSETS]
             + [(query, 0) for query in QUERIES[1:]])
    return tuple(SOURCE + "?" + urlencode({
        "select": SELECT,
        "where": ("(" + query + ") AND lastdate_begin >= date'"
                  + current.isoformat() + "' AND firstdate_begin < date'"
                  + str(last_year) + "-01-01'"),
        "order_by": "updatedat desc", "limit": PER_PAGE,
        "offset": offset,
    }) for query, offset in views)


def fetch_json(url, today=None):
    """DNS-pinned public-IP HTTPS, certificate/SNI and no redirects/proxies."""
    if url not in fixed_query_urls(today):
        raise ValueError("Unapproved OpenData request")
    parts = urlsplit(url)
    if parts.hostname != HOST or parts.path != ENDPOINT:
        raise ValueError("Unapproved OpenData host/path")
    conn = DNSPinnedHTTPSConnection(
        HOST, port=443, timeout=12, context=ssl.create_default_context())
    try:
        conn.request("GET", parts.path + "?" + parts.query, headers={
            "Host": HOST,
            "User-Agent": "GrossesOndesPublicOpenDataResearch/1.0",
            "Accept": "application/json", "Accept-Encoding": "identity",
        })
        response = conn.getresponse()
        raw = response.read(MAX_BYTES + 1)
        if response.status != 200 or len(raw) > MAX_BYTES:
            raise ValueError("Public OpenData HTTP or body rejected")
        content_type = response.getheader("content-type", "")
        if content_type.split(";", 1)[0].strip().lower() != "application/json":
            raise ValueError("Public OpenData is not JSON")
        if response.getheader("content-encoding", "identity").lower() != "identity":
            raise ValueError("Compressed or unverified OpenData body")
        return json.loads(raw.decode("utf-8"))
    finally:
        conn.close()


def _canonical_url(url):
    if not isinstance(url, str) or not 18 <= len(url) <= 500:
        return False
    try:
        parts = urlsplit(url)
        return (parts.scheme == "https"
                and parts.hostname == "openagenda.com"
                and parts.netloc == "openagenda.com"
                and parts.port is None and not parts.query and not parts.fragment
                and not parts.username and not parts.password
                and re.fullmatch(
                    r"/(?:[a-z]{2}/)?[a-z0-9-]+/events/[a-z0-9-]+",
                    parts.path) is not None)
    except (ValueError, TypeError):
        return False


def _iso_date(value):
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except (TypeError, ValueError):
        return None


def published_identity(name):
    """Conservative comparison: remove only a trailing year or edition number.

    Every other word remains; matching also requires the SAME region and year.
    Neither external data nor public catalog can grant a publisher approval.
    """
    if not isinstance(name, str):
        return None
    name = re.sub(r"\s+20[2-4]\d\s*$", "", name, flags=re.I).strip()
    name = re.sub(
        r"\s+(?:#\s?\d{1,2}|(?:edition|édition)\s*#?\s*\d{1,2})\s*$",
        "", name, flags=re.I).strip()
    name = re.sub(r"\s+20[2-4]\d\s*$", "", name, flags=re.I).strip()
    key = normalized(name)
    return key if len(key) >= 6 else None


def known_published_editions(catalog):
    """Read-only dedup identity list from trusted local public catalog."""
    if catalog is None:
        return set()
    if (not isinstance(catalog, dict) or catalog.get("schema") != 1
            or not isinstance(catalog.get("festivals"), list)
            or len(catalog["festivals"]) > 5000):
        raise ValueError("Invalid local published festival catalog")
    keys = set()
    for row in catalog["festivals"]:
        if not isinstance(row, dict):
            continue
        try:
            year = date.fromisoformat(row.get("startDate", "")).year
        except (TypeError, ValueError):
            continue
        name = published_identity(row.get("name"))
        region = row.get("region")
        if name and isinstance(region, str) and region in REGIONS:
            keys.add((name, year, region))
    return keys


def candidate(row, today):
    """Untrusted metadata can become only an unverified discovery lead."""
    if not isinstance(row, dict) or len(row) > 80:
        return None
    title, url = row.get("title_fr"), row.get("canonicalurl")
    if (not isinstance(title, str) or not 7 <= len(title) <= 150
            or FORBIDDEN.search(title) or not _canonical_url(url)):
        return None
    key = normalized(title)
    years = {int(x) for x in YEAR.findall(key)}
    current = date.fromisoformat(today)
    if len(years) > 1:
        return None
    first, last = _iso_date(row.get("firstdate_begin")), _iso_date(row.get("lastdate_begin"))
    if first is None or last is None or last < current or last < first:
        return None
    # Without a printed year, the provider's calendar year is an UNVERIFIED
    # RESEARCH HINT only. No published edition date is derived from it.
    year = next(iter(years)) if years else first.year
    if (not current.year <= year <= current.year + 2
            or first.year != year or not FEST.search(key)
            or INDIVIDUAL_EVENT.match(key)):
        return None
    country = row.get("location_countrycode")
    if not isinstance(country, str) or country not in COUNTRIES:
        return None
    region = OVERSEAS.get(country) if country != "FR" else row.get("location_region")
    if not isinstance(region, str) or region not in REGIONS:
        return None
    # Genre can be found in a short description or keyword, but is NEVER a
    # verified genre or a reason for publisher eligibility.
    description = row.get("description_fr")
    description = description if isinstance(description, str) else ""
    keywords = row.get("keywords_fr")
    keywords = " ".join(x for x in keywords[:24] if isinstance(x, str)) if isinstance(keywords, list) else ""
    genre_text = normalized((title + " " + description[:1500] + " " + keywords)[:1800])
    if not STYLE.search(genre_text):
        return None
    status = row.get("status")
    if isinstance(status, str) and re.search(
            r"annul|cancel|report|postpon", normalized(status)):
        return None
    digest = sha256((url + "\n" + key + "\n" + str(year)).encode("utf-8")).hexdigest()[:20]
    return {
        "id": "oa-" + digest, "name_hint": title,
        "edition_year_hint": year, "region_hint": region,
        "year_source_review_only": ("TITLE" if years
                                    else "UNVERIFIED_PROVIDER_START_DATE"),
        "source_url": url, "observed_at": today,
        "kind": "OPENAGENDA_PUBLIC_RESEARCH_ONLY",
        "review_only": True, "safe_to_publish": False,
        "publication_authorized": False, "festival_verified": False,
        "edition_dates_verified": False, "official_site_verified": False,
    }


def validated_leads(state, today):
    report = state.get(STATE_KEY, {})
    if (not isinstance(report, dict) or report.get("schema") != SCHEMA
            or report.get("research_ruleset") != RESEARCH_RULESET):
        return []
    if (report.get("as_of") != today or report.get("review_only") is not True
            or report.get("publication_authorized") is not False
            or report.get("safe_to_publish") is not False
            or not isinstance(report.get("leads"), list)
            or len(report["leads"]) > MAX_LEADS):
        return []
    valid = []
    for row in report["leads"]:
        if (not isinstance(row, dict)
                or row.get("kind") != "OPENAGENDA_PUBLIC_RESEARCH_ONLY"
                or row.get("observed_at") != today
                or row.get("review_only") is not True
                or row.get("publication_authorized") is not False
                or row.get("safe_to_publish") is not False
                or row.get("festival_verified") is not False
                or row.get("edition_dates_verified") is not False
                or row.get("official_site_verified") is not False
                or not _canonical_url(row.get("source_url"))
                or not isinstance(row.get("name_hint"), str)
                or FORBIDDEN.search(row["name_hint"])
                or not 7 <= len(row["name_hint"]) <= 150
                or not isinstance(row.get("region_hint"), str)
                or row.get("region_hint") not in REGIONS
                or type(row.get("edition_year_hint")) is not int):
            continue
        title, year = row["name_hint"], row["edition_year_hint"]
        years = {int(x) for x in YEAR.findall(normalized(title))}
        source_kind = row.get("year_source_review_only")
        if not ((years == {year} and source_kind == "TITLE")
                or (not years and source_kind == "UNVERIFIED_PROVIDER_START_DATE")):
            continue
        expected = sha256((row["source_url"] + "\n" + normalized(title) + "\n"
                           + str(year)).encode("utf-8")).hexdigest()[:20]
        if row.get("id") != "oa-" + expected:
            continue
        valid.append(row)
    return valid


def scan(state, today, fetch=None, catalog=None):
    if not isinstance(state, dict) or state.get("schema") != "grossesondes.source-watch.v1":
        raise ValueError("Invalid private source-watch state")
    date.fromisoformat(today)
    known = known_published_editions(catalog)
    known_signature = sha256(json.dumps(
        sorted(known), ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")).hexdigest()[:20]
    previous = state.get(STATE_KEY)
    if (isinstance(previous, dict)
            and previous.get("research_ruleset") == RESEARCH_RULESET
            and previous.get("known_catalog_digest") == known_signature
            and previous.get("as_of") == today
            and previous.get("status") == "SCANNED"
            and previous.get("review_only") is True
            and previous.get("publication_authorized") is False
            and previous.get("safe_to_publish") is False
            and previous.get("requests_attempted") == len(fixed_query_urls(today))
            and previous.get("requests_failed") == 0
            and isinstance(previous.get("leads"), list)
            and len(previous["leads"]) <= MAX_LEADS):
        return previous
    read = (lambda url: fetch_json(url, today)) if fetch is None else fetch
    found, already_published = {}, set()
    requests, failures = 0, 0
    for url in fixed_query_urls(today):
        requests += 1
        try:
            response = read(url)
            if (not isinstance(response, dict)
                    or type(response.get("total_count")) is not int
                    or not isinstance(response.get("results"), list)
                    or len(response["results"]) > PER_PAGE):
                raise ValueError("Malformed OpenData response")
            for row in response["results"]:
                lead = candidate(row, today)
                if lead is None:
                    continue
                identity = (published_identity(lead["name_hint"]),
                            lead["edition_year_hint"], lead["region_hint"])
                if identity in known:
                    already_published.add(lead["id"])
                    continue
                if lead["id"] not in found:
                    found[lead["id"]] = lead
        except (OSError, ValueError, TypeError, KeyError, UnicodeError, json.JSONDecodeError):
            failures += 1
    lead_rows = sorted(found.values(), key=lambda r: (r["name_hint"], r["source_url"]))[:MAX_LEADS]
    report = {
        "schema": SCHEMA, "as_of": today,
        "research_ruleset": RESEARCH_RULESET,
        "known_catalog_digest": known_signature,
        "already_published_leads_count": len(already_published),
        "status": "UNAVAILABLE" if failures == requests else "SCANNED" if not failures else "PARTIAL",
        "review_only": True, "safe_to_publish": False,
        "publication_authorized": False, "publications": 0,
        "requests_attempted": requests, "requests_failed": failures,
        "leads_count": len(lead_rows), "leads": lead_rows,
    }
    state[STATE_KEY] = report
    return report


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--intake", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    args = parser.parse_args()
    folder = args.intake
    today = datetime.now(ZoneInfo("Europe/Paris")).date().isoformat()
    state_path = folder / "source-watch-state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    result = scan(state, today, catalog=catalog)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
    (folder / "national-openagenda-research-review.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print("National OpenAgenda OPEN-DATA research only: requests="
          + str(result["requests_attempted"]) + ", unavailable="
          + str(result["requests_failed"]) + ", leads="
          + str(result["leads_count"]) + ", already_published="
          + str(result["already_published_leads_count"])
          + ", publications=0")


if __name__ == "__main__":
    main()
