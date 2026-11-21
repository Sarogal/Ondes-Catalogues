"""Private exact-session cross-reading: OpenAgenda v2 versus NEW source domains.

Discovery has no fixed city, venue, organizer, domain, or editorial-term list.
The source is linked from a DILA-corroborated municipal page (#588), fetched
with pinned public IP and TLS (#590). OA UID, slug, title and every exact
session are re-read from OA's public API (#580/#586) before comparison.

An exact structured occurrence is a RESEARCH signal, not official ownership,
independent provenance, re-use rights, geography, family access or publication.
In particular, OpenAgenda and the HTML page may carry syndicated copies of
the same underlying organizer data. Never connect this output to a publisher.
"""
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
import json
import re

from proof import norm
from ptitesondes_dynamic_municipal_source_links import (
    SCHEMA as LINK_SCHEMA, _safe_url,
)
from ptitesondes_openagenda_national_event_research import (
    _french_text, _time_sessions, MAX_TIMINGS,
)
from ptitesondes_openagenda_v2_direct_evidence import (
    _valid_public_read_key, read_direct_agenda_v2, read_direct_v2,
)
from ptitesondes_unlisted_source_safe_recheck import read_unknown_https

SCHEMA = "ptitesondes.unlisted_exact_session_research.v1"
MAX_HTML = 350_000
MAX_SCRIPTS = 300
MAX_NODES = 8000
MAX_DEPTH = 24
MAX_BLOCK_BYTES = 350_000
MAX_MATCHED_SESSIONS = MAX_TIMINGS
ISO_WITH_OFFSET = re.compile(
    r"20[0-9]{2}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}"
    r"(?::[0-9]{2}(?:\.[0-9]{1,6})?)?(?:Z|[+-][0-9]{2}:[0-9]{2})\Z"
)


class _JsonLD(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.active = False
        self.parts = []
        self.part_size = 0
        self.blocks = []
        self.exceeded = False

    def handle_starttag(self, tag, attrs):
        if tag != "script":
            return
        attr = dict(attrs)
        self.active = (str(attr.get("type") or "").lower().split(";", 1)[0].strip()
                       == "application/ld+json")
        self.parts = []
        self.part_size = 0

    def handle_data(self, data):
        if self.active:
            if self.part_size + len(data) > MAX_BLOCK_BYTES:
                self.exceeded = True
                self.active = False
                self.parts = []
                return
            self.parts.append(data)
            self.part_size += len(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.active:
            if len(self.blocks) >= MAX_SCRIPTS:
                self.exceeded = True
            else:
                self.blocks.append("".join(self.parts))
            self.active = False
            self.parts = []


def _nodes(document):
    """Walk bounded JSON-LD graphs without limiting the event vocabulary."""
    pending = [(document, 0)]
    seen = 0
    while pending:
        value, depth = pending.pop()
        seen += 1
        if seen > MAX_NODES or depth > MAX_DEPTH:
            raise ValueError("unbounded_jsonld_graph")
        if isinstance(value, list):
            pending.extend((item, depth + 1) for item in reversed(value))
        elif isinstance(value, dict):
            yield value
            # Only JSON-LD structural subgraphs are traversed, not arbitrary
            # organizer text or URL values posing as event objects.
            for key in ("@graph", "subEvent", "mainEntity",
                        "itemListElement", "item", "event"):
                if key in value:
                    pending.append((value[key], depth + 1))


def _is_event(value):
    kinds = value.get("@type")
    if isinstance(kinds, str):
        kinds = [kinds]
    if not isinstance(kinds, list):
        return False
    for kind in kinds:
        if not isinstance(kind, str):
            continue
        terminal = kind.rstrip("/").rsplit("/", 1)[-1].rsplit("#", 1)[-1]
        if terminal.lower().endswith("event"):
            return True
    return False


def _instant(value):
    if type(value) is not str or ISO_WITH_OFFSET.fullmatch(value) is None:
        return None
    try:
        t = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if t.utcoffset() is None:
            return None
        return t
    except (ValueError, OverflowError):
        return None


def _interval(value):
    if not isinstance(value, dict):
        return None
    a, b = _instant(value.get("begin")), _instant(value.get("end"))
    if a is None or b is None or not a < b or b - a > timedelta(days=2):
        return None
    return a, b


def _location_state(node, lead):
    """Optional venue/city corroboration; unknown != contradictory."""
    locations = node.get("location")
    locations = locations if isinstance(locations, list) else [locations]
    claims = []
    for location in locations:
        if not isinstance(location, dict):
            continue
        venue = location.get("name")
        if not isinstance(venue, str):
            venue = None
        address = location.get("address")
        city = (address.get("addressLocality")
                if isinstance(address, dict) else None)
        if not isinstance(city, str):
            city = None
        if venue or city:
            claims.append((venue, city))
    known_venue = lead.get("venue_unverified")
    known_city = lead.get("city_unverified")
    known_venue = norm(known_venue) if isinstance(known_venue, str) else None
    known_city = norm(known_city) if isinstance(known_city, str) else None
    matching = False
    for venue, city in claims:
        venue_match = (norm(venue) == known_venue
                       if venue and known_venue else None)
        city_match = (norm(city) == known_city
                      if city and known_city else None)
        # Conflicting data anywhere in a multi-location list cannot be
        # hidden by one matching venue appearing earlier in the same node.
        if venue_match is False or city_match is False:
            return "source_location_conflicts"
        if venue_match is True or city_match is True:
            matching = True
    if matching:
        return "matching_source_location_claim"
    return "location_not_comparable" if claims else "source_location_not_stated"


def _structured_source_sessions(html, lead, intervals):
    """Compare each *individual* exact instant; no day or recurrence guessing."""
    if not isinstance(html, str) or not 0 < len(html.encode("utf-8")) <= MAX_HTML:
        raise ValueError("invalid_source_html")
    parser = _JsonLD()
    parser.feed(html)
    parser.close()
    if parser.exceeded:
        raise ValueError("structured_data_unbounded")
    expected_title = norm(lead["title"])
    target = {(a, b): _interval({"begin": a, "end": b})
              for a, b in intervals}
    if len(target) != len(intervals) or any(v is None for v in target.values()):
        raise ValueError("invalid_oa_intervals")
    status = {}
    event_nodes = 0
    for block in parser.blocks:
        try:
            doc = json.loads(block)
        except (ValueError, TypeError, RecursionError):
            continue
        for node in _nodes(doc):
            if not _is_event(node):
                continue
            event_nodes += 1
            if event_nodes > MAX_NODES:
                raise ValueError("unbounded_event_nodes")
            if not isinstance(node.get("name"), str):
                continue
            if norm(node["name"]) != expected_title:
                continue
            state = node.get("eventStatus")
            if isinstance(state, dict):
                state = state.get("@id")
            states = state if isinstance(state, list) else [state]
            states = [value.get("@id") if isinstance(value, dict) else value
                      for value in states]
            if any(
                    isinstance(value, str)
                    and any(marker in value.lower()
                            for marker in ("cancelled", "canceled",
                                           "postponed", "rescheduled"))
                    for value in states):
                # One explicit cancellation/reprogramming is a conflict for
                # this exact occurrence, not a publication-friendly positive.
                disposition = "source_changed_or_cancelled"
            else:
                disposition = None
            start = _instant(node.get("startDate"))
            end = _instant(node.get("endDate"))
            if start is None or end is None or not start < end:
                continue
            for key, (a, b) in target.items():
                if start == a and end == b:
                    geo = _location_state(node, lead)
                    state_here = (disposition or
                                  ("source_venue_conflicts"
                                   if geo == "source_location_conflicts"
                                   else "exact_structured_interval_seen"))
                    # Any conflicting source node vetoes a positive duplicate,
                    # regardless of node order.
                    rank = {"source_changed_or_cancelled": 3,
                            "source_venue_conflicts": 2,
                            "exact_structured_interval_seen": 1}
                    old = status.get(key)
                    if old is None or rank[state_here] > rank[old]:
                        status[key] = state_here
    positives = [
        {"begin": begin, "end": end}
        for begin, end in intervals
        if status.get((begin, end)) == "exact_structured_interval_seen"
    ]
    return {
        "exact_source_session_intervals": positives,
        "exact_source_session_count": len(positives),
        "source_changed_or_cancelled_count": sum(
            status.get((begin, end)) == "source_changed_or_cancelled"
            for begin, end in intervals),
        "source_venue_conflict_count": sum(
            status.get((begin, end)) == "source_venue_conflicts"
            for begin, end in intervals),
        "source_structured_event_nodes_examined": event_nodes,
    }


def _blank(status):
    return {
        "schema": SCHEMA, "status": status,
        "oa_uid_slug_rechecked_live": False,
        "oa_timing_rechecked_live": False,
        "source_exact_session_count": 0,
        "source_sessions_claimed_not_independent": [],
        "source_changed_or_cancelled_count": 0,
        "source_venue_conflict_count": 0,
        "source_structured_event_nodes_examined": 0,
        "organizer_independently_attested": False,
        "event_source_independent_from_openagenda": False,
        "rights_reviewed": False,
        "family_eligibility_verified": False,
        "venue_geography_verified": False,
        "access_conditions_verified": False,
        "publisher_connected": False,
        "publication_ready": False,
        "approval_granted": False,
        "public_writes": 0,
    }


def review_unlisted_exact_sessions(
        lead, links, url, public_read_key, today, *,
        agenda_reader=read_direct_agenda_v2,
        event_reader=read_direct_v2,
        source_reader=read_unknown_https):
    """Re-read OA UID/slug/event and unlisted source; never approve anything."""
    result = _blank("untrusted_or_incomplete_private_lead")
    if (not isinstance(lead, dict) or not isinstance(links, dict)
            or type(today) is not date
            or not _valid_public_read_key(public_read_key)
            or lead.get("publication_ready") is not False
            or lead.get("public_writes") != 0
            or not isinstance(lead.get("title"), str)
            or not 1 <= len(lead["title"]) <= 300
            or type(lead.get("agenda_uid")) is not int
            or not 0 < lead["agenda_uid"] < 10**12
            or type(lead.get("event_uid")) is not int
            or not 0 < lead["event_uid"] < 10**12
            or not isinstance(lead.get("agenda_slug"), str)
            or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,100}", lead["agenda_slug"])
            or not isinstance(lead.get("explicit_source_session_intervals"), list)
            or not 1 <= len(lead["explicit_source_session_intervals"]) <= MAX_TIMINGS
            or links.get("schema") != LINK_SCHEMA
            or links.get("status") != "private_source_link_research_only"
            or links.get("municipal_domain_confirmed_by_dila") is not True
            or links.get("candidate_domains_officially_approved") is not False
            or not isinstance(links.get("source_candidates"), list)
            or not _safe_url(url)
            or not any(isinstance(item, dict)
                       and item.get("url") == url
                       and item.get("source_ownership_unverified") is True
                       and item.get("publication_ready") is False
                       for item in links["source_candidates"])):
        return result
    candidate = lead["explicit_source_session_intervals"]
    if any(not isinstance(x, dict) or
           set(x) != {"begin", "end"} or _interval(x) is None
           for x in candidate):
        return result
    pairs = [(x["begin"], x["end"]) for x in candidate]
    if len(set(pairs)) != len(pairs):
        return result
    try:
        agenda = agenda_reader(lead["agenda_uid"], public_read_key)
        if (not isinstance(agenda, dict)
                or str(agenda.get("uid")) != str(lead["agenda_uid"])
                or agenda.get("slug") != lead["agenda_slug"]):
            return _blank("live_oa_agenda_uid_slug_conflict")
    except (OSError, ValueError, TypeError, KeyError, TimeoutError):
        return _blank("live_oa_agenda_unavailable")
    try:
        api = event_reader(lead["agenda_uid"], lead["event_uid"],
                           public_read_key)
    except (OSError, ValueError, TypeError, KeyError, TimeoutError):
        return _blank("live_oa_event_unavailable")
    if (not isinstance(api, dict)
            or type(api.get("uid")) is not int
            or api["uid"] != lead["event_uid"]
            or type(api.get("state")) is not int or api["state"] != 2
            or api.get("removed") is True
            or type(api.get("status")) is not int
            or api["status"] not in (1, 2)
            or norm(_french_text(api, "title")) != norm(lead["title"])):
        return _blank("live_oa_event_identity_or_status_conflict")
    loc = api.get("location") if isinstance(api.get("location"), dict) else {}
    if ((isinstance(lead.get("city_unverified"), str)
         and norm(lead["city_unverified"]) != norm(loc.get("adminLevel4")))
        or (isinstance(lead.get("venue_unverified"), str)
            and norm(lead["venue_unverified"]) != norm(loc.get("name")))):
        return _blank("live_oa_event_location_changed")
    current, _ = _time_sessions(api.get("timings"), today)
    if current != candidate:
        return _blank("live_oa_exact_timings_changed")
    try:
        html = source_reader(url)
        matched = _structured_source_sessions(html, lead, pairs)
    except (OSError, ValueError, TypeError, KeyError, TimeoutError,
            UnicodeError, RecursionError):
        return _blank("unlisted_source_not_recheckable")
    status = ("structured_source_exact_sessions_research_only"
              if matched["exact_source_session_count"] else
              "no_exact_structured_source_sessions_yet")
    if api["status"] == 2:
        status = "rescheduled_needs_independent_current_session_confirmation"
    return {
        **_blank(status),
        "oa_uid_slug_rechecked_live": True,
        "oa_timing_rechecked_live": True,
        "source_exact_session_count": matched["exact_source_session_count"],
        "source_sessions_claimed_not_independent":
            matched["exact_source_session_intervals"],
        "source_changed_or_cancelled_count":
            matched["source_changed_or_cancelled_count"],
        "source_venue_conflict_count":
            matched["source_venue_conflict_count"],
        "source_structured_event_nodes_examined":
            matched["source_structured_event_nodes_examined"],
    }


def public_redacted_exact_session_summary(reports):
    """Aggregate only, never leak source URL, date, name, venue or coordinates."""
    if (not isinstance(reports, list) or len(reports) > 200):
        raise ValueError("invalid_private_exact_session_reports")
    allowed = {
        "structured_source_exact_sessions_research_only",
        "no_exact_structured_source_sessions_yet",
        "rescheduled_needs_independent_current_session_confirmation",
        "untrusted_or_incomplete_private_lead",
        "live_oa_agenda_uid_slug_conflict", "live_oa_agenda_unavailable",
        "live_oa_event_unavailable", "live_oa_event_identity_or_status_conflict",
        "live_oa_event_location_changed", "live_oa_exact_timings_changed",
        "unlisted_source_not_recheckable",
    }
    counts = {x: 0 for x in allowed}
    for report in reports:
        if (not isinstance(report, dict) or report.get("schema") != SCHEMA
                or report.get("status") not in allowed
                or report.get("publisher_connected") is not False
                or report.get("publication_ready") is not False
                or report.get("public_writes") != 0
                or type(report.get("source_exact_session_count")) is not int
                or not 0 <= report["source_exact_session_count"] <= MAX_TIMINGS):
            raise ValueError("invalid_private_exact_session_report")
        counts[report["status"]] += 1
    return {
        "schema": SCHEMA + ".aggregate",
        "checked": len(reports),
        "status_counts": {k: v for k, v in sorted(counts.items()) if v},
        "publisher_connected": False, "publication_ready": False,
        "public_writes": 0,
    }
