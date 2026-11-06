"""Bounded, private discovery of festival-specific websites from primary event pages.

Only inspected *after* source_qualification has corroborated the edition's
visible name and date on an institution or venue page. A hyperlink is never
proof of organizer ownership. This module performs NO network requests.
"""
from datetime import date, timedelta
import re
from organizer_domain_evidence import _source_family
from urllib.parse import urlsplit

from structured_evidence import StructuredData, event_objects, event_date

SOURCE_ROLES = {"INSTITUTION", "VENUE"}
TARGET_ROLES = {"UNKNOWN", "ORGANIZER_CANDIDATE"}
MAX_EVENT_OBJECTS = 100
MAX_LINKS_PER_SOURCE = 4
MAX_QUEUE = 12
MAX_QUEUE_PER_EDITION = 3
MAX_AGE_DAYS = 21


def _outside_source(candidate, source_url):
    source_host = (urlsplit(source_url).hostname or "").lower()
    target_host = (urlsplit(candidate).hostname or "").lower()
    return (bool(source_host and target_host)
            and _source_family(source_host) != _source_family(target_host)
            and not (target_host == source_host
                     or target_host.endswith("." + source_host)
                     or source_host.endswith("." + target_host)))


def event_website_links(html, source_url, edition_name, start_date, end_date,
                        clean_url, classify, normalize):
    """Event.url/sameAs research hints; exact name + dates required in JSON-LD.

    A different event on the same institutional page cannot supply links.
    No promotion, no crawling, no trust in social/ticketing/third-party URLs.
    """
    if (not isinstance(html, str) or len(html) > 650_000
            or classify(source_url) not in SOURCE_ROLES
            or not isinstance(edition_name, str)):
        return []
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date or start_date)
    except (ValueError, TypeError):
        return []
    if end < start or (end - start).days > 31:
        return []
    edition = normalize(edition_name)
    if len(edition) < 7:
        return []
    allowed_names = {edition, normalize(edition_name + " " + str(start.year))}
    parser = StructuredData()
    parser.feed(html)
    found = []
    seen = set()
    inspected = 0
    for document in parser.documents[:25]:
        for event in event_objects(document):
            inspected += 1
            if inspected > MAX_EVENT_OBJECTS:
                return found
            if (normalize(event.get("name") or "") not in allowed_names
                    or event_date(event.get("startDate")) != start):
                continue
            event_end = event_date(event.get("endDate"))
            if event_end is not None and event_end != end:
                continue
            for field in ("url", "sameAs"):
                values = event.get(field)
                if not isinstance(values, list):
                    values = [values]
                for raw in values[:6]:
                    target = clean_url(raw)
                    if (not target or target in seen
                            or classify(target) not in TARGET_ROLES
                            or not _outside_source(target, source_url)):
                        continue
                    seen.add(target)
                    found.append({"candidate_url": target,
                                  "evidence_format": "SCHEMA_ORG_EVENT_" + field.upper()})
                    if len(found) >= MAX_LINKS_PER_SOURCE:
                        return found
    return found


def visible_event_website_links(anchors, source_url, edition_name, start_date,
                                clean_url, classify, normalize):
    """Explicit festival website links from a corroborated venue/city page.

    An anchor must be locally tied to the exact edition name AND visibly
    described as a website or official site. This produces a research hint
    only, not a statement that the target is organizer-controlled.

    Anchors are already filtered for hidden elements by the caller's
    existing Anchors parser; raw hidden markup is never inspected here.
    """
    if (classify(source_url) not in SOURCE_ROLES
            or not isinstance(edition_name, str)
            or not isinstance(anchors, list)):
        return []
    edition = normalize(edition_name)
    try:
        expected_year = date.fromisoformat(start_date).year
    except (ValueError, TypeError):
        return []
    if len(edition) < 7:
        return []
    exact = re.compile(r"(?<![a-z0-9])" + re.escape(edition) + r"(?![a-z0-9])")
    markers = ("site officiel", "site internet", "site web",
               "site du festival", "site de l evenement", "site de l event")
    found = []
    for row in anchors[:500]:
        if not isinstance(row, (tuple, list)) or len(row) != 3:
            continue
        raw, label, prefix = row
        if not isinstance(label, str) or not isinstance(prefix, str):
            continue
        label_key, prefix_key = normalize(label), normalize(prefix)
        local_years = {int(y) for y in re.findall(
            r"(?<![0-9])20[2-4][0-9](?![0-9])", label_key + " " + prefix_key)}
        if local_years and local_years != {expected_year}:
            continue
        # Edition and website attribution must occur in the very same
        # visible anchor or its immediate, local block prefix.
        if (not (exact.search(label_key) or exact.search(prefix_key))
                or not any(word in label_key or word in prefix_key for word in markers)):
            continue
        target = clean_url(raw)
        if (not target or classify(target) not in TARGET_ROLES
                or not _outside_source(target, source_url)
                or any(link["candidate_url"] == target for link in found)):
            continue
        found.append({"candidate_url": target,
                      "evidence_format": "VISIBLE_EVENT_WEBSITE"})
        if len(found) >= MAX_LINKS_PER_SOURCE:
            return found
    return found


def discovery_queue(leads, history, today, clean_url, classify):
    """Reconstruct a fresh private queue from dated, corroborated lead history.

    New URLs are not visited, certified, or silently added to public or
    curated files. Historical records are untrusted until their origin,
    freshness, fingerprint, role and edition are verified again.
    """
    current = date.fromisoformat(today)
    queue = []
    seen = set()
    if not isinstance(history, dict) or not isinstance(leads, list):
        raise ValueError("historique de découverte invalide")
    for lead in leads:
        if (not isinstance(lead, dict)
                or lead.get("allowed_to_publish") is not False
                or lead.get("official_status") != "NOT_VERIFIED"):
            continue
        slug = lead.get("slug")
        try:
            end = date.fromisoformat(lead.get("end_date") or lead["start_date"])
        except (TypeError, ValueError, KeyError):
            continue
        if not isinstance(slug, str) or end < current:
            continue
        listed = lead.get("candidate_urls")
        if not isinstance(listed, list):
            continue
        existing = {clean_url(url) for url in listed}
        previous = history.get(slug, {})
        if not isinstance(previous, dict):
            continue
        edition_count = 0
        for origin in listed[:12]:
            source = clean_url(origin)
            if not source:
                continue
            record = previous.get(source, {})
            if not isinstance(record, dict):
                continue
            if (record.get("status") != "REVIEW_REQUIRED"
                    or record.get("role") not in SOURCE_ROLES
                    or classify(source) not in SOURCE_ROLES):
                continue
            digest = record.get("fingerprint_sha256")
            if (not isinstance(digest, str) or len(digest) != 64
                    or any(c not in "0123456789abcdef" for c in digest)):
                continue
            try:
                checked = date.fromisoformat(record["lastChecked"])
            except (TypeError, KeyError, ValueError):
                continue
            if not timedelta(0) <= current - checked <= timedelta(days=MAX_AGE_DAYS):
                continue
            for key, evidence_format in (
                ("organizer_links_review_only", "VISIBLE_ORGANIZER_ANCHOR"),
                ("structured_organizer_links_review_only", "SCHEMA_ORG_ORGANIZER"),
                ("festival_event_links_review_only", "SCHEMA_ORG_EVENT"),
                ("visible_festival_website_links_review_only", "VISIBLE_EVENT_WEBSITE"),
            ):
                candidates = record.get(key, [])
                if not isinstance(candidates, list):
                    continue
                for raw in candidates[:4]:
                    if isinstance(raw, dict):
                        kind, raw = raw.get("evidence_format"), raw.get("candidate_url")
                    else:
                        kind = evidence_format
                    target = clean_url(raw)
                    identity = (slug, target)
                    if (not target or target in existing or identity in seen
                            or classify(target) not in TARGET_ROLES
                            or not _outside_source(target, source)):
                        continue
                    seen.add(identity)
                    queue.append({
                        "slug": slug, "candidate_url": target,
                        "discovered_from": source,
                        "evidence_format": kind if isinstance(kind, str) else evidence_format,
                        "last_observed": checked.isoformat(),
                        "status": "UNVERIFIED_DISCOVERY",
                        "link_only": True,
                        "official_site_authorized": False,
                        "publication_authorized": False,
                    })
                    edition_count += 1
                    if len(queue) >= MAX_QUEUE:
                        return queue
                    if edition_count >= MAX_QUEUE_PER_EDITION:
                        break
                if edition_count >= MAX_QUEUE_PER_EDITION:
                    break
            if edition_count >= MAX_QUEUE_PER_EDITION:
                break
    return queue
