"""Generic read-only EventON calendar nomination from a pinned official index.

EventON/evcal is a reusable WordPress calendar component. Event anchors use
classes desc_trig + evcal_list_a and an evc_<timestamp><eventID> ID.
The identifier's timestamp is only a ROUTING HINT for selecting a likely
date and MUST NOT certify the event's local date, time or occurrence.
Those claims still require a separately fetched first-party page and the
existing independent OpenAgenda, geography and session checks.

No HTTP, credentials, source ownership, rights, approval or publication.
"""
from datetime import date, datetime, timedelta, timezone
import re
from urllib.parse import urljoin

from ptitesondes_openagenda_v2_organizer_index import (
    _VisibleAnchors, MAX_ANCHORS,
)
from ptitesondes_family_national_source_preflight import norm_text
from ptitesondes_openagenda_v2_geo_bridge import _url

SCHEMA = "ptitesondes.oa2.eventon_index_routing.v1"
MAX_HTML = 2_000_000
MAX_NAME = 260
MAX_URL = 1800
EVC = re.compile(r"evc_([1-9][0-9]{9})([0-9]{1,8})\Z")
SAFE_REASONS = frozenset((
    "invalid_or_unreviewed_index", "candidate_title_or_day_invalid",
    "index_unavailable", "no_exact_eventon_occurrence",
    "ambiguous_eventon_occurrence_or_link",
    "eventon_page_needs_independent_session_proof",
))


class _EventOnAnchors(_VisibleAnchors):
    """Retain EventON class + ID without changing the generic HTML matcher."""
    def __init__(self):
        super().__init__()
        self.eventon = []

    def handle_starttag(self, tag, attrs):
        super().handle_starttag(tag, attrs)
        if tag == "a" and self.active:
            a = dict(attrs)
            self.active[-1]["eventon_id"] = a.get("id")
            self.active[-1]["eventon_classes"] = a.get("class", "")

    def handle_endtag(self, tag):
        if tag == "a" and self.active:
            a = self.active[-1]
            if not a["hidden"]:
                self.eventon.append((
                    a.get("href"), " ".join(a["parts"]),
                    a.get("eventon_id"), a.get("eventon_classes"),
                ))
        super().handle_endtag(tag)


def _base(reason="invalid_or_unreviewed_index"):
    return {
        "schema": SCHEMA,
        "reason": reason,
        "first_party_event_page_nominated": False,
        "verified_event_time": False,
        "organizer_ownership_attested": False,
        "approval_granted": False,
        "publisher_connected": False,
        "public_writes": 0,
    }


def nominate_eventon_page(lead, reviewed_index, fetched_index):
    """Nominate an exact same-host page, not a validated event.

    Requires the index to come from a separate trusted registry.
    The candidate's title and date select a hint only. Multiple plausible
    links lead to a hold, never an arbitrary choice.
    """
    if (not isinstance(lead, dict)
            or not isinstance(reviewed_index, dict)
            or set(reviewed_index) != {"approved_host", "exact_index_url"}
            or not isinstance(fetched_index, dict)
            or set(fetched_index) != {"url", "html"}):
        return _base()
    host, url = (
        reviewed_index.get("approved_host"),
        reviewed_index.get("exact_index_url"),
    )
    if (not isinstance(host, str) or _url(url, host=host) is None
            or fetched_index.get("url") != url):
        return _base()
    title, raw_day = lead.get("title"), lead.get("date_start")
    if (not isinstance(title, str) or not 1 <= len(title) <= MAX_NAME
            or not norm_text(title) or not isinstance(raw_day, str)):
        return _base("candidate_title_or_day_invalid")
    try:
        candidate_day = date.fromisoformat(raw_day)
        if candidate_day.isoformat() != raw_day:
            return _base("candidate_title_or_day_invalid")
    except ValueError:
        return _base("candidate_title_or_day_invalid")
    html = fetched_index.get("html")
    if (not isinstance(html, str) or not 50 <= len(html) <= MAX_HTML):
        return _base("index_unavailable")
    parser = _EventOnAnchors()
    try:
        parser.feed(html)
        parser.close()
    except (ValueError, TypeError):
        return _base("index_unavailable")
    matches = set()
    for href, label, raw_id, raw_classes in parser.eventon:
        if (not isinstance(href, str) or not 1 <= len(href) <= MAX_URL
                or not isinstance(label, str) or len(label) > MAX_NAME
                or norm_text(label) != norm_text(title)
                or not isinstance(raw_id, str)
                or not isinstance(raw_classes, str)
                or not {"evcal_list_a", "desc_trig"}.issubset(
                    set(raw_classes.split()))):
            continue
        parsed_id = EVC.fullmatch(raw_id)
        if parsed_id is None:
            continue
        try:
            stamp_day = datetime.fromtimestamp(
                int(parsed_id.group(1)), tz=timezone.utc).date()
        except (ValueError, OverflowError, OSError):
            continue
        # EventON timestamps can be based on a local date stored as UTC.
        # Allow one calendar-day offset to avoid losing near-midnight events,
        # but this is a ROUTING HINT only; independent page/date proof follows.
        if abs((stamp_day - candidate_day).days) > 1:
            continue
        found = urljoin(url, href)
        page = _url(found, host=host)
        if (page is None or page.query or page.fragment or found == url):
            continue
        matches.add(found)
        if len(matches) > 1:
            return _base("ambiguous_eventon_occurrence_or_link")
    if not matches:
        return _base("no_exact_eventon_occurrence")
    return dict(
        _base("eventon_page_needs_independent_session_proof"),
        first_party_event_page_nominated=True,
        reviewed_organizer={
            "approved_host": host, "exact_url": next(iter(matches))},
    )


def verify_eventon_page(nomination, fetched_event):
    """Exact independent first-party fetch, with no rights or approval."""
    if (not isinstance(nomination, dict)
            or nomination.get("schema") != SCHEMA
            or nomination.get("first_party_event_page_nominated") is not True
            or not isinstance(fetched_event, dict)
            or set(fetched_event) != {"url", "html"}):
        return False
    pin = nomination.get("reviewed_organizer")
    if (not isinstance(pin, dict)
            or set(pin) != {"approved_host", "exact_url"}
            or _url(pin.get("exact_url"), host=pin.get("approved_host")) is None):
        return False
    html = fetched_event.get("html")
    return (fetched_event.get("url") == pin["exact_url"]
            and isinstance(html, str) and 50 <= len(html) <= 500_000)


def redacted_eventon_stage(nomination):
    """Only fixed producer-owned reasons may leave the private runner."""
    reason = nomination.get("reason") if isinstance(nomination, dict) else None
    if reason not in SAFE_REASONS:
        reason = "invalid_or_unreviewed_index"
    return {
        "schema": SCHEMA, "reason": reason,
        "contains_event_url_or_id": False,
        "approval_granted": False, "publisher_connected": False,
        "public_writes": 0,
    }
