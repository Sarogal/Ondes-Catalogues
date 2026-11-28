"""Read-only ticket-provider probes; no stock publication is authorized.

Only HTTPS links already discovered on the catalogue's registered organizer
page are eligible. Offers are hints for editorial review, never a trusted
ticketAvailability update.
"""
from datetime import date
import json
import re
from urllib.parse import urlsplit

from official_ticket_links import provider_for_host
from official_ticket_offer_links import structured_offer_links, visible_year_ticket_links
from dns_pinned_https import safe_public_url, fetch_public_html
from structured_evidence import StructuredData, event_date, event_objects, root_name, normalize
from ticket_status_watch import categories, schema_term, SENSITIVE


def _valid_prior_day(raw, today_day):
    try:
        day = date.fromisoformat(raw)
    except (TypeError, ValueError):
        return date.min
    return day if day <= today_day else date.min


def checked_vendor_day(record, url, today_day):
    """Read both the legacy single-link state and the per-URL review history."""
    if not isinstance(record, dict):
        return date.min
    urls = record.get("urls")
    if isinstance(urls, dict) and url in urls:
        return _valid_prior_day(urls[url], today_day)
    if record.get("ticket_url") == url:
        return _valid_prior_day(record.get("lastChecked"), today_day)
    return date.min


def select_provider_checks(leads, editions, today, limit=3, last_checked=None):
    """Rotate both festival editions and provider URLs, always review-only.

    One request at most per festival per pass. Within an edition, prefer never
    checked vendor URLs, then oldest attempts. When equally unchecked, exact
    edition-bound JSON-LD offer URLs beat generic HTML anchors. Across editions,
    the festival's last attempted date is used to retain national coverage.
    """
    if last_checked is None:
        last_checked = {}
    if not isinstance(leads, list) or not isinstance(last_checked, dict) or not 1 <= limit <= 6:
        raise ValueError("paramètres invalides")
    today_day = date.fromisoformat(today)
    grouped, seen = {}, set()
    for lead in leads:
        if not isinstance(lead, dict):
            continue
        edition = editions.get(lead.get("slug"))
        if not isinstance(edition, dict) or (edition.get("officialSite") != lead.get("source_url")
                or lead.get("verification_status") != "LINK_ONLY"
                or lead.get("publication_authorized") is not False):
            continue
        url = lead.get("ticket_url")
        if not isinstance(url, str) or not url.startswith("https://"):
            continue
        if provider_for_host(urlsplit(url).hostname) != lead.get("provider"):
            continue
        start = event_date(edition.get("startDate"))
        end = event_date(edition.get("endDate")) or start
        if not start or not end or start > end or end < today_day:
            continue
        # The same canonical URL can appear several times in an organizer's
        # markup. Keep one copy, favoring a precisely edition-bound offer.
        url_key = (lead["slug"], url)
        if url_key in seen:
            other = grouped.get(lead["slug"], [])
            if lead.get("link_origin") == "schema_org_offer_url":
                for index, item in enumerate(other):
                    if item[0]["ticket_url"] == url:
                        other[index] = (lead, edition, start, end)
                        break
            continue
        seen.add(url_key)
        grouped.setdefault(lead["slug"], []).append((lead, edition, start, end))

    ranked = []
    for slug, group in grouped.items():
        record = last_checked.get(slug)
        lead, edition, start, end = min(group, key=lambda item: (
            checked_vendor_day(record, item[0]["ticket_url"], today_day),
            0 if item[0].get("link_origin") == "schema_org_offer_url" else 1,
            item[0]["ticket_url"],
        ))
        attempted = _valid_prior_day(
            record.get("lastChecked") if isinstance(record, dict) else None,
            today_day,
        )
        ranked.append((attempted, end, start, slug, lead, edition))
    # An edition with several links never consumes more than one slot.
    ranked.sort(key=lambda row: (row[0], row[1], row[2], row[3]))
    return [(lead, edition) for _, _, _, _, lead, edition in ranked[:limit]]

def provider_snapshot(html, edition):
    """Find exact event name/dates in vendor JSON-LD; never certify sales."""
    empty = {"result": "UNVERIFIED", "categories_review_only": []}
    if not isinstance(html, str) or not 0 < len(html) <= 650_000:
        return empty
    start = event_date(edition.get("startDate"))
    end = event_date(edition.get("endDate")) or start
    name = root_name(edition.get("name", ""))
    if not start or not end or start > end or not 3 <= len(name) <= 120:
        return empty
    parser = StructuredData()
    parser.feed(html)
    matched = []
    count = 0
    for document in parser.documents[:25]:
        for event in event_objects(document):
            count += 1
            if count > 100:
                return empty
            title = event.get("name")
            if not isinstance(title, str) or root_name(title) != name:
                continue
            start_on_page = event_date(event.get("startDate"))
            end_on_page = event_date(event.get("endDate")) or start_on_page
            if start_on_page != start or end_on_page != end:
                continue
            if schema_term(event.get("eventStatus"), SENSITIVE):
                matched.append({"result": "SENSITIVE_REVIEW", "categories_review_only": []})
                continue
            offers = categories(event)
            if offers is None or len(offers) > 12:
                return {"result": "CONFLICT", "categories_review_only": []}
            matched.append({"result": "EXPLICIT_CATEGORY_HINTS" if offers else "MATCHED_NO_STOCK",
                            "categories_review_only": offers})
    if not matched:
        return empty
    signatures = {json.dumps(row, sort_keys=True, ensure_ascii=False) for row in matched}
    return matched[0] if len(signatures) == 1 else {"result": "CONFLICT", "categories_review_only": []}



def provider_edition_location(html, edition):
    """Review-only exact event location, never the organizer's postal address.

    Called only by the existing bounded vendor rotation. This result is a
    research clue; the Publisher must separately reprove link provenance.
    """
    if (not isinstance(html, str) or not 0 < len(html.encode("utf-8")) <= 650_000
            or not isinstance(edition, dict)):
        return None
    start = event_date(edition.get("startDate"))
    end = event_date(edition.get("endDate"))
    name = root_name(edition.get("name", ""))
    if not start or not end or start > end or not 5 <= len(name) <= 120:
        return None
    def term(value):
        return str(value).rsplit("/", 1)[-1].casefold()
    def label(value):
        if (not isinstance(value, str) or not 2 <= len(value.strip()) <= 120
                or not re.fullmatch(r"[\wÀ-ÿ .’'\-]+", value, re.UNICODE)
                or not any(c.isalpha() for c in value)):
            return None
        return " ".join(value.split())
    try:
        parser = StructuredData()
        parser.feed(html)
        parser.close()
        found, count = [], 0
        for document in parser.documents[:25]:
            for event in event_objects(document):
                count += 1
                if count > 100:
                    return None
                title = event.get("name")
                if not isinstance(title, str) or root_name(title) != name:
                    continue
                if (event_date(event.get("startDate")) != start
                        or (event_date(event.get("endDate")) or
                            event_date(event.get("startDate"))) != end):
                    continue
                years = set(re.findall(r"\b20[2-4]\d\b", title))
                if years - {str(start.year)} or schema_term(event.get("eventStatus"), SENSITIVE):
                    return None
                place = event.get("location")
                if not isinstance(place, dict) or term(place.get("@type")) != "place":
                    return None
                address = place.get("address")
                if not isinstance(address, dict) or term(address.get("@type")) != "postaladdress":
                    return None
                country = address.get("addressCountry")
                if isinstance(country, dict):
                    country = country.get("name")
                if not isinstance(country, str) or normalize(country) not in ("fr", "france"):
                    return None
                city = label(address.get("addressLocality"))
                venue = label(place.get("name"))
                postcode = address.get("postalCode")
                if (not city or not venue or not isinstance(postcode, str)
                        or not re.fullmatch(r"\d{5}", postcode)):
                    return None
                if edition.get("city") and normalize(edition["city"]) != normalize(city):
                    return None
                found.append({"city": city, "venue": venue, "postalCode": postcode})
        if not found:
            return None
        signatures = {(normalize(x["city"]), normalize(x["venue"]), x["postalCode"])
                      for x in found}
        if len(signatures) != 1:
            return None
        return found[0]
    except (ValueError, TypeError, UnicodeError, RecursionError):
        return None


def independently_linked_location(edition, today, *, fetch=fetch_public_html):
    """Reprove a vendor location from a signed edition, without trusting leads.

    Caller must supply an already published, signed edition. An exact
    current Event.offers.url or an explicit year-labelled ticket anchor with
    the matching edition slug on its freshly fetched official page is eligible.
    No private URL, guessed vendor path, profile search or saved HTML accepted.
    This contract is still review-only; it grants no publication authority.
    """
    if not isinstance(edition, dict):
        return None
    site = edition.get("officialSite")
    start, end = event_date(edition.get("startDate")), event_date(edition.get("endDate"))
    try:
        day = date.fromisoformat(today)
        if (not site or safe_public_url(site) != site or provider_for_host(urlsplit(site).hostname)
                or not start or not end or not day <= start <= end
                or edition.get("cancelled") is True):
            return None
        root = fetch(site)
        # Reject ambiguity rather than choosing one seller arbitrarily.
        links = structured_offer_links(root, site, edition,
                                       lambda url: safe_public_url(url) == url, limit=2)
        visible = visible_year_ticket_links(root, site, edition,
                                            lambda url: safe_public_url(url) == url)
        targets = {link["ticket_url"] for link in links} | set(visible)
        if len(targets) != 1:
            return None
        target = next(iter(targets))
        if safe_public_url(target) != target:
            return None
        location = provider_edition_location(fetch(target), edition)
        if location is None:
            return None
        return {"source_url": site, "ticket_url": target,
                "edition_location_review_only": location,
                "publication_authorized": False}
    except (OSError, TimeoutError, ValueError, TypeError, UnicodeError, KeyError, RecursionError):
        return None


def provider_conflict_reason(snapshot, official_observation=None):
    """Private safety veto, not a vendor confirmation or ticket proof.

    Only an exact event/date vendor JSON-LD match can trigger a veto.
    HTTP errors, JavaScript-only pages and missing structured stock are
    unknown: none of them mean sold out or in stock.
    """
    if not isinstance(snapshot, dict):
        return None
    result = snapshot.get("result")
    if result == "SENSITIVE_REVIEW":
        return "VENDOR_SENSITIVE_REVIEW"
    if result == "CONFLICT":
        return "VENDOR_STRUCTURED_CONFLICT"
    if result != "EXPLICIT_CATEGORY_HINTS" or not isinstance(official_observation, dict):
        return None
    official = official_observation.get("ticket_categories")
    vendor = snapshot.get("categories_review_only")
    if not isinstance(official, list) or not isinstance(vendor, list):
        return None
    from structured_evidence import normalize
    named = {
        normalize(item["category"]): item["availability"]
        for item in official
        if isinstance(item, dict) and isinstance(item.get("category"), str)
        and isinstance(item.get("availability"), str)
    }
    for item in vendor:
        if not isinstance(item, dict):
            continue
        category, availability = item.get("category"), item.get("availability")
        if not isinstance(category, str) or not isinstance(availability, str):
            continue
        key = normalize(category)
        if key in named and named[key] != availability:
            return "CATEGORY_DISAGREEMENT"
    return None
