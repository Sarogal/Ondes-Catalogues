"""Independent proof of per-category festival ticket availability (never overall sold out).

Private intake can propose a typed patch after two observations. Neither its
source HTML nor its interpretation is trusted here: this validator accepts
only the immutable catalogue's registered officialSite, independently fetched
by the cloud synchronizer. Cancellation and rescheduling stay review-only.
"""
from datetime import date, timedelta
import re

from grossesondes_structured_roster import JsonLD, walk, edition_name, iso_day, canonical

PROOF_MODE = "structured-tickets.v1"
FIELD = "ticketAvailability"
EVENT_TYPES = {"festival", "musicfestival", "musicevent"}
SENSITIVE = {"EventCancelled", "EventPostponed", "EventRescheduled"}
STATES = {
    "SoldOut": "sold_out",
    "InStock": "in_stock",
    "LimitedAvailability": "limited_availability",
    "PreOrder": "preorder",
}


def schema_term(raw, choices):
    if not isinstance(raw, str):
        return None
    for key, val in choices.items():
        if raw in (key, "https://schema.org/" + key, "http://schema.org/" + key):
            return val
    return None


def official_ticket_categories(html, original):
    """Return a unique, exact-category snapshot or None, failing closed.

    Only explicitly labelled offers tied to an exact named-year edition and
    identical dates are eligible. Unknown/contradictory status-bearing offers,
    repeated conflicting objects and sensitive statuses all block approval.
    No global festival availability is inferred from the categories.
    """
    if not isinstance(html, str) or not html or len(html) > 650_000:
        return None
    start = iso_day(original.get("startDate"))
    end = iso_day(original.get("endDate"))
    name = edition_name(original.get("name", ""))
    if not start or not end or start > end or len(name) < 8:
        return None
    parser = JsonLD()
    parser.feed(html)
    matches = []
    count = 0
    for document in parser.documents[:25]:
        for event in walk(document):
            count += 1
            if count > 100:
                return None
            types = event.get("@type")
            types = types if isinstance(types, list) else [types]
            types = {str(x).rsplit("/", 1)[-1].casefold() for x in types}
            if not types.intersection(EVENT_TYPES):
                continue
            title = event.get("name")
            if (not isinstance(title, str) or edition_name(title) != name or
                    str(start.year) not in re.findall(r"\b20[2-4][0-9]\b", title)):
                continue
            ev_start = iso_day(event.get("startDate"))
            ev_end = iso_day(event.get("endDate")) or ev_start
            if ev_start != start or ev_end != end:
                return None
            if schema_term(event.get("eventStatus"),
                           {v: v for v in SENSITIVE}):
                return None
            offers = event.get("offers")
            if isinstance(offers, dict):
                offers = [offers]
            if not isinstance(offers, list) or not 1 <= len(offers) <= 40:
                continue
            found = {}
            for offer in offers:
                if not isinstance(offer, dict):
                    return None
                raw_availability = offer.get("availability")
                status = schema_term(raw_availability, STATES)
                if raw_availability is not None and status is None:
                    return None
                if status is None:
                    continue
                label = offer.get("name")
                if not isinstance(label, str):
                    return None
                label = " ".join(label.split())
                key = canonical(label)
                if not (3 <= len(key) <= 90 and 3 <= len(label) <= 120):
                    return None
                if key in found and found[key]["status"] != status:
                    return None
                found[key] = {"name": label, "status": status}
            if not found or len(found) > 12:
                continue
            matches.append(sorted(found.values(), key=lambda x: canonical(x["name"])))
    if not matches:
        return None
    # Duplicate identical JSON-LD objects are acceptable, not contradictions.
    return matches[0] if all(row == matches[0] for row in matches) else None


def validate_structured_tickets(original, proposal, html, today):
    """Return (revised_row, changed_fields, pending) or None.

    Fresh, independent confirmation is required on every execution.
    A ticket category is not an assertion that the whole festival is full.
    """
    if not isinstance(proposal, dict) or proposal.get("proofMode") != PROOF_MODE:
        return None
    official = original.get("officialSite")
    if (not isinstance(official, str) or not official.startswith("https://")
            or proposal.get("evidence") != [official]
            or proposal.get("slug") != original.get("slug")):
        return None
    changes = proposal.get("changes")
    if (not isinstance(changes, list) or len(changes) != 1
            or not isinstance(changes[0], dict)
            or set(changes[0]) != {"field", "before", "after"}
            or changes[0]["field"] != FIELD
            or changes[0]["before"] != original.get(FIELD)):
        return None
    after = changes[0]["after"]
    if (not isinstance(after, dict)
            or set(after) != {"source", "verifiedAt", "scope", "categories"}
            or after["source"] != official or after["scope"] != "per_category_only"
            or not isinstance(after["categories"], list)):
        return None
    try:
        today_day = date.fromisoformat(today)
        check_day = date.fromisoformat(after["verifiedAt"])
    except (TypeError, ValueError, KeyError):
        return None
    if not today_day - timedelta(days=2) <= check_day <= today_day:
        return None
    if proposal.get("verified_at") != after["verifiedAt"]:
        return None
    confirmed = official_ticket_categories(html, original)
    if confirmed is None or after["categories"] != confirmed:
        return None
    changed = dict(original)
    changed[FIELD] = after
    return changed, [FIELD], []
