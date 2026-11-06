"""Conservative schema.org extraction from an already registered official site.

Structured hints are NOT publication proofs. In particular, an event's date
range does not imply daily sessions, a price does not describe ticket tiers,
and eventStatus alone does not approve cancellation.
"""
from datetime import date
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
import json
import re
import unicodedata

ACCEPTED_EVENT_TYPES = {"festival", "musicevent", "event", "musicfestival"}
STATUS_HINTS = {"EventCancelled", "EventPostponed", "EventRescheduled"}
MAX_SCRIPT = 120_000


class StructuredData(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.active = False
        self.buffer = []
        self.documents = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "script":
            kind = dict(attrs).get("type", "").split(";")[0].lower().strip()
            self.active = kind == "application/ld+json"
            self.buffer = []

    def handle_data(self, data):
        if self.active and sum(map(len, self.buffer)) < MAX_SCRIPT:
            self.buffer.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "script" and self.active:
            raw = "".join(self.buffer)
            if len(raw) <= MAX_SCRIPT:
                try:
                    self.documents.append(json.loads(raw))
                except (ValueError, TypeError):
                    pass
            self.active = False
            self.buffer = []


def event_objects(value, depth=0):
    if depth > 5:
        return
    if isinstance(value, list):
        for item in value[:100]:
            yield from event_objects(item, depth + 1)
    elif isinstance(value, dict):
        if "@type" in value:
            types = value["@type"] if isinstance(value["@type"], list) else [value["@type"]]
            kinds = {str(x).rsplit("/", 1)[-1].casefold() for x in types if isinstance(x, str)}
            if kinds & ACCEPTED_EVENT_TYPES:
                yield value
        if "@graph" in value:
            yield from event_objects(value["@graph"], depth + 1)


def normalize(value):
    text = unicodedata.normalize("NFKD", str(value).casefold())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(re.findall(r"[a-z0-9]+", text))


def artist_key(name):
    """Conservative alias key: spacing and punctuation only, no fuzzy matching."""
    return "".join(normalize(name).split())


def root_name(name):
    text = re.sub(r"\b20[2-4][0-9]\b", " ", str(name))
    return normalize(text)


def event_date(raw):
    if not isinstance(raw, str) or not re.match(r"^\d{4}-\d{2}-\d{2}(?:$|[Tt ])", raw):
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def performers(event):
    raw = event.get("performer") or []
    if not isinstance(raw, list):
        raw = [raw]
    result, seen = [], set()
    for item in raw[:100]:
        name = item.get("name", "") if isinstance(item, dict) else item
        if not isinstance(name, str):
            continue
        name = name.strip()
        key = artist_key(name)
        if 3 <= len(key) <= 75 and key not in seen and key not in ("tba", "avenir", "tobeannounced"):
            result.append(name)
            seen.add(key)
    return result


def offer_prices(event):
    raw = event.get("offers", [])
    if not isinstance(raw, list):
        raw = [raw]
    result = []
    for offer in raw[:30]:
        if not isinstance(offer, dict) or str(offer.get("priceCurrency", "")).upper() != "EUR":
            continue
        try:
            value = Decimal(str(offer.get("price", "")))
            if not value.is_finite() or value < 0 or value > 2000:
                continue
            amount = str(value.quantize(Decimal("0.01")))
        except (InvalidOperation, ValueError, TypeError):
            continue
        if amount not in result:
            result.append(amount)
    return result


def location_hint(event):
    place = event.get("location")
    if not isinstance(place, dict):
        return None
    name = place.get("name")
    if isinstance(name, str) and 3 <= len(name.strip()) <= 180:
        return name.strip()
    return None


def inspect_official_html(html, edition, source_url, observed_at):
    """Return review-only structured clues, never a replacement festival row.

    Existing edition identity comes from the published catalogue. A future
    edition must be explicitly labelled by year in the event name; a current
    edition can propose only date corrections, added artists, missing prices,
    or a sensitive status review.
    """
    if not isinstance(html, str) or len(html) > 650_000:
        raise ValueError("HTML trop volumineux ou invalide")
    parser = StructuredData()
    parser.feed(html)
    target = root_name(edition.get("name", ""))
    if len(target) < 8:
        return []
    current_year = None
    start_current = event_date(edition.get("startDate"))
    if start_current is not None:
        current_year = start_current.year
    else:
        match = re.search(r"(20[2-4][0-9])$", str(edition.get("slug", "")))
        if match:
            current_year = int(match.group(1))
    if current_year is None:
        return []
    previous_names = {artist_key(n) for n in (edition.get("lineup") or [])
                      if isinstance(n, str)}
    observations = []
    dedup = set()
    seen_events = 0
    for document in parser.documents[:25]:
        for event in event_objects(document):
            seen_events += 1
            if seen_events > 100:
                return observations
            event_name = event.get("name")
            if not isinstance(event_name, str):
                continue
            event_root = root_name(event_name)
            if target not in event_root and event_root not in target:
                continue
            if len(event_root) < 8:
                continue
            start = event_date(event.get("startDate"))
            end = event_date(event.get("endDate"))
            if start is None or (end is not None and (end < start or (end - start).days > 31)):
                continue
            observed_day = date.fromisoformat(observed_at)
            if start < observed_day or start.year > observed_day.year + 2:
                continue
            # A new year is NOT inferred from a generic recurrence/calendar widget.
            if start.year != current_year and (
                start.year < current_year or str(start.year) not in normalize(event_name).split()
            ):
                continue
            key = (normalize(event_name), start.isoformat(), end.isoformat() if end else None)
            if key in dedup:
                continue
            dedup.add(key)
            hints = {}
            if start.year > current_year:
                hints["new_edition_year"] = start.year
            else:
                if edition.get("startDate") != start.isoformat():
                    hints["startDate"] = start.isoformat()
                if end is not None and edition.get("endDate") != end.isoformat():
                    hints["endDate"] = end.isoformat()
                added = [name for name in performers(event) if artist_key(name) not in previous_names]
                if added:
                    hints["new_performers"] = added
                prices = offer_prices(event)
                if prices and edition.get("price") is None:
                    hints["offer_prices_eur"] = prices
            status = str(event.get("eventStatus", "")).rsplit("/", 1)[-1]
            if status in STATUS_HINTS:
                hints["sensitive_event_status"] = status
                hints["requires_secondary_confirmation"] = True
            place = location_hint(event)
            if place and (hints or not edition.get("venue")):
                hints["place_name_unverified"] = place
            if not hints:
                continue
            observations.append({
                "slug": edition["slug"],
                "name_on_source": event_name.strip()[:180],
                "source_url": source_url,
                "observed_at": observed_at,
                "startDate_source": start.isoformat(),
                "endDate_source": end.isoformat() if end else None,
                "range_needs_sessions": bool(end and (end - start).days > 2),
                "hints": hints,
                "publication_authorized": False,
            })
    return observations
