"""Private professional-site detail research; no publication permission.

A professional profile nominates a host, never a date. Follow exact event
links from that host's visible programme instead of parsing all the dates
in its calendar as one festival. The detail must explicitly identify the
festival, prove the edition and link to the very same ticket event.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit, urljoin

from dns_pinned_https import fetch_public_html, safe_public_url
from national_professional_profile_discovery import _path_identity, ALLOWED_WEBSITE_ROLES
from grossesondes_generic_directory_edition import Heading, verify_primary, ROCK_METAL_PUNK_GENRES
from grossesondes_venue_reciprocal_edition import safe_root, safe_link, anchor_rows, visible_content
from source_qualification import normalized, classify

MAX_PAGES = 12
MAX_SITES = 4
MAX_PAGES_PER_SITE = 4


def _ticket_backlink(html, page, ticket):
    identity = _path_identity(ticket)
    if identity is None:
        return False
    for href, label, _ in anchor_rows(html):
        try:
            if _path_identity(urljoin(page, href)) == identity:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _detail_dates(html, page, title, year, today, ticket):
    headings = Heading()
    headings.feed(html)
    headings.close()
    brand = normalized(title.rsplit(" ", 1)[0])
    if len(headings.headings) != 1 or headings.headings[0] not in (
            brand, normalized(title)):
        return None
    # Genre in the brand alone is not proof of musical scope.
    words = normalized(visible_content(html))
    outside = re.sub(r"(?<![a-z0-9])" + re.escape(brand) + r"(?![a-z0-9])", " ", words)
    if not ROCK_METAL_PUNK_GENRES.search(outside):
        return None
    if not _ticket_backlink(html, page, ticket):
        return None
    return verify_primary(html, title, year, today)


def _links(html, page, root, title):
    brand = normalized(title.rsplit(" ", 1)[0])
    exact, indexes = set(), set()
    for href, label, _ in anchor_rows(html):
        link = safe_link(href, page, root)
        if link is None:
            continue
        words = normalized(label)
        if re.search(r"(?<![a-z0-9])" + re.escape(brand) + r"(?![a-z0-9])", words):
            exact.add(link)
        elif re.search(r"\b(?:agenda|calendrier|programmation|concerts|events|programme)\b", words):
            indexes.add(link)
    return sorted(exact), sorted(indexes - exact)


def examine(research, title, year, today, *, fetch=fetch_public_html):
    """Bounded independent detail-page reads; results stay private hints."""
    result = {"status": "NO_OFFICIAL_DETAIL_PROOF", "requests": 0, "proofs": [],
              "review_only": True, "safe_to_publish": False, "publication_authorized": False}
    if (not isinstance(research, dict) or research.get("status") != "PROFESSIONAL_WEBSITE_HINTS"
            or research.get("review_only") is not True
            or research.get("safe_to_publish") is not False
            or research.get("publication_authorized") is not False
            or not isinstance(research.get("websites"), list)
            or not 0 < len(research["websites"]) <= MAX_SITES
            or not isinstance(title, str) or type(year) is not int
            or not re.fullmatch(r".{7,150} " + str(year), title)):
        return result
    cache = {}
    def read(url):
        if url in cache:
            return cache[url]
        if result["requests"] >= MAX_PAGES:
            return None
        result["requests"] += 1
        try:
            html = fetch(url)
            anchor_rows(html)
            cache[url] = html
        except (OSError, ValueError, TypeError, UnicodeError, KeyError, RecursionError):
            cache[url] = None
        return cache[url]
    # Reserve an equal share of network reads for every nominated site.
    # A large producer calendar must not starve a co-organizing venue.
    site_budget = min(MAX_PAGES_PER_SITE, MAX_PAGES // len(research["websites"]))
    for item in research["websites"]:
        if (not isinstance(item, dict) or item.get("verified") is not False
                or item.get("publication_authorized") is not False):
            continue
        site, ticket = item.get("website_url"), item.get("ticket_url")
        if (safe_public_url(site) is None or _path_identity(ticket) is None
                or classify(site) not in ALLOWED_WEBSITE_ROLES):
            continue
        root = "https://" + urlsplit(site).hostname + "/"
        if safe_root(root) is None:
            continue
        pending = [(0, site)]
        if site != root:
            pending.append((1, root))
        seen, proofs, unresolved = set(), [], False
        site_requests_start = result["requests"]
        while pending:
            rank, page = pending.pop(0)
            if page in seen:
                continue
            if page not in cache and (result["requests"] >= MAX_PAGES
                    or result["requests"] - site_requests_start >= site_budget):
                unresolved = unresolved or rank == 0
                break
            seen.add(page)
            html = read(page)
            if html is None:
                unresolved = unresolved or (rank == 0 and page != site)
                continue
            try:
                dates = _detail_dates(html, page, title, year, today, ticket)
                if dates:
                    proofs.append((page, tuple(dates)))
                elif rank == 0 and page != site:
                    unresolved = True
                exact, indexes = _links(html, page, root, title)
                pending.extend((0, x) for x in exact if x not in seen)
                if not proofs and rank != 1:
                    pending.extend((1, x) for x in indexes[:2] if x not in seen)
                best = {}
                for priority, x in pending:
                    if x not in seen:
                        best[x] = min(priority, best.get(x, priority))
                pending = sorted((priority, x) for x, priority in best.items())
                if sum(priority == 0 for priority, _ in pending) > MAX_PAGES:
                    unresolved = True
                    break
            except (ValueError, TypeError, UnicodeError, KeyError, RecursionError):
                unresolved = True
                break
        if unresolved or any(priority == 0 and x not in seen for priority, x in pending):
            continue
        if not proofs or len({dates for _, dates in proofs}) != 1:
            continue
        page, dates = sorted(proofs)[0]
        result["proofs"].append({"official_detail_url": page, "ticket_url": ticket,
                                 "start_date": dates[0], "end_date": dates[1],
                                 "publication_authorized": False})
    if len({(p["start_date"], p["end_date"]) for p in result["proofs"]}) > 1:
        result["proofs"] = []
        result["status"] = "CONFLICTING_OFFICIAL_DETAILS"
    elif result["proofs"]:
        result["status"] = "OFFICIAL_DETAIL_PROOF_REVIEW_ONLY"
    return result
