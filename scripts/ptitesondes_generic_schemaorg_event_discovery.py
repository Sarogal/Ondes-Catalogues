"""Reusable, read-only Schema.org JSON-LD family outing discovery hints.

Source-independent adapter: any separately pinned official institution site
may use it. This module performs NO HTTP request and NO independent proof of
organizer, venue coordinates, audience, price, rights, or publisher readiness.

Exact occurrence day/clock must exist in Event.startDate; date ranges and
recurrence schedules are never expanded into fabricated performances.
Unclassified events are kept as PRIVATE hints for further review.
"""
from collections import Counter, deque
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
import json
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ptitesondes_real_family_source_adapters import (
    classify, TERRITORY_TIMEZONES,
)

SCHEMA = "ptitesondes.generic_schemaorg_event_discovery.v1"
MAX_HTML = 500_000
MAX_SCRIPTS = 32
MAX_NODES = 600
MAX_LEADS = 200
MAX_TEXT = 180
# Reviewed IANA timezone pin, never selected from a candidate event.
SOURCE_TIMEZONES = TERRITORY_TIMEZONES | frozenset((
    "America/Miquelon", "America/Marigot", "America/St_Barthelemy",
    "Pacific/Tahiti", "Pacific/Marquesas", "Pacific/Gambier",
    "Pacific/Noumea", "Pacific/Wallis",
))
MAX_NESTED = 8
CLOCK = re.compile(r"\d{4}-\d{2}-\d{2}T[0-2]\d:[0-5]\d")
HOLD_REASONS = frozenset((
    "invalid_input", "malformed_json", "too_many_scripts",
    "too_many_nodes", "missing_title", "missing_venue_or_city",
    "missing_exact_clock", "ambiguous_timezone",
    "non_future", "cancelled_or_postponed",
    "too_many_events", "unclassified_nonmusical",
))


class _JsonLdScripts(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.collecting = False
        self.data = []

    def handle_starttag(self, tag, attrs):
        if tag != "script":
            return
        kinds = dict(attrs)
        typ = str(kinds.get("type") or "").split(";", 1)[0].strip().lower()
        if typ == "application/ld+json":
            self.collecting = True
            self.data = []

    def handle_data(self, data):
        if self.collecting:
            self.data.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.collecting:
            self.collecting = False
            if len(self.parts) >= MAX_SCRIPTS:
                raise ValueError("too_many_scripts")
            self.parts.append("".join(self.data))
            self.data = []


def _safe_text(raw, limit=MAX_TEXT):
    return (type(raw) is str and raw == raw.strip()
            and 1 <= len(raw) <= limit
            and not re.search(r"[\x00-\x1f\x7f<>]", raw))


def _valid_pin(pin, page):
    if (type(pin) is not dict or set(pin) != {
            "approved_host", "exact_child_url", "child_prefix", "timezone"}
            or type(page) is not dict or set(page) != {"url", "html"}
            or not _safe_text(pin.get("approved_host"), 200)
            or not _safe_text(pin.get("exact_child_url"), 1000)
            or not _safe_text(pin.get("child_prefix"), 180)
            or type(pin.get("timezone")) is not str
            or pin["timezone"] not in SOURCE_TIMEZONES
            or page.get("url") != pin["exact_child_url"]):
        return False
    try:
        url = urlsplit(pin["exact_child_url"])
        if (url.scheme != "https" or url.hostname != pin["approved_host"]
                or url.username or url.password or url.port not in (None, 443)
                or url.fragment or not url.path.startswith(pin["child_prefix"])):
            return False
        if not pin["child_prefix"].startswith("/") or pin["child_prefix"].startswith("//"):
            return False
        return isinstance(page["html"], str) and 60 <= len(page["html"]) <= MAX_HTML
    except (ValueError, TypeError):
        return False


def _event_type(value):
    variants = value if type(value) is list else [value]
    if not variants or len(variants) > 20:
        return False
    for v in variants:
        if type(v) is not str:
            continue
        name = v.rsplit("/", 1)[-1].rsplit("#", 1)[-1]
        if name != "EventSeries" and (name == "Event" or name.endswith("Event")
                                      or name == "Festival"):
            return True
    return False


def _all_nodes(data):
    """Bounded BFS across @graph / subEvent / top-level lists."""
    queue = deque([(data, 0)])
    read = 0
    while queue:
        item, depth = queue.popleft()
        read += 1
        if read > MAX_NODES:
            raise ValueError("too_many_nodes")
        if depth > MAX_NESTED:
            continue
        if isinstance(item, list):
            queue.extend((v, depth + 1) for v in item)
            continue
        if not isinstance(item, dict):
            continue
        if _event_type(item.get("@type")):
            yield item
        for key in ("@graph", "subEvent", "event", "events", "itemListElement"):
            if key in item:
                queue.append((item[key], depth + 1))


def _exact_local_datetime(start, target_timezone):
    if type(start) is not str or len(start) > 70:
        return None, "missing_exact_clock"
    if CLOCK.match(start) is None:
        return None, "missing_exact_clock"
    try:
        parsed = datetime.fromisoformat(start.replace("Z", "+00:00"))
        if parsed.second or parsed.microsecond or not 2000 <= parsed.year <= 2100:
            return None, "missing_exact_clock"
        zone = ZoneInfo(target_timezone)
        if parsed.tzinfo is None:
            # Source timezone is independently pinned per institution, not
            # inferred from event claims. Ambiguous/nonexistent DST local
            # clocks must be held until the source confirms exact instant.
            a = parsed.replace(tzinfo=zone, fold=0)
            b = parsed.replace(tzinfo=zone, fold=1)
            if a.utcoffset() != b.utcoffset():
                return None, "ambiguous_timezone"
            if (a.astimezone(timezone.utc).astimezone(zone)
                    .replace(tzinfo=None) != parsed):
                return None, "ambiguous_timezone"
            return a, None
        return parsed.astimezone(zone), None
    except (ValueError, OverflowError, ZoneInfoNotFoundError):
        return None, "missing_exact_clock"


def _venue_city(location):
    venues = location if type(location) is list else [location]
    if len(venues) != 1 or not isinstance(venues[0], dict):
        return None
    item = venues[0]
    venue = item.get("name")
    address = item.get("address")
    city = address.get("addressLocality") if type(address) is dict else None
    if not _safe_text(venue, 160) or not _safe_text(city, 120):
        return None
    return venue, city


def _empty(stage="no_exact_schemaorg_sessions"):
    return {
        "schema": SCHEMA, "stage": stage,
        "private_leads": [],
        "counts": {
            "schemaorg_event_nodes": 0, "future_exact_sessions": 0,
            "explicit_categories_hint_only": 0,
            "unclassified_sessions_requiring_review": 0,
            **{reason: 0 for reason in sorted(HOLD_REASONS)},
        },
        "first_party_visible_session_rechecked": False,
        "organizer_ownership_attested": False,
        "venue_geocoded": False, "rights_reviewed": False,
        "publisher_connected": False, "publication_ready": False,
        "approved": False, "public_writes": 0,
    }


def parse_schemaorg_private_event_hints(page, trusted_child, today):
    """Parse current child page, trusted host/prefix/timezone from caller.

    A JSON-LD script is an untrusted SOURCE CLAIM, not visible proof; each
    session must pass the existing first-party, organizer and geo gates later.
    """
    if type(today) is not date or not _valid_pin(trusted_child, page):
        return _empty("invalid_trusted_child_or_page")
    parser = _JsonLdScripts()
    try:
        parser.feed(page["html"])
        parser.close()
    except (ValueError, TypeError):
        return _empty("jsonld_script_scan_failed")
    counts = _empty()["counts"]
    result = []
    seen = set()
    for script in parser.parts:
        if len(script) > MAX_HTML:
            counts["malformed_json"] += 1
            continue
        try:
            obj = json.loads(script)
            events = list(_all_nodes(obj))
        except (TypeError, ValueError, RecursionError):
            counts["malformed_json"] += 1
            continue
        for item in events:
            counts["schemaorg_event_nodes"] += 1
            if counts["schemaorg_event_nodes"] > MAX_LEADS:
                return _empty("too_many_event_nodes")
            if not _safe_text(item.get("name")):
                counts["missing_title"] += 1
                continue
            start, issue = _exact_local_datetime(
                item.get("startDate"), trusted_child["timezone"])
            if issue:
                counts[issue] += 1
                continue
            if start.date() < today:
                counts["non_future"] += 1
                continue
            status = str(item.get("eventStatus") or "").rsplit("/", 1)[-1]
            if status in ("EventCancelled", "EventPostponed", "EventMovedOnline"):
                counts["cancelled_or_postponed"] += 1
                continue
            place = _venue_city(item.get("location"))
            if place is None:
                counts["missing_venue_or_city"] += 1
                continue
            venue, city = place
            title = item["name"]
            category = classify(title, str(item.get("keywords") or "")[:180])
            identity = (title.casefold(), venue.casefold(), city.casefold(),
                        start.date().isoformat(), start.strftime("%H:%M"))
            if identity in seen:
                continue
            if len(result) >= MAX_LEADS:
                return _empty("too_many_event_nodes")
            seen.add(identity)
            if category is None:
                counts["unclassified_sessions_requiring_review"] += 1
            else:
                counts["explicit_categories_hint_only"] += 1
            result.append({
                "source_url": page["url"], "title": title,
                "venue": venue, "city": city,
                "date_start": start.date().isoformat(),
                "date_end": start.date().isoformat(),
                "start_local": start.strftime("%H:%M"),
                "category_hint_only": category,
                "source_format": "schema_org_jsonld",
                "audience_source_visible_confirmed": False,
                "price_evidence": "not_stated",
                "registration_evidence": "not_stated",
                "official_session_independently_proved": False,
                "organizer_independently_attested": False,
                "approved": False, "published": False,
            })
    counts["future_exact_sessions"] = len(result)
    return dict(_empty(), stage="private_structured_hints_only",
                private_leads=result, counts=counts)


def redact_schemaorg_report(result):
    """Public CI can print these bounded aggregate counts, NEVER lead data."""
    base = _empty()["counts"]
    candidate = result.get("counts") if isinstance(result, dict) else None
    safe = {}
    for k in base:
        v = candidate.get(k) if isinstance(candidate, dict) else None
        safe[k] = v if type(v) is int and 0 <= v <= MAX_NODES else 0
    return {
        "schema": SCHEMA, "counts": safe,
        "contains_candidate_identifiers": False,
        "first_party_visible_session_rechecked": False,
        "rights_reviewed": False, "publication_ready": False,
        "publisher_connected": False, "public_writes": 0,
    }
