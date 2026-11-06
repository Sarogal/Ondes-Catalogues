"""Read-only ticket-provider probes; no stock publication is authorized.

Only HTTPS links already discovered on the catalogue's registered organizer
page are eligible. Offers are hints for editorial review, never a trusted
ticketAvailability update.
"""
from datetime import date
import json
from urllib.parse import urlsplit

from official_ticket_links import provider_for_host
from structured_evidence import StructuredData, event_date, event_objects, root_name
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
