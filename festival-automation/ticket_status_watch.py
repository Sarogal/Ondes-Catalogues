"""Private review-only JSON-LD ticket and event status monitoring.
A recorded status or SoldOut category NEVER changes the public catalogue.
"""
from datetime import date, timedelta
from hashlib import sha256
import json
import re

from structured_evidence import StructuredData, event_objects, event_date, normalize, root_name

AVAILABILITY = {"SoldOut": "sold_out", "InStock": "in_stock",
                "LimitedAvailability": "limited_availability", "PreOrder": "preorder"}
SENSITIVE = {"EventCancelled": "cancelled", "EventPostponed": "postponed",
             "EventRescheduled": "rescheduled"}
STATE_KEY = "ticket_status_observations"


def schema_term(value, vocabulary):
    if not isinstance(value, str):
        return None
    for name, canonical in vocabulary.items():
        if value in (name, "https://schema.org/" + name, "http://schema.org/" + name):
            return canonical
    return None


def categories(event):
    """Only explicitly named categories; never infer whole-event availability."""
    offers = event.get("offers", [])
    if isinstance(offers, dict):
        offers = [offers]
    if not isinstance(offers, list) or len(offers) > 40:
        return []
    result = {}
    for offer in offers:
        if not isinstance(offer, dict):
            continue
        availability = schema_term(offer.get("availability"), AVAILABILITY)
        name = offer.get("name")
        if not availability or not isinstance(name, str):
            continue
        name = " ".join(name.split())
        key = normalize(name)
        if not (3 <= len(key) <= 90 and 3 <= len(name) <= 120):
            continue
        if key in result and result[key]["availability"] != availability:
            return None
        result[key] = {"category": name, "availability": availability}
    return sorted(result.values(), key=lambda x: normalize(x["category"]))


def inspect_ticket_status(html, edition, source_url, observed_at):
    """Require explicitly named, single-year festival JSON-LD on registered URL.

    For tickets, the dates must exactly match the published edition. Sensitive
    cancellations or rescheduling remain review-only even if dates differ.
    """
    if not isinstance(html, str) or len(html) > 650_000:
        raise ValueError("HTML invalide")
    today = date.fromisoformat(observed_at)
    start, end = event_date(edition.get("startDate")), event_date(edition.get("endDate"))
    target = root_name(edition.get("name", ""))
    if not start or not end or start < today or len(target) < 8:
        return []
    parser = StructuredData()
    parser.feed(html)
    matches = []
    seen = 0
    for document in parser.documents[:25]:
        for event in event_objects(document):
            seen += 1
            if seen > 100:
                return []
            kinds = event.get("@type")
            kinds = kinds if isinstance(kinds, list) else [kinds]
            if not {str(k).rsplit("/", 1)[-1].casefold() for k in kinds} & {
                "musicevent", "musicfestival", "festival", "event"
            }:
                continue
            name = event.get("name")
            if (not isinstance(name, str) or root_name(name) != target
                    or str(start.year) not in re.findall(r"\b20[2-4][0-9]\b", name)):
                continue
            ev_start = event_date(event.get("startDate"))
            ev_end = event_date(event.get("endDate")) or ev_start
            if not ev_start or not ev_end or ev_end < ev_start or (
                ev_end - ev_start).days > 31 or ev_start.year != start.year:
                continue
            sensitive = schema_term(event.get("eventStatus"), SENSITIVE)
            ticket = categories(event)
            if ticket is None:
                return []
            if ev_start != start or ev_end != end:
                ticket = []
            if not ticket and not sensitive:
                continue
            matches.append({
                "slug": edition["slug"], "source": source_url,
                "edition": name.strip()[:180],
                "startDate": ev_start.isoformat(), "endDate": ev_end.isoformat(),
                "ticket_categories": ticket, "sensitive_event_status": sensitive,
                "observed_at": observed_at, "publication_authorized": False,
            })
    if not matches:
        return []
    signatures = {json.dumps({k: v for k, v in row.items() if k != "observed_at"},
                             sort_keys=True) for row in matches}
    return matches[:1] if len(signatures) == 1 else []


def stable_ticket_status_observation(state, slug, url, observations, today):
    """Return a review-only proof digest after two calendar-day observations."""
    records = state.setdefault(STATE_KEY, {})
    if not isinstance(records, dict):
        raise ValueError("état billetterie corrompu")
    if not isinstance(observations, list) or len(observations) != 1:
        records.pop(slug, None)
        return None
    obs = observations[0]
    offers = obs.get("ticket_categories")
    if (obs.get("slug") != slug or obs.get("source") != url
            or obs.get("publication_authorized") is not False
            or not isinstance(offers, list)
            or (not offers and obs.get("sensitive_event_status") not in SENSITIVE.values())
            or any(not isinstance(x, dict)
                   or x.get("availability") not in AVAILABILITY.values()
                   or not isinstance(x.get("category"), str) for x in offers)):
        records.pop(slug, None)
        return None
    proof = {k: v for k, v in obs.items() if k != "observed_at"}
    digest = sha256(json.dumps(proof, sort_keys=True,
                               ensure_ascii=False).encode("utf-8")).hexdigest()
    prev = records.get(slug, {})
    prev = prev if isinstance(prev, dict) else {}
    yesterday = (date.fromisoformat(today) - timedelta(days=1)).isoformat()
    same = prev.get("source") == url and prev.get("digest") == digest
    stable = same and (prev.get("lastSeen") == yesterday
                       or prev.get("lastConfirmed") == today)
    records[slug] = {
        "source": url, "digest": digest,
        "firstSeen": prev.get("firstSeen") if same and prev.get("lastSeen") in (
            yesterday, today) else today,
        "lastSeen": today, "lastConfirmed": today if stable else None,
    }
    return digest if stable else None
