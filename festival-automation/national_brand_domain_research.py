"""Bounded brand-domain research for national festival pass leads.

A guessed domain is never a trusted URL. It is inspected with the existing
DNS-pinned transport and must pass first-party identity/edition checks.
This research neither publishes nor promotes a domain to an approved list.
"""
from datetime import date
from pathlib import Path
import re
import sys

from dns_pinned_https import safe_public_url, fetch_public_html
from national_openagenda_research import pass_edition_title
from source_qualification import normalized
SCRIPTS = str(Path(__file__).resolve().parents[1] / "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
from grossesondes_first_party_direct_edition import (
    GENERIC_WORDS, verify_first_party_claims,
)


def brand_domain_candidate(name, year):
    title = pass_edition_title(name, year)
    if title is None:
        return None
    core = title.rsplit(" ", 1)[0]
    if re.fullmatch(r"[\wÀ-ÿ '-]+", core) is None:
        return None
    tokens = normalized(core).split()
    if (not 1 <= len(tokens) <= 5
            or any(re.fullmatch(r"[a-z0-9]+", token) is None for token in tokens)
            or not any(len(token) >= 5 and token not in GENERIC_WORDS
                       for token in tokens)):
        return None
    brand = "".join(tokens)
    if not 9 <= len(brand) <= 45 or not re.search(r"[a-z]", brand):
        return None
    # One bounded research guess, no retries, redirects or alternate hosts.
    site = "https://" + brand + ".fr/"
    return (title, site) if safe_public_url(site) == site else None


def research_brand_domain(lead, title, year, today, *, fetch=fetch_public_html):
    report = {"status": "NO_BRAND_DOMAIN_CANDIDATE", "review_only": True,
              "publication_authorized": False, "safe_to_publish": False,
              "site_review_only": None, "dates_review_only": None}
    if (not isinstance(lead, dict) or lead.get("review_only") is not True
            or lead.get("safe_to_publish") is not False
            or lead.get("publication_authorized") is not False
            or lead.get("observed_at") != today
            or lead.get("edition_year_hint") != year
            or year < date.fromisoformat(today).year):
        return report
    candidate = brand_domain_candidate(lead.get("name_hint"), year)
    if candidate is None or normalized(candidate[0]) != normalized(title):
        return report
    canonical, site = candidate
    claims = verify_first_party_claims(site, canonical, today, fetch=fetch)
    if claims is None:
        report["status"] = "BRAND_DOMAIN_OR_EDITION_UNPROVEN"
        return report
    dates, city = claims
    report.update(status="FIRST_PARTY_BRAND_EDITION_REVIEW_ONLY",
                  site_review_only=site, dates_review_only=list(dates),
                  city_review_only=city)
    return report
