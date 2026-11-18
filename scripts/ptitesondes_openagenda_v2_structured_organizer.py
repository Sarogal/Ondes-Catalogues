"""Read-only first-party JSON-LD event/session corroboration.

Input HTML must already come from an independently reviewed HTTPS organiser
page fetched without redirects. Structured Event data supplies exact session
times where a municipal site does not display them as visible <li> text.
The visual page must still state title, place, commune and family audience.
No per-event exceptions, approval, rights claim, or publication.
"""
from datetime import date, datetime
from html.parser import HTMLParser
import ipaddress
import json
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ptitesondes_family_national_source_preflight import (
    _VisibleText, norm_text, AGE_PHRASE, BAD_STATUS, official_host,
)
from ptitesondes_openagenda_v2_organizer_bridge import (
    ADULT_ONLY, OA_SOURCE_SCHEMA, FORBIDDEN_HOSTS,
)

SCHEMA = "ptitesondes.oa2.first_party_structured_event_session.v1"
MAX_HTML = 500_000
MAX_BLOCKS = 25
MAX_NODES = 80
MAX_SESSIONS = 20


class _JSONLD(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.active = False
        self.parts = []
        self.blocks = []

    def handle_starttag(self, tag, attrs):
        if tag == "script" and str(dict(attrs).get("type") or "").strip().lower() == "application/ld+json":
            self.active = True
            self.parts = []

    def handle_data(self, data):
        if self.active:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.active:
            if len(self.blocks) < MAX_BLOCKS:
                self.blocks.append("".join(self.parts))
            self.active = False
            self.parts = []


def _events(raw):
    pending = [raw]
    remaining = MAX_NODES
    while pending and remaining:
        node = pending.pop()
        if isinstance(node, list):
            pending.extend(reversed(node[:MAX_NODES]))
        elif isinstance(node, dict):
            remaining -= 1
            kind = node.get("@type")
            kinds = [kind] if isinstance(kind, str) else kind
            if isinstance(kinds, list) and any(
                isinstance(x, str) and x.rsplit("/", 1)[-1].endswith("Event")
                for x in kinds
            ):
                yield node
            graph = node.get("@graph")
            if isinstance(graph, list):
                pending.extend(reversed(graph[:MAX_NODES]))


def _clock(value, day, timezone):
    if not isinstance(value, str) or len(value) > 50:
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            return None
        local = stamp.astimezone(ZoneInfo(timezone))
        return local.strftime("%H:%M") if local.date().isoformat() == day else None
    except (ValueError, ZoneInfoNotFoundError, OverflowError):
        return None


def check_structured_organizer_session(
        lead, api_event, direct_proof, reviewed_organizer, official_page):
    out = {
        "schema": SCHEMA,
        "official_structured_sessions_concordant": False,
        "organizer_ownership_attested": False,
        "rights_reviewed": False, "age_access_fully_verified": False,
        "publisher_connected": False, "approval_granted": False,
        "public_writes": 0, "reason": "missing_or_untrusted_input",
    }
    def hold(reason):
        return dict(out, reason=reason)
    if (not isinstance(lead, dict) or not isinstance(api_event, dict)
            or not isinstance(direct_proof, dict)
            or direct_proof.get("schema") != OA_SOURCE_SCHEMA
            or direct_proof.get("source_evidence_structurally_valid") is not True
            or direct_proof.get("event_kind") != "single_explicit_dated_occurrence"
            or direct_proof.get("approval_granted") is not False
            or direct_proof.get("public_writes") != 0):
        return hold("unverified_direct_single_day_proof")
    if (not isinstance(reviewed_organizer, dict)
            or set(reviewed_organizer) != {"approved_host", "exact_url"}
            or not isinstance(official_page, dict)
            or set(official_page) != {"url", "html"}):
        return hold("organizer_not_separately_reviewed")
    host, url = reviewed_organizer["approved_host"], reviewed_organizer["exact_url"]
    try:
        u = urlsplit(url)
        if (not isinstance(host, str) or not isinstance(url, str)
                or len(url) > 1800 or u.hostname != host
                or official_host(url) != host
                or host in FORBIDDEN_HOSTS
                or host.endswith((".openagenda.com", ".opendatasoft.com",
                                  ".local", ".internal"))
                or host == "localhost"
                or re.fullmatch(r"[a-z0-9.-]+", host) is None
                or official_page.get("url") != url):
            return hold("organizer_url_not_independently_pinned")
        try:
            ipaddress.ip_address(host)
            return hold("organizer_url_not_independently_pinned")
        except ValueError:
            pass
    except (TypeError, ValueError):
        return hold("organizer_url_not_independently_pinned")
    html = official_page.get("html")
    if not isinstance(html, str) or not 50 <= len(html) <= MAX_HTML:
        return hold("official_page_unreadable")
    visible_parser = _VisibleText()
    ld_parser = _JSONLD()
    try:
        visible_parser.feed(html)
        visible_parser.close()
        ld_parser.feed(html)
        ld_parser.close()
    except (TypeError, ValueError):
        return hold("official_page_unreadable")
    visible = norm_text(" ".join(visible_parser.words))
    if any(not isinstance(lead.get(k), str) or
           norm_text(lead[k]) not in visible for k in ("title", "city", "venue")):
        return hold("official_visible_title_city_venue_not_confirmed")
    if ADULT_ONLY.search(visible) or BAD_STATUS.search(visible):
        return hold("adult_only_cancelled_full_or_postponed")
    if not AGE_PHRASE.search(visible):
        return hold("organizer_family_audience_not_visible")
    day = lead.get("date_start")
    try:
        if (not isinstance(day, str) or date.fromisoformat(day).isoformat() != day
                or lead.get("date_end") != day):
            return hold("invalid_candidate_day")
    except ValueError:
        return hold("invalid_candidate_day")
    timezone = api_event.get("timezone")
    if not isinstance(timezone, str):
        return hold("invalid_event_timezone")
    try:
        ZoneInfo(timezone)
    except (ValueError, ZoneInfoNotFoundError):
        return hold("invalid_event_timezone")
    wanted = direct_proof.get("explicit_local_times_for_candidate_day")
    if (not isinstance(wanted, list) or not 1 <= len(wanted) <= MAX_SESSIONS
            or not all(isinstance(t, str) and
                       re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", t)
                       for t in wanted) or len(set(wanted)) != len(wanted)):
        return hold("unverified_explicit_times")
    matched = set()
    for raw in ld_parser.blocks:
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            continue
        for event in _events(parsed):
            if norm_text(event.get("name")) != norm_text(lead["title"]):
                continue
            if event.get("eventStatus") is not None and (
                not isinstance(event["eventStatus"], str)
                or event["eventStatus"].rsplit("/", 1)[-1] != "EventScheduled"
            ):
                continue
            location = event.get("location")
            places = location if isinstance(location, list) else [location]
            if not any(isinstance(loc, dict) and
                       norm_text(loc.get("name")) == norm_text(lead["venue"])
                       and isinstance(loc.get("address"), dict)
                       and norm_text(loc["address"].get("addressLocality")) == norm_text(lead["city"])
                       for loc in places[:MAX_NODES]):
                continue
            time = _clock(event.get("startDate"), day, timezone)
            if time is not None:
                matched.add(time)
            if len(matched) > MAX_SESSIONS:
                return hold("ambiguous_excessive_sessions")
    if not set(wanted).issubset(matched):
        return hold("first_party_structured_session_not_concordant")
    return dict(out, official_structured_sessions_concordant=True,
                confirmed_local_start_times_count=len(wanted),
                reason="first_party_structured_session_other_gates_pending")
