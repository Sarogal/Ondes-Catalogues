"""Strict read-only OpenAgenda API v2 provenance and timing evidence.

Discovery, geometry, organiser attestation, access rules, licence review,
historical deduplication, and publication are SEPARATE gates. This module
cannot confer approval, generate a publisher patch, or call a cloud writer.

OpenAgenda v2 GET /agendas/{agendaUID}/events/{eventUID} requires an API key.
A public read key gives public published data only; do not query with secret
keys or put a key into URL query parameters.
"""
from collections import Counter
from datetime import date, datetime, timedelta
import json
import math
import re
import unicodedata
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from proof import meters

SCHEMA = "ptitesondes.openagenda_v2_direct_source_evidence.v1"
API_ORIGIN = "https://api.openagenda.com"
MAX_BYTES = 600_000
MAX_TIMINGS = 800  # OpenAgenda's documented maximum.
MAX_DAYS_AHEAD = 184
FR_TZ = frozenset({
    "Europe/Paris", "America/Guadeloupe", "America/Martinique",
    "America/Cayenne", "Indian/Reunion", "Indian/Mayotte",
})
# Some source feeds represent French overseas departments by ISO territory
# codes. Require both independently declared administrative names rather than
# accepting any non-FR country that happens to be near a reviewed venue.
OVERSEAS_ADMIN = {
    "GP": frozenset(("guadeloupe",)),
    "MQ": frozenset(("martinique",)),
    "GF": frozenset(("guyane",)),
    "RE": frozenset(("reunion", "la reunion")),
    "YT": frozenset(("mayotte",)),
}
UID = re.compile(r"[0-9]{1,12}\Z")
SLUG = re.compile(r"[a-z0-9][a-z0-9-]{0,100}\Z")
TIME = re.compile(
    r"20[0-9]{2}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:"
    r"[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:?[0-9]{2})\Z"
)
CHILD = re.compile(
    r"\b(?:enfants?|bebes?|tout petits?|familles?|parents enfants|"
    r"jeune public|petits et grands|adolescents?|ados?)\b"
)
EXCLUSIVELY_ADULT = re.compile(
    r"\b(?:reserve aux adultes|adulte uniquement|interdit aux enfants|"
    r"sans enfants|public adulte seulement)\b"
)
# Only these stable, programmer-owned reason codes may leave private audit.
SAFE_REASONS = frozenset({
    "missing_or_unreviewed_source_registry",
    "candidate_url_uid_or_agenda_mismatch", "invalid_event_uid",
    "direct_api_event_uid_mismatch", "not_publicly_scheduled",
    "event_removed", "not_physical_family_event",
    "unreviewed_territory_timezone",
    "candidate_date_invalid_or_out_of_window", "api_title_mismatch",
    "geography_not_independently_verified", "candidate_venue_identity_mismatch",
    "invalid_age_claim", "family_audience_not_in_source_record",
    "source_rights_unknown", "invalid_or_oversized_timings",
    "no_explicit_timings", "malformed_timing", "invalid_timing_or_timezone",
    "invalid_timing_duration", "time_offset_not_matching_reviewed_timezone",
    "overnight_timing_needs_separate_contract", "duplicate_timing",
    "uid_has_no_exact_dated_occurrence",
    "await_independent_organizer_rights_duplicate_and_access_checks",
})


def _norm(value):
    if not isinstance(value, str):
        return ""
    value = unicodedata.normalize("NFKD", value.casefold())
    return " ".join(re.sub(r"[^a-z0-9]+", " ", "".join(
        c for c in value if not unicodedata.combining(c))).split())


def _uid(value):
    return ((type(value) is int and value > 0 and bool(UID.fullmatch(str(value))))
            or (isinstance(value, str) and bool(UID.fullmatch(value))
                and int(value) > 0))


def _valid_public_read_key(value):
    """Accept public read keys only, rejecting all HTTP header control chars."""
    return (
        isinstance(value, str)
        and value.startswith("oa_pk_")
        and 15 <= len(value) <= 256
        and not any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in value)
    )


def _source_parts(url):
    """Require a UID-prefixed OpenAgenda page with an explicit agenda slug."""
    if not isinstance(url, str) or len(url) > 700:
        return None
    try:
        u = urlsplit(url)
        if (u.scheme != "https" or u.hostname != "openagenda.com"
                or u.port not in (None, 443) or u.username or u.password
                or u.query or u.fragment):
            return None
        tokens = u.path.strip("/").split("/")
        if len(tokens) == 4 and tokens[0] in ("fr", "en"):
            tokens = tokens[1:]
        if len(tokens) != 3 or tokens[1] != "events":
            return None
        slug, _, event_part = tokens
        if not SLUG.fullmatch(slug):
            return None
        m = re.fullmatch(r"([0-9]{1,12})_([a-z0-9-]{1,140})", event_part)
        if not m:
            return None
        return slug, m.group(1)
    except ValueError:
        return None


def _calendar_review(reviewed):
    """Immutable agenda identity and timezone must be curated independently.

    Metadata in an event itself does not establish institutional ownership of
    its agenda. That verification occurs outside this adapter.
    """
    if not isinstance(reviewed, dict) or set(reviewed) != {
            "agenda_slug", "agenda_uid", "timezone"}:
        return False
    return (isinstance(reviewed["agenda_slug"], str)
            and SLUG.fullmatch(reviewed["agenda_slug"]) is not None
            and _uid(reviewed["agenda_uid"])
            and reviewed["timezone"] in FR_TZ)


def _fr(row, key):
    val = row.get(key)
    if isinstance(val, str):
        return val
    if isinstance(val, dict):
        return val.get("fr") if isinstance(val.get("fr"), str) else ""
    return ""


def _time(raw, timezone):
    if not isinstance(raw, str) or not TIME.fullmatch(raw):
        return None
    try:
        x = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        tz = ZoneInfo(timezone)
        if x.utcoffset() is None:
            return None
        return x.astimezone(tz)
    except (ValueError, OverflowError, ZoneInfoNotFoundError):
        return None


def _french_location(location):
    code = location.get("countryCode")
    if code == "FR":
        return True
    names = OVERSEAS_ADMIN.get(code)
    return bool(names and _norm(location.get("adminLevel1")) in names
                and _norm(location.get("adminLevel2")) in names)


def _venue(ev, approved):
    """Two independent coordinate sets: published OA and reviewed venue."""
    loc = ev.get("location")
    if not isinstance(loc, dict) or not isinstance(approved, dict):
        return False
    if (not isinstance(approved.get("aliases"), list)
            or not approved.get("aliases")
            or any(not isinstance(a, str) or not _norm(a)
                   for a in approved["aliases"])
            or not _norm(approved.get("city")) or not _norm(loc.get("name"))
            or not _norm(loc.get("adminLevel4"))
            or _norm(loc.get("adminLevel4")) != _norm(approved["city"])
            or _norm(loc.get("name")) not in {
                _norm(name) for name in approved["aliases"]
            } or not _french_location(loc)):
        return False
    a = (loc.get("latitude"), loc.get("longitude"))
    b = (approved.get("lat"), approved.get("lng"))
    if not all(type(v) in (int, float) and math.isfinite(v) for v in a + b):
        return False
    if (not all(-90 <= lat <= 90 and -180 <= lng <= 180
                for lat, lng in (a, b))):
        return False
    return meters(a, b) <= 65


def _sessions(event, timezone, target_day, today):
    timings = event.get("timings")
    if not isinstance(timings, list) or len(timings) > MAX_TIMINGS:
        return [], set(), "invalid_or_oversized_timings"
    if not timings:
        return [], set(), "no_explicit_timings"
    all_days = set()
    target_times = set()
    seen = set()
    for timing in timings:
        if not isinstance(timing, dict):
            return [], set(), "malformed_timing"
        begin = _time(timing.get("begin"), timezone)
        end = _time(timing.get("end"), timezone)
        if begin is None or end is None or not begin < end:
            return [], set(), "invalid_timing_or_timezone"
        duration = end.astimezone(ZoneInfo("UTC")) - begin.astimezone(ZoneInfo("UTC"))
        if not timedelta(0) < duration <= timedelta(hours=24):
            return [], set(), "invalid_timing_duration"
        if (begin.utcoffset() != datetime.fromisoformat(
                timing["begin"].replace("Z", "+00:00")).utcoffset() or
                end.utcoffset() != datetime.fromisoformat(
                timing["end"].replace("Z", "+00:00")).utcoffset()):
            # API v2 specifies an offset: do not accept a different local-zone
            # interpretation (including wrong DST and territory offsets).
            # UTC Z is *not* an appropriate claimed local offset.
            return [], set(), "time_offset_not_matching_reviewed_timezone"
        if begin.date() != end.date():
            return [], set(), "overnight_timing_needs_separate_contract"
        slot = (begin.isoformat(), end.isoformat())
        if slot in seen:
            return [], set(), "duplicate_timing"
        seen.add(slot)
        day = begin.date()
        all_days.add(day.isoformat())
        if day == target_day:
            target_times.add(begin.strftime("%H:%M"))
    if not target_times:
        return [], all_days, "uid_has_no_exact_dated_occurrence"
    return sorted(target_times), all_days, ""


def review_direct_v2(lead, api_event, reviewed_agenda, registered_venue, today):
    """Verify a single candidate against authenticated OpenAgenda *read* data.

    Returns a non-publishable source diagnostic. Never accepts an 'approved'
    flag supplied by intake, and never trusts API coordinates as independent.
    """
    result = {
        "schema": SCHEMA, "mode": "isolated_direct_source_evidence_only",
        "source_evidence_structurally_valid": False,
        "api_family_audience_confirmed": False,
        "event_kind": "unverified",
        "explicit_local_times_for_candidate_day": [],
        "explicit_dated_days_count": 0,
        "organizer_independently_attested": False,
        "rights_reviewed": False,
        "published_duplicate_checked": False,
        "age_and_access_fully_verified": False,
        "publisher_connected": False, "approval_granted": False,
        "public_writes": 0,
    }

    def fail(reason):
        return dict(result, reason=reason)

    if (not isinstance(lead, dict) or not isinstance(api_event, dict)
            or type(today) is not date or not _calendar_review(reviewed_agenda)):
        return fail("missing_or_unreviewed_source_registry")
    p = _source_parts(lead.get("source_url"))
    if p is None or p != (
            reviewed_agenda["agenda_slug"], str(lead.get("external_id"))):
        return fail("candidate_url_uid_or_agenda_mismatch")
    if not _uid(lead.get("external_id")) or not _uid(api_event.get("uid")):
        return fail("invalid_event_uid")
    if str(api_event["uid"]) != lead["external_id"]:
        return fail("direct_api_event_uid_mismatch")
    if (type(api_event.get("state")) is not int or api_event["state"] != 2
            or type(api_event.get("status")) is not int
            or api_event["status"] != 1):
        return fail("not_publicly_scheduled")
    if api_event.get("removed") is True:
        return fail("event_removed")
    if api_event.get("attendanceMode") not in (1, 3):
        return fail("not_physical_family_event")
    if api_event.get("timezone") != reviewed_agenda["timezone"]:
        return fail("unreviewed_territory_timezone")
    try:
        target_day = date.fromisoformat(lead["date_start"])
        if (not today <= target_day <= today + timedelta(days=MAX_DAYS_AHEAD)
                or lead.get("date_end") != target_day.isoformat()):
            return fail("candidate_date_invalid_or_out_of_window")
    except (ValueError, TypeError, KeyError):
        return fail("candidate_date_invalid_or_out_of_window")
    if (not _norm(_fr(api_event, "title")) or not _norm(lead.get("title"))
            or _norm(_fr(api_event, "title")) != _norm(lead.get("title"))):
        return fail("api_title_mismatch")
    if not _venue(api_event, registered_venue):
        return fail("geography_not_independently_verified")
    if (not _norm(lead.get("city")) or not _norm(lead.get("venue"))
            or _norm(api_event["location"].get("adminLevel4")) != _norm(lead.get("city"))
            or _norm(api_event["location"].get("name")) != _norm(lead.get("venue"))):
        return fail("candidate_venue_identity_mismatch")
    age = api_event.get("age")
    if age is not None:
        if not isinstance(age, dict):
            return fail("invalid_age_claim")
        vals = [age.get(k) for k in ("min", "max") if age.get(k) is not None]
        if not all(type(v) is int and 0 <= v <= 120 for v in vals):
            return fail("invalid_age_claim")
        if (type(age.get("min")) is int and type(age.get("max")) is int
                and age["min"] > age["max"]):
            return fail("invalid_age_claim")
    desc = _norm(" ".join((_fr(api_event, key) for key in (
        "title", "description", "longDescription"))))
    age_child = isinstance(age, dict) and type(age.get("max")) is int and age["max"] <= 17
    if EXCLUSIVELY_ADULT.search(desc):
        return fail("family_audience_not_in_source_record")
    # A neutral source description may be corroborated by a separately
    # pinned first-party organizer session; it is NOT family proof by itself.
    api_family_cue = bool(CHILD.search(desc) or age_child)
    # OpenAgenda API v2 represents rights.license as an object, not a
    # string. These fields are attribution evidence, NEVER proof that the
    # event's creator is the organiser or that reuse terms were reviewed.
    rights = api_event.get("rights")
    license_info = rights.get("license") if isinstance(rights, dict) else None
    licensor = rights.get("licensor") if isinstance(rights, dict) else None
    if (not isinstance(license_info, dict)
            or not isinstance(license_info.get("id"), str)
            or not license_info["id"].strip()
            or not isinstance(licensor, dict)
            or not isinstance(licensor.get("name"), str)
            or not licensor["name"].strip()):
        return fail("source_rights_unknown")
    clocks, all_days, err = _sessions(
        api_event, reviewed_agenda["timezone"], target_day, today)
    if err:
        return fail(err)
    # Multiple dated days under one immutable UID must not be expanded into
    # daily catalogue cards, even if times are explicit. The organiser and
    # editorial grouping contract must decide whether this is a series,
    # exhibition or one event displayed as a date range.
    if len(all_days) > 1:
        kind = "multi_day_one_uid_hold_for_grouping"
    else:
        kind = "single_explicit_dated_occurrence"
    return dict(result,
                source_evidence_structurally_valid=True,
                api_family_audience_confirmed=api_family_cue,
                event_kind=kind,
                explicit_dated_days_count=len(all_days),
                explicit_local_times_for_candidate_day=clocks,
                reason="await_independent_organizer_rights_duplicate_and_access_checks")


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def read_direct_v2(agenda_uid, event_uid, public_read_key, opener=None):
    """Bounded, no-redirect, public-only API v2 read; zero publication rights.

    Requires independently pinned agenda UID; fails closed if key or provider
    unavailable. Never logs a secret or falls back to ODS / arbitrary HTML.
    """
    if not _uid(agenda_uid) or not _uid(event_uid):
        raise ValueError("invalid_immutable_uid")
    if not _valid_public_read_key(public_read_key):
        raise ValueError("public_read_key_unavailable_or_not_public")
    url = (API_ORIGIN + "/v2/agendas/" + str(agenda_uid)
           + "/events/" + str(event_uid))
    request = Request(url, headers={
        "key": public_read_key,
        "Accept": "application/json",
        "User-Agent": "PtitesOndesIndependentOAV2ReadOnly/1.0",
    })
    fetch = opener or build_opener(_NoRedirect()).open
    try:
        with fetch(request, timeout=18) as response:
            if (response.geturl() != url or response.status != 200):
                raise ValueError("direct_api_unexpected_endpoint_or_status")
            raw = response.read(MAX_BYTES + 1)
    except (OSError, TimeoutError) as exc:
        raise ValueError("direct_api_unavailable") from None
    if len(raw) > MAX_BYTES:
        raise ValueError("direct_api_response_too_large")
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise ValueError("direct_api_response_not_json") from None
    if not isinstance(payload, dict):
        raise ValueError("direct_api_response_invalid_shape")
    # Exact GET /events/{uid} is specified to return an event record,
    # never silently accept a list whose first row merely resembles it.
    return payload


def read_direct_agenda_v2(agenda_uid, public_read_key, opener=None):
    """Read published OpenAgenda metadata without granting ownership.

    GET /v2/agendas/{agendaUID} supplies exact UID and slug identity but
    even official=1 and an institution-looking url are self-asserted API
    metadata. An independently fetched institutional page is still needed.
    """
    if not _uid(agenda_uid):
        raise ValueError("invalid_immutable_agenda_uid")
    if not _valid_public_read_key(public_read_key):
        raise ValueError("public_read_key_unavailable_or_not_public")
    url = API_ORIGIN + "/v2/agendas/" + str(agenda_uid)
    request = Request(url, headers={
        "key": public_read_key,
        "Accept": "application/json",
        "User-Agent": "PtitesOndesIndependentOAV2ReadOnly/1.0",
    })
    fetch = opener or build_opener(_NoRedirect()).open
    try:
        with fetch(request, timeout=18) as response:
            if response.geturl() != url or response.status != 200:
                raise ValueError("direct_agenda_unexpected_endpoint_or_status")
            raw = response.read(250_001)
    except (OSError, TimeoutError):
        raise ValueError("direct_agenda_unavailable") from None
    if len(raw) > 250_000:
        raise ValueError("direct_agenda_response_too_large")
    try:
        result = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise ValueError("direct_agenda_invalid_json") from None
    if (not isinstance(result, dict)
            or not _uid(result.get("uid"))
            or str(result["uid"]) != str(agenda_uid)
            or not isinstance(result.get("slug"), str)
            or SLUG.fullmatch(result["slug"]) is None):
        raise ValueError("direct_agenda_uid_or_slug_invalid")
    return result


def redacted_batch_report(reports):
    """Only non-identifying counts, suitable for public runner summaries."""
    if not isinstance(reports, list) or len(reports) > 100:
        raise ValueError("invalid_batch")
    counts = Counter()
    for report in reports:
        if (not isinstance(report, dict) or report.get("schema") != SCHEMA
                or report.get("public_writes") != 0
                or report.get("approval_granted") is not False
                or report.get("reason") not in SAFE_REASONS):
            raise ValueError("invalid_source_report")
        counts[report["reason"]] += 1
    return {
        "schema": "ptitesondes.openagenda_v2_source_aggregate.v1",
        "checked": len(reports),
        "reason_counts": dict(sorted(counts.items())),
        "approved_events": 0, "public_writes": 0,
        "contains_private_candidate_data": False,
    }
