"""Bounded ticket -> professional profile -> website research, never publication proof.

Profiles are nominated by the event page, not a roster of venues or producers.
A profile must identify itself and link back to that exact ticket event.
Only the existing DNS-pinned HTTPS transport is used in production.
"""
from __future__ import annotations

import re
from pathlib import Path
import sys
from urllib.parse import urljoin, urlsplit

from dns_pinned_https import fetch_public_html, safe_public_url, OfficialHTTPStatusError
from national_openagenda_research import _valid_professional_hints, provider_title_matches
from source_qualification import Anchors, normalized, classify, visible_text
SCRIPTS = str(Path(__file__).resolve().parents[1] / 'scripts')
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
from grossesondes_generic_directory_edition import Heading

MAX_REQUESTS = 5
MAX_PROFILES = 3
MAX_WEBSITES = 4
EVENT_PATH = re.compile(r"/(?:[a-z]{2}/)?(events|festivals)/([a-z0-9-]{3,150})/?")
PROFILE_PATH = re.compile(r"/(?:[a-z]{2}/)?(?:venues|organizers|organisers|organisateurs|promoters|salles|lieux)/[a-z0-9-]{2,150}/?")
ALLOWED_WEBSITE_ROLES = {"UNKNOWN", "ORGANIZER_CANDIDATE", "VENUE", "INSTITUTION"}


def _path_identity(url):
    if safe_public_url(url) is None:
        return None
    parts = urlsplit(url)
    match = EVENT_PATH.fullmatch(parts.path)
    return (parts.hostname, match.group(1), match.group(2)) if match else None


def ticket_variants(url):
    """Bounded same-host event/festival route alternative, identity still required."""
    identity = _path_identity(url)
    if identity is None:
        return []
    # An event listing URL may be a festival listing URL on the same platform.
    # Never search other hosts or construct arbitrary paths from event text.
    part = urlsplit(url)
    if identity[1] == "events":
        alternative = part._replace(path=re.sub(r"/events/", "/festivals/", part.path, count=1)).geturl()
        return [url, alternative] if safe_public_url(alternative) else [url]
    return [url]


def _parse(html):
    if not isinstance(html, str) or not 0 < len(html) <= 650_000:
        return [], []
    headings, anchors = Heading(), Anchors()
    try:
        headings.feed(html)
        headings.close()
        anchors.feed(html)
        anchors.close()
    except (ValueError, TypeError, UnicodeError, RecursionError):
        return [], []
    return headings.headings, anchors.anchors


def _url(base, raw):
    if not isinstance(raw, str) or not raw or len(raw) > 500:
        return None
    try:
        result = urljoin(base, raw)
        return result if len(result) <= 500 and safe_public_url(result) else None
    except (ValueError, TypeError, UnicodeError):
        return None


def _event_profiles(html, url, title, year, diagnostic=None):
    if diagnostic is None:
        diagnostic = {}
    if not isinstance(html, str) or not 0 < len(html) <= 650_000:
        diagnostic['outcome'] = 'HTML_UNAVAILABLE_OR_SIZE_REJECTED'
        return None
    headings, anchors = _parse(html)
    if len(headings) != 1 or not provider_title_matches(headings[0], title, year):
        diagnostic['outcome'] = 'EVENT_HEADING_MISMATCH'
        diagnostic['heading_count'] = min(len(headings), 100)
        return None
    try:
        if str(year) not in visible_text(html).split():
            diagnostic['outcome'] = 'EVENT_YEAR_NOT_VISIBLE'
            return None
    except ValueError:
        diagnostic['outcome'] = 'VISIBLE_TEXT_REJECTED'
        return None
    found = []
    for raw, label, _prefix in anchors:
        link = _url(url, raw)
        if link is None or urlsplit(link).hostname != urlsplit(url).hostname:
            continue
        if PROFILE_PATH.fullmatch(urlsplit(link).path) is None:
            continue
        label = normalized(label)
        if not 2 <= len(label) <= 180 or any(link == item[0] for item in found):
            continue
        found.append((link, label))
        if len(found) >= MAX_PROFILES:
            break
    diagnostic['outcome'] = 'PROFILES_FOUND' if found else 'NO_VISIBLE_PROFILES'
    diagnostic['profile_count'] = len(found)
    return found


def _profile_websites(html, profile, label, ticket, diagnostic=None):
    if diagnostic is None:
        diagnostic = {}
    if not isinstance(html, str) or not 0 < len(html) <= 650_000:
        diagnostic['outcome'] = 'HTML_UNAVAILABLE_OR_SIZE_REJECTED'
        return []
    headings, anchors = _parse(html)
    if len(headings) != 1:
        diagnostic['outcome'] = 'PROFILE_HEADING_COUNT_MISMATCH'
        diagnostic['heading_count'] = min(len(headings), 100)
        return []
    identity = headings[0]
    # A card can append follower/event counts to the displayed profile name.
    if not identity or not (label == identity or re.fullmatch(
            re.escape(identity) + r" \d[0-9 ]*(?:followers|abonnes)(?: \d[0-9 ]*(?:events|evenements))?", label)):
        diagnostic['outcome'] = 'PROFILE_IDENTITY_MISMATCH'
        return []
    event_identity = _path_identity(ticket)
    links = [(_url(profile, raw), normalized(text)) for raw, text, _ in anchors]
    # Do not accept a profile with a different edition or an unrelated artist.
    if not any(_path_identity(link) == event_identity for link, _ in links if link):
        diagnostic['outcome'] = 'EXACT_EVENT_BACKLINK_ABSENT'
        return []
    found = []
    for link, text in links:
        if not link or urlsplit(link).hostname == urlsplit(profile).hostname:
            continue
        host = urlsplit(link).hostname
        if classify(link) not in ALLOWED_WEBSITE_ROLES:
            continue
        # Explicit website label or visible matching domain, not generic footer links.
        labels = {normalized(host), normalized(host.removeprefix("www.")),
                  "site officiel", "site web", "site internet", "website", "official website"}
        if text not in labels or link in found:
            continue
        found.append(link)
        if len(found) >= 2:
            break
    diagnostic['outcome'] = 'WEBSITES_FOUND' if found else 'NO_EXPLICIT_SAFE_WEBSITE'
    diagnostic['website_count'] = len(found)
    return found


def discover(hints, title, year, *, fetch=fetch_public_html, rate_limited_hosts=None):
    """Return only private research paths. No external website is fetched here."""
    result = {"status": "NO_PROFESSIONAL_PATH", "requests": 0, "websites": [],
              "review_only": True, "safe_to_publish": False, "publication_authorized": False,
              "diagnostics": []}
    if (not _valid_professional_hints(hints) or not isinstance(title, str)
            or not 7 <= len(title) <= 160 or type(year) is not int or not 2020 <= year <= 2049):
        return result
    visited = set()
    # One explicit 429 defers further requests to that origin for this pass.
    # A caller shares this set across dossiers; it is not publication evidence.
    if rate_limited_hosts is None:
        rate_limited_hosts = set()
    deferred = False

    def read(url, stage):
        nonlocal deferred
        if result["requests"] >= MAX_REQUESTS or url in visited:
            return None, None
        host = urlsplit(url).hostname
        if host in rate_limited_hosts:
            deferred = True
            return None, None
        visited.add(url)
        result["requests"] += 1
        diagnostic = {'stage': stage, 'outcome': 'FETCH_FAILED'}
        result['diagnostics'].append(diagnostic)
        try:
            return fetch(url), diagnostic
        except OfficialHTTPStatusError as exc:
            diagnostic['outcome'] = 'HTTP_STATUS_REJECTED'
            diagnostic['http_status'] = exc.status_code
            if exc.status_code == 429:
                rate_limited_hosts.add(host)
                deferred = True
        except (OSError, ValueError, TypeError, UnicodeError, KeyError):
            pass
        return None, diagnostic

    for link in hints["links"]:
        if link["field"] not in ("registration", "links"):
            continue
        for ticket in ticket_variants(link["url"]):
            page, diagnostic = read(ticket, 'TICKET_' + _path_identity(ticket)[1].upper())
            if page is None:
                continue
            profiles = _event_profiles(page, ticket, title, year, diagnostic)
            if profiles is None:
                continue
            result["status"] = "TICKET_IDENTITY_REVIEW_ONLY"
            if not profiles:
                continue
            for profile, label in profiles:
                profile_html, diagnostic = read(profile, 'PROFILE')
                if profile_html is None:
                    continue
                for site in _profile_websites(profile_html, profile, label, ticket, diagnostic):
                    if any(site == item["website_url"] for item in result["websites"]):
                        continue
                    result["websites"].append({"ticket_url": ticket, "profile_url": profile,
                        "website_url": site, "verified": False, "publication_authorized": False})
                    result["status"] = "PROFESSIONAL_WEBSITE_HINTS"
                    if len(result["websites"]) >= MAX_WEBSITES:
                        return result
            # Exact event already found. No alternate page or recursive traversal.
            if result["websites"]:
                return result
    if deferred and not result["websites"]:
        result["status"] = "PROFESSIONAL_RATE_LIMITED"
    return result
