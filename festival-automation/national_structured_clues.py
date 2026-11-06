"""Read-only, bounded structured Event clues from a regional festival detail page.

Reuse schema.org parser already used for published editions, but *never*
promote an agenda's JSON-LD, organizer name, location or date into proof.
No hyperlinks are extracted as fetch targets and no network request is made.
"""
from datetime import date
import re

from national_discovery_queue import _identity
from source_qualification import matches_date, normalized
from structured_evidence import StructuredData, event_objects, event_date

MAX_DOCUMENTS = 25
MAX_EVENTS = 100
MAX_HINTS = 2
MAX_STRING = 120
MAX_RANGE_DAYS = 31
DANGEROUS = re.compile(r"[<>{}\x00-\x1f]")


def _text(value, length=MAX_STRING):
    if (not isinstance(value, str) or not 3 <= len(value.strip()) <= length
            or DANGEROUS.search(value)):
        return None
    return value.strip()


def _location(event):
    place = event.get("location")
    if not isinstance(place, dict):
        return None, None
    venue = _text(place.get("name"))
    address = place.get("address")
    city = _text(address.get("addressLocality")) if isinstance(address, dict) else None
    return venue, city


def _organizer(event):
    person = event.get("organizer")
    if isinstance(person, list):
        return None  # No assumption about ownership or selecting first item.
    return _text(person.get("name")) if isinstance(person, dict) else None


def detail_event_clues(html, source, visible):
    """Structured hints need an EXACT year-specific festival name match.

    The already-registered regional index must first have shown the same URL
    during the watch: this function cannot approve a new site or link.
    """
    if (not isinstance(html, str) or len(html) > 650_000
            or not isinstance(visible, str) or len(visible) > 650_000
            or not isinstance(source, dict)
            or not isinstance(source.get("year"), int)):
        raise ValueError("entree evenement invalide")
    expected = _identity(source.get("title"))
    if expected is None or expected[1] != source["year"]:
        return []
    target_name, target_year = expected
    parser = StructuredData()
    parser.feed(html)
    matches = []
    seen = set()
    count = 0
    for doc in parser.documents[:MAX_DOCUMENTS]:
        for event in event_objects(doc):
            count += 1
            if count > MAX_EVENTS:
                return matches
            if not isinstance(event, dict):
                continue
            event_name = _text(event.get("name"), 180)
            candidate = _identity(event_name)
            # Explicit edition year in event name, not just an arbitrary date
            # in an embedded calendar or a festival from a previous year.
            if candidate != (target_name, target_year):
                continue
            start = event_date(event.get("startDate"))
            end = event_date(event.get("endDate"))
            if (start is None or start.year != target_year
                    or (end is not None and (
                        end < start or end.year != target_year
                        or (end - start).days > MAX_RANGE_DAYS))):
                continue
            key = (start.isoformat(), end.isoformat() if end else None)
            if key in seen:
                continue
            seen.add(key)
            venue, city = _location(event)
            organizer = _organizer(event)
            # The user-visible page is separate from embedded JSON-LD.
            # Dates must be present NEAR the festival's visible name.
            match = re.search(
                r"(?<![a-z0-9])" + re.escape(target_name) + r"(?![a-z0-9])",
                visible)
            window = (visible[max(0, match.start()-80):match.end()+400]
                      if match else "")
            start_seen = bool(window and matches_date(window, start.isoformat()))
            end_seen = bool(end and window and matches_date(window, end.isoformat()))
            matches.append({
                "event_name_hint": event_name,
                "start_date_hint": start.isoformat(),
                "end_date_hint": end.isoformat() if end else None,
                "start_date_visible_near_name": start_seen,
                "end_date_visible_near_name": end_seen,
                "venue_name_hint": venue,
                "city_name_hint": city,
                "organizer_name_hint": organizer,
                "organizer_identity_verified": False,
                "publisher_independence_verified": False,
                "event_dates_verified": False,
                "event_location_verified": False,
                "publication_authorized": False,
                "review_only": True,
            })
            if len(matches) >= MAX_HINTS:
                return matches
    return matches


def valid_clues(value, source, visible_year):
    """Reject altered persisted hints, retaining legacy records with no hints."""
    if not isinstance(value, list) or len(value) > MAX_HINTS:
        return False
    expected = _identity(source.get("title"))
    if expected is None or expected[1] != source["year"]:
        return not value
    for item in value:
        if not isinstance(item, dict):
            return False
        ident = _identity(item.get("event_name_hint"))
        if ident != expected:
            return False
        try:
            start = date.fromisoformat(item["start_date_hint"])
            raw_end = item.get("end_date_hint")
            end = date.fromisoformat(raw_end) if raw_end is not None else None
        except (ValueError, TypeError, KeyError):
            return False
        if (start.year != source["year"] or (end is not None and (
                end.year != source["year"] or end < start
                or (end - start).days > MAX_RANGE_DAYS))):
            return False
        if (item.get("organizer_identity_verified") is not False
                or item.get("publisher_independence_verified") is not False
                or item.get("event_dates_verified") is not False
                or item.get("event_location_verified") is not False
                or item.get("publication_authorized") is not False
                or item.get("review_only") is not True
                or type(item.get("start_date_visible_near_name")) is not bool
                or type(item.get("end_date_visible_near_name")) is not bool
                or (item["end_date_visible_near_name"] and end is None)):
            return False
        for field in ("venue_name_hint", "city_name_hint", "organizer_name_hint"):
            if item.get(field) is not None and _text(item[field]) != item[field]:
                return False
        if item["start_date_visible_near_name"] and visible_year is not True:
            return False
    return True
