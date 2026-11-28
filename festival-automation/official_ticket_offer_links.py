"""Strict organizer-page JSON-LD offer links for festival ticket review only.

The organizer's registered officialSite is the sole provenance. Provider URLs
only enter a private lead report: they NEVER establish stock, ticket prices or
publication permission. This reader makes no HTTP requests.
"""
from urllib.parse import urljoin, urlsplit

from official_ticket_links import provider_for_host
from structured_evidence import StructuredData, event_date, event_objects, root_name

SENSITIVE = {"eventcancelled", "eventpostponed", "eventrescheduled"}


def structured_offer_links(html, organizer_url, edition, permitted_url, limit=6):
    """Accept an offer.url only when the event name and date range are exact."""
    if (not isinstance(html, str) or len(html) > 650_000
            or not permitted_url(organizer_url) or not isinstance(edition, dict)
            or not 1 <= limit <= 12):
        return []
    start = event_date(edition.get("startDate"))
    end = event_date(edition.get("endDate")) or start
    target = root_name(edition.get("name", ""))
    if not start or not end or end < start or len(target) < 5:
        return []

    parser = StructuredData()
    parser.feed(html)
    seen, result = set(), []
    inspected = 0
    for document in parser.documents[:25]:
        for event in event_objects(document):
            inspected += 1
            if inspected > 100:
                return []
            if root_name(event.get("name", "")) != target:
                continue
            first = event_date(event.get("startDate"))
            last = event_date(event.get("endDate")) or first
            if first != start or last != end:
                continue
            status = str(event.get("eventStatus") or "").rsplit("/", 1)[-1].casefold()
            if status in SENSITIVE:
                continue
            offers = event.get("offers", [])
            if isinstance(offers, dict):
                offers = [offers]
            if not isinstance(offers, list) or len(offers) > 40:
                continue
            for offer in offers:
                if not isinstance(offer, dict):
                    continue
                raw = offer.get("url")
                if not isinstance(raw, str) or not 0 < len(raw) <= 2048:
                    continue
                if any(ord(character) < 32 for character in raw):
                    continue
                try:
                    candidate = urljoin(organizer_url, raw.strip())
                    parsed = urlsplit(candidate)
                    vendor = provider_for_host(parsed.hostname)
                except (TypeError, ValueError):
                    continue
                if not vendor or not permitted_url(candidate):
                    continue
                clean = parsed._replace(query="", fragment="").geturl()
                if not permitted_url(clean) or parsed.path in ("", "/") or clean in seen:
                    continue
                seen.add(clean)
                result.append({
                    "ticket_url": clean,
                    "provider": vendor,
                    "verification_status": "LINK_ONLY",
                    "publication_authorized": False,
                    "link_origin": "schema_org_offer_url",
                })
                if len(result) >= limit:
                    return result
    return result


def visible_year_ticket_links(html, organizer_url, edition, permitted_url):
    """Explicit current-year ticket label and matching event slug, discovery only.

    The vendor still has to independently prove the full signed date range
    and event identity. Never accept a generic ticket button or hidden link.
    """
    import re
    from source_qualification import Anchors
    from structured_evidence import normalize, artist_key
    if (not isinstance(html, str) or not 0 < len(html) <= 650_000
            or not isinstance(edition, dict) or not permitted_url(organizer_url)):
        return []
    start = event_date(edition.get("startDate"))
    end = event_date(edition.get("endDate"))
    brand = artist_key(root_name(edition.get("name", "")))
    if not start or not end or start.year != end.year or len(brand) < 5:
        return []
    class VisibleTickets(Anchors):
        def handle_starttag(self, tag, attrs):
            style = dict(attrs).get("style") or ""
            if re.search(r"visibility\s*:\s*hidden", style, re.I):
                attrs = list(attrs) + [("hidden", None)]
            super().handle_starttag(tag, attrs)
    parser = VisibleTickets()
    parser.feed(html)
    parser.close()
    found = set()
    for raw, label, _ in parser.anchors:
        if not re.fullmatch(r"(?:billetterie|tickets|ticket office|billets)\s+" +
                            str(start.year), normalize(label)):
            continue
        if not isinstance(raw, str) or not 0 < len(raw) <= 500:
            continue
        try:
            url = urljoin(organizer_url, raw)
            parts = urlsplit(url)
            slug = parts.path.rstrip("/").rsplit("/", 1)[-1]
            if (not provider_for_host(parts.hostname) or not permitted_url(url)
                    or "%" in parts.path or ".." in parts.path.split("/")
                    or not re.fullmatch(r"[A-Za-z0-9-]+", slug)
                    or artist_key(slug) != brand + str(start.year)):
                continue
            found.add(url)
        except (ValueError, TypeError, UnicodeError):
            continue
    return sorted(found)[:2]
