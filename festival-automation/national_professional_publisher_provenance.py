"""Independent public OpenData provenance for professional event proofs.

The only private selector accepted is a canonical OpenAgenda event URL.
The network origin, fields, query structure and response limits are fixed.
No ticket, profile or professional URL from a private patch is fetched.
"""
import json
import ssl
from urllib.parse import urlencode
from dns_pinned_https import DNSPinnedHTTPSConnection, fetch_public_html
from national_openagenda_research import (
    HOST, ENDPOINT, SELECT, MAX_BYTES, _canonical_url, candidate,
    provider_title_matches,
)
from national_professional_profile_discovery import discover
from national_professional_official_detail import examine, examine_openagenda_venue
from national_cultural_venue_discovery import cultural_detail


def lookup_path(event):
    if not _canonical_url(event):
        return None
    return ENDPOINT + "?" + urlencode({
        "select": SELECT, "where": "canonicalurl = '" + event + "'",
        "limit": 2,
    })


def fetch_record(event):
    path = lookup_path(event)
    if path is None:
        raise ValueError("Invalid canonical OpenAgenda event")
    conn = DNSPinnedHTTPSConnection(HOST, port=443, timeout=12,
                                    context=ssl.create_default_context())
    try:
        conn.request("GET", path, headers={
            "Host": HOST, "User-Agent": "GrossesOndesProfessionalProof/1.0",
            "Accept": "application/json", "Accept-Encoding": "identity",
        })
        response = conn.getresponse()
        raw = response.read(MAX_BYTES + 1)
        if (response.status != 200 or len(raw) > MAX_BYTES
                or response.getheader("content-type", "").split(";", 1)[0].strip().lower()
                   != "application/json"
                or response.getheader("content-encoding", "identity").lower() != "identity"):
            raise ValueError("Unusable public OpenData response")
        return json.loads(raw.decode("utf-8"))
    finally:
        conn.close()


def prove(event, title, today, *, record_fetch=fetch_record, fetch=fetch_public_html):
    if (lookup_path(event) is None or not isinstance(title, str)
            or not 8 <= len(title) <= 160):
        return []
    try:
        year = int(title.rsplit(" ", 1)[-1])
        data = record_fetch(event)
        if (not isinstance(data, dict) or type(data.get("total_count")) is not int
                or data["total_count"] != 1 or not isinstance(data.get("results"), list)
                or len(data["results"]) != 1):
            return []
        lead = candidate(data["results"][0], today)
        if (lead is None or lead["source_url"] != event
                or lead["edition_year_hint"] != year
                or not provider_title_matches(lead["name_hint"], title, year)):
            return []
        research = discover(lead["professional_source_hints_review_only"],
                            title, year, fetch=fetch)
        report = examine(research, title, year, today, fetch=fetch)
        if report["status"] == "NO_OFFICIAL_DETAIL_PROOF":
            report = examine_openagenda_venue(lead, title, year, today, fetch=fetch)
        if report["status"] == "NO_OFFICIAL_DETAIL_PROOF":
            report = cultural_detail(lead, title, year, today, fetch=fetch)
        return report["proofs"] if report["status"] == "OFFICIAL_DETAIL_PROOF_REVIEW_ONLY" else []
    except (OSError, ValueError, TypeError, UnicodeError, KeyError, RecursionError):
        return []
