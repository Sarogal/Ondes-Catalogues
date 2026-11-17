"""Bounded MPT Montpellier listing discovery. No publisher, token or state I/O.

The city-owned HTML listing supplies untrusted *links*, not occurrence proof.
Each exact child/family session must still be independently re-read from the
municipal detail page and later pass the #346 official/GPS/private gates.
"""
from datetime import date
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from ptitesondes_real_family_source_adapters import (
    parse_montpellier_mpt_detail, scope_proposals,
    FAMILY_TYPES,
)

SCHEMA = "ptitesondes.mpt_list_discovery_preview.v1"
LISTING_URL = "https://mpt.montpellier.fr/evenements"
MAX_HTML_BYTES = 1_500_000
MAX_LINKS = 80
MAX_PAGES = 24
MAX_OCCURRENCES = 500
_DETAIL_PATH = "/evenement/"


def trusted_detail(url):
    if not isinstance(url, str) or len(url) > 700:
        return False
    try:
        x = urlsplit(url)
        return (x.scheme == "https" and x.hostname == "mpt.montpellier.fr"
                and x.username is None and x.password is None
                and x.port in (None, 443) and not x.query and not x.fragment
                and x.path.startswith(_DETAIL_PATH)
                and len(x.path) > len(_DETAIL_PATH)
                and "//" not in x.path
                and not any(p in (".", "..") for p in x.path.split("/")))
    except ValueError:
        return False


class _Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hrefs = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "template", "svg"):
            self.hidden += 1
            return
        if tag == "a" and not self.hidden:
            attrs = dict(attrs)
            style = str(attrs.get("style") or "").casefold().replace(" ", "")
            if ("hidden" in attrs
                    or str(attrs.get("aria-hidden") or "").lower() == "true"
                    or "display:none" in style):
                return
            href = attrs.get("href")
            if isinstance(href, str):
                self.hrefs.append(href)

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "template", "svg"):
            self.hidden = max(0, self.hidden - 1)


def extract_detail_links(html, *, listing_url=LISTING_URL):
    if (not isinstance(html, str) or not 50 <= len(html.encode("utf-8")) <= MAX_HTML_BYTES
            or listing_url != LISTING_URL):
        raise ValueError("invalid_mpt_listing")
    parser = _Links()
    parser.feed(html)
    parser.close()
    links, seen = [], set()
    for href in parser.hrefs:
        if len(links) >= MAX_LINKS:
            break
        target = urljoin(LISTING_URL, href)
        if not trusted_detail(target) or target in seen:
            continue
        links.append(target)
        seen.add(target)
    return links


def discover_listing(listing_html, *, today, detail_get, page_limit=12):
    """Return lead objects privately to the caller; report is anonymous only.

    Bounded, separate fetch callback. No reading arbitrary links or external
    URLs, no page-derived trusted host/venue/GPS or approval. Any source fetch
    error is counted as HELD, not accepted as a valid empty programme.
    """
    if (type(today) is not date or not callable(detail_get)
            or type(page_limit) is not int or not 1 <= page_limit <= MAX_PAGES):
        raise ValueError("invalid_mpt_discovery_config")
    urls = extract_detail_links(listing_html)
    selected = urls[:page_limit]
    leads, failed, fetched, no_family = [], 0, 0, 0
    for link in selected:
        try:
            raw = detail_get(link)
            if (not isinstance(raw, str)
                    or len(raw.encode("utf-8")) > MAX_HTML_BYTES):
                raise ValueError("invalid_mpt_detail_html")
            items = parse_montpellier_mpt_detail(raw, link, today)
            fetched += 1
            if not items:
                no_family += 1
            leads.extend(items)
        except (OSError, UnicodeError, ValueError, TypeError):
            failed += 1
        if len(leads) > MAX_OCCURRENCES:
            raise ValueError("too_many_mpt_occurrences")
    outcomes = scope_proposals(leads, today)
    structurally_plausible = sum(
        x["structurally_plausible_for_independent_review"] for x in outcomes)
    report = {
        "schema": SCHEMA,
        "mode": "listing_discovery_readonly_not_admission",
        "listed_unique_detail_urls": len(urls),
        "selected_detail_pages": len(selected),
        "readable_detail_pages": fetched,
        "held_unreadable_details": failed,
        "details_without_explicit_family_session": no_family,
        "explicit_dated_occurrences": len(leads),
        "classified_family_occurrences": sum(
            lead["category"] in FAMILY_TYPES for lead in leads),
        "structurally_plausible_for_independent_review": structurally_plausible,
        "listing_truncated_at": MAX_LINKS if len(urls) >= MAX_LINKS else None,
        "selected_details_are_sample_only": len(urls) > len(selected),
        "trusted_organisers_authenticated": 0,
        "independent_geo_verified": 0,
        "private_approvals": 0,
        "publisher_connected": False,
        "publication_ready": False,
        "approval_granted_to_publisher": False,
        "public_writes": 0,
        "candidate_titles_and_urls_excluded_from_report": True,
    }
    return leads, report
