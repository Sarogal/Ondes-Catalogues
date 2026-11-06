"""Private schema.org organizer URL leads on already corroborated institution/venue pages.

The event's exact visible name/date are checked by source_qualification first.
Even a perfect JSON-LD match here remains LINK_ONLY; it cannot prove domain
control, add a published officialSite or enable a field update.
"""
from datetime import date
import re
from urllib.parse import urlsplit

from structured_evidence import StructuredData, event_objects, event_date

SOURCE_ROLES = {"INSTITUTION", "VENUE"}
CANDIDATE_ROLES = {"UNKNOWN", "ORGANIZER_CANDIDATE"}
ORGANIZATION_TYPES = {"organization", "ngo", "localbusiness"}
MAX_EVENTS = 100
MAX_LINKS = 4


def exact_organizer_alias(name, aliases, normalize):
    """Exact legal or parenthesized name, allowing the label 'Association'."""
    if not isinstance(name, str):
        return False
    normalized = normalize(name)
    normalized = re.sub(r"^(?:association|l association) ", "", normalized)
    return bool(normalized) and normalized in aliases


def structured_organizer_links(html, source_url, edition_name, start_date,
                               end_date, aliases, clean_url, classify, normalize):
    """Return bounded private URLs from event.organizer.url, never proof.

    The event must be separately identified in the JSON-LD by *exact* festival
    name (optionally with the edition year) and starting date. This prevents a
    global site header Organization URL or unrelated event in @graph from
    supplying a candidate for the current edition.
    """
    if (not isinstance(html, str) or len(html) > 650_000
            or not isinstance(aliases, list) or not aliases
            or classify(source_url) not in SOURCE_ROLES):
        return []
    try:
        start = date.fromisoformat(start_date)
    except (TypeError, ValueError):
        return []
    if not isinstance(edition_name, str) or not normalize(edition_name):
        return []
    try:
        expected_end = date.fromisoformat(end_date or start_date)
    except (TypeError, ValueError):
        return []
    if expected_end < start:
        return []
    names = {normalize(edition_name), normalize(edition_name + " " + str(start.year))}
    parser = StructuredData()
    parser.feed(html)
    source_host = urlsplit(source_url).hostname
    found = []
    observed = 0
    for doc in parser.documents[:25]:
        for event in event_objects(doc):
            observed += 1
            if observed > MAX_EVENTS:
                return found
            if (normalize(event.get("name")) not in names
                    or event_date(event.get("startDate")) != start):
                continue
            end = event_date(event.get("endDate"))
            if end is not None and (end != expected_end or (end - start).days > 31):
                continue
            organizers = event.get("organizer")
            if not isinstance(organizers, list):
                organizers = [organizers]
            for org in organizers[:6]:
                if not isinstance(org, dict):
                    continue
                kinds = org.get("@type")
                if isinstance(kinds, str):
                    kinds = [kinds]
                if kinds is not None and (not isinstance(kinds, list) or not any(
                        isinstance(k, str) and k.rsplit("/", 1)[-1].lower() in ORGANIZATION_TYPES
                        for k in kinds)):
                    continue
                if not exact_organizer_alias(org.get("name"), aliases, normalize):
                    continue
                target = clean_url(org.get("url"))
                if not target or classify(target) not in CANDIDATE_ROLES:
                    continue
                host = urlsplit(target).hostname
                if (not host or host == source_host
                        or host.endswith("." + source_host)
                        or source_host.endswith("." + host)):
                    continue
                if target not in found:
                    found.append(target)
                if len(found) >= MAX_LINKS:
                    return found
    return found
