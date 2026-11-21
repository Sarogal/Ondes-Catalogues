"""Read-only OpenAgenda v2 provenance, grouping and ODS fallback PRE-INTEGRATION.

This module has no IO, no secrets, no catalogue/patch constructors and no
approval authority. Registry data MUST be independently curated outside
untrusted intake. The results are routing diagnostics, not admission permits.
"""
from datetime import date, datetime, timedelta
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from ptitesondes_openagenda_v2_direct_evidence import FR_TZ

# Stay in sync with the independent direct evidence verifier (#573).
# Regional geographic evidence must still be independently checked.
TRUSTED_TZ = FR_TZ
SCHEMA = "ptitesondes.oa2.preintegration.v1"
MAX_SLOTS = 800


def _uid(value):
    return ((type(value) is int and 0 < value <= 999999999999)
            or (isinstance(value, str) and value.isascii()
                and value.isdigit() and 0 < int(value) <= 999999999999))


def _fixed_https(url):
    if not isinstance(url, str) or len(url) > 1000:
        return None
    try:
        u = urlsplit(url)
        if (u.scheme != "https" or not u.hostname or u.username
                or u.password or u.query or u.fragment
                or u.port not in (None, 443)):
            return None
        return u
    except ValueError:
        return None


def agenda_identity_for_review(api_agenda, curated):
    """Validate exact agenda identity; do not assert institutional ownership.

    'curated' is a maintainer-reviewed registry entry, not an intake field.
    A URL set by an OpenAgenda account is self-asserted; institutional
    ownership still requires a separately retrieved official-site reference.
    """
    result = {
        "schema": SCHEMA, "identity_consistent": False,
        "ownership_attested": False, "publishing_authorized": False,
        "reason": "unreviewed_agenda",
    }
    if not isinstance(api_agenda, dict) or not isinstance(curated, dict):
        return result
    required = {"agenda_uid", "agenda_slug", "timezone",
                "institution_url", "authority_reference_url"}
    if set(curated) != required or not _uid(curated["agenda_uid"]):
        return result
    slug = curated["agenda_slug"]
    if (not isinstance(slug, str) or not slug
            or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-"
                   for c in slug)
            or curated["timezone"] not in TRUSTED_TZ
            or _fixed_https(curated["institution_url"]) is None
            or _fixed_https(curated["authority_reference_url"]) is None):
        return result
    source = _fixed_https(curated["institution_url"])
    proof = _fixed_https(curated["authority_reference_url"])
    if source.hostname != proof.hostname:
        return result
    if (not _uid(api_agenda.get("uid"))
            or str(api_agenda["uid"]) != str(curated["agenda_uid"])
            or api_agenda.get("slug") != slug):
        return dict(result, reason="agenda_uid_or_slug_mismatch")
    # 'official: 1' is useful API metadata, but it is NOT independent proof.
    return dict(result, identity_consistent=True,
                reason="requires_independent_institutional_link")


def independently_linked_agenda(identity, curated, fetched_official_page):
    """Find an exact OA link on an HTTPS institutional page, read separately.

    The caller MUST have pinned and safely fetched the response from
    curated.authority_reference_url (same origin, no redirect, bounded body).
    This function validates content only, never grants organiser attestation.
    """
    if (not isinstance(identity, dict)
            or identity.get("schema") != SCHEMA
            or identity.get("identity_consistent") is not True
            or not isinstance(fetched_official_page, dict)
            or not isinstance(curated, dict)):
        return False
    if fetched_official_page.get("url") != curated.get("authority_reference_url"):
        return False
    body = fetched_official_page.get("text")
    if not isinstance(body, str) or len(body) > 500000:
        return False
    slug = curated.get("agenda_slug")
    # Match an actual exact OpenAgenda agenda link; simple substring matches
    # would accept /villeurbanne-fake or openagenda.com.evil.test.
    from html.parser import HTMLParser
    class Links(HTMLParser):
        def __init__(self):
            super().__init__()
            self.hrefs = []
        def handle_starttag(self, tag, attrs):
            if tag == "a":
                self.hrefs.extend(v for k, v in attrs if k == "href")
    parser = Links()
    parser.feed(body)
    for href in parser.hrefs:
        parsed = _fixed_https(href)
        if (parsed is not None and parsed.hostname == "openagenda.com"
                and parsed.path.strip("/") in (slug, "fr/" + slug, "en/" + slug)):
            return True
    return False


def _slots(event, timezone):
    """Return validated, ordered ISO slots; None on any ambiguity."""
    values = event.get("timings") if isinstance(event, dict) else None
    if (not isinstance(values, list) or not 1 <= len(values) <= MAX_SLOTS
            or timezone not in TRUSTED_TZ):
        return None
    slots = []
    try:
        tz = ZoneInfo(timezone)
        for item in values:
            if not isinstance(item, dict):
                return None
            a, b = item.get("begin"), item.get("end")
            if not isinstance(a, str) or not isinstance(b, str):
                return None
            start = datetime.fromisoformat(a.replace("Z", "+00:00"))
            end = datetime.fromisoformat(b.replace("Z", "+00:00"))
            if start.tzinfo is None or end.tzinfo is None:
                return None
            local_start, local_end = start.astimezone(tz), end.astimezone(tz)
            if (start.utcoffset() != local_start.utcoffset()
                    or end.utcoffset() != local_end.utcoffset()
                    or not timedelta(0) < end - start <= timedelta(hours=24)
                    or local_start.date() != local_end.date()):
                return None
            slots.append((local_start.isoformat(), local_end.isoformat()))
    except (ValueError, TypeError, OverflowError):
        return None
    if len(set(slots)) != len(slots):
        return None
    slots.sort()
    for previous, current in zip(slots, slots[1:]):
        if datetime.fromisoformat(previous[1]) > datetime.fromisoformat(current[0]):
            return None
    return slots


def group_multi_day(event, external_organizer_schedule=None,
                    reviewed_organizer_origin=None):
    """Distinguish one-day, continuous period, series, and uncertain repeat.

    The externally supplied schedule MUST be separately authenticated by the
    organizer gate. Classification never grants a publishable occurrence.
    """
    base = {
        "schema": SCHEMA, "kind": "unverified",
        "daily_cards_authorized": False, "publication_authorized": False,
        "reason": "invalid_source_slots",
    }
    if not isinstance(event, dict) or not _uid(event.get("uid")):
        return base
    tz = event.get("timezone")
    slots = _slots(event, tz)
    if slots is None:
        return base
    days = sorted({a[:10] for a, _ in slots})
    identifier = str(event["uid"])
    if len(days) == 1:
        return dict(base, kind="one_day_explicit_slots",
                    explicit_day_count=1, reason="other_gates_required")
    grouped = dict(base, kind="multi_day_unresolved",
                   explicit_day_count=len(days),
                   reason="independent_organizer_schedule_required")
    s = external_organizer_schedule
    if not isinstance(s, dict) or str(s.get("event_uid")) != identifier:
        return grouped
    source = _fixed_https(s.get("source_url"))
    reviewed = _fixed_https(reviewed_organizer_origin)
    if source is None or reviewed is None or source.hostname != reviewed.hostname:
        return grouped
    if s.get("presentation") == "continuous_period":
        start, end = s.get("date_start"), s.get("date_end")
        if start == days[0] and end == days[-1]:
            return dict(grouped, kind="continuous_period_for_editorial_review",
                        reason="range_representation_requires_editorial_review")
        # The organiser may document only ONE portion of a much longer
        # programme. This is not proof that the other dates, nor each
        # individual OpenAgenda timing, is a public session. Never synthesize
        # a daily fiche from this subset.
        if (isinstance(start, str) and isinstance(end, str)
                and start in days and end in days and start < end):
            window = [day for day in days if start <= day <= end]
            if len(window) >= 2:
                return dict(
                    grouped,
                    kind="partial_continuous_period_for_editorial_review",
                    independently_confirmed_window_days=len(window),
                    reason="only_official_subperiod_confirmed_no_daily_sessions",
                )
    if s.get("presentation") == "separate_sessions":
        proposed = s.get("confirmed_slots")
        if isinstance(proposed, list) and all(
                isinstance(x, dict)
                and isinstance(x.get("begin"), str)
                and isinstance(x.get("end"), str) for x in proposed):
            src_slots = _slots({"timings": proposed}, tz)
            if src_slots == slots:
                return dict(grouped, kind="separate_sessions_for_editorial_review",
                            reason="session_series_requires_historic_dedup")
    return grouped


def ods_fallback_preflight(ods_state, direct_result, agenda_identity,
                           grouping, historic_uid_exists=None,
                           independently_linked=False,
                           first_party_session_evidence=None):
    """Assess whether ODS absence MAY be investigated using direct API proof.

    No boolean named approved; this is a non-publishing routing diagnostic.
    ODS disagreement OR outage is a hold, never a trigger to prefer a
    convenient direct result. Exact-UID absence must be proven positively. Every successful result still requires independent
    organiser, rights, access, categories and historical merge checks.
    """
    report = {
        "schema": SCHEMA, "route": "hold",
        "publisher_connected": False, "approval_granted": False,
        "public_writes": 0, "reason": "not_ready",
    }
    # A network timeout is NOT proof the mirror lacks this immutable UID.
    # Only a completed ODS query with exactly zero rows may enable review.
    if ods_state != "uid_absent":
        return dict(report, reason="ods_unavailable_present_or_conflicting")
    if historic_uid_exists is not False:
        return dict(report, reason="historical_uid_exists_or_unknown")
    if (not isinstance(direct_result, dict)
            or direct_result.get("schema") != "ptitesondes.openagenda_v2_direct_source_evidence.v1"
            or direct_result.get("source_evidence_structurally_valid") is not True
            or direct_result.get("approval_granted") is not False
            or direct_result.get("public_writes") != 0):
        return dict(report, reason="direct_source_not_verified")
    if (not isinstance(agenda_identity, dict)
            or agenda_identity.get("schema") != SCHEMA
            or agenda_identity.get("identity_consistent") is not True):
        return dict(report, reason="agenda_identity_not_consistent")
    # Some organizers maintain their own definitive program without linking
    # back to the OpenAgenda home page. An independently reviewed first-party
    # page containing EACH exact session may substitute only for the missing
    # agenda-homepage link, never for identity, time, GPS, rights or history.
    fp = first_party_session_evidence
    first_party_ok = (
        isinstance(fp, dict)
        and fp.get("schema") == "ptitesondes.oa2.independent_organizer_session.v1"
        and fp.get("official_session_evidence_consistent") is True
        and fp.get("organizer_ownership_attested") is False
        and fp.get("rights_reviewed") is False
        and fp.get("age_access_fully_verified") is False
        and fp.get("approval_granted") is False
        and fp.get("public_writes") == 0
    )
    # An institution linking its calendar is not evidence that this particular
    # neutral-audience event is suitable for families. Only an independently
    # checked first-party dated session can supply the missing audience cue.
    if (direct_result.get("api_family_audience_confirmed") is not True
            and not first_party_ok):
        return dict(report, reason="family_audience_requires_independent_session")
    if independently_linked is not True and not first_party_ok:
        return dict(report, reason="no_independent_institutional_or_first_party_session_evidence")
    if (not isinstance(grouping, dict) or grouping.get("schema") != SCHEMA
            or grouping.get("publication_authorized") is not False):
        return dict(report, reason="grouping_not_checked")
    if grouping.get("kind") != "one_day_explicit_slots":
        return dict(report, reason="multi_day_requires_grouping")
    return dict(report, route="direct_source_candidate_for_remaining_gates",
                reason="organiser_rights_access_category_and_dedup_still_required")


def review_missing_mirror_source(
        lead, curated_agenda, registered_venue, today, public_read_key,
        published_events, *, ods_probe=None, agenda_reader=None,
        event_reader=None, institutional_page=None,
        organizer_registry=None, organizer_page=None):
    """Route a proven ODS-missing UID into the EXISTING direct OA verifiers.

    Deliberately read-only: neither a claim in private intake nor a cached
    "approved" flag may grant publication. The caller supplies separately
    reviewed agenda/venue registries, a fresh public catalogue, and optionally
    independently fetched institutional/organizer HTML. Production adapters
    can invoke the default bounded network readers; tests inject offline readers.
    The result is only a route to remaining rights, access, editorial and
    independent organizer gates, never an event or a publisher patch.
    """
    hold = {
        "schema": SCHEMA, "route": "hold",
        "reason": "invalid_or_unreviewed_inputs",
        "publisher_connected": False, "approval_granted": False,
        "public_writes": 0,
    }
    from ptitesondes_openagenda_v2_direct_evidence import (
        _source_parts, read_direct_v2, read_direct_agenda_v2, review_direct_v2,
    )
    from ptitesondes_qualification_rootcause import probe_uid_in_index
    from ptitesondes_candidate_promotion import covered_by_published_range

    if (not isinstance(lead, dict)
            or lead.get("collector") != "openagenda-v2"
            or not isinstance(lead.get("external_id"), str)
            or not _uid(lead["external_id"])
            or type(today) is not date
            or not isinstance(curated_agenda, dict)
            or not isinstance(published_events, list)
            or len(published_events) > 10000
            or any(not isinstance(ev, dict) for ev in published_events)):
        return hold
    uid = lead["external_id"]
    part = _source_parts(lead.get("source_url"))
    if (part is None or part[1] != uid
            or part[0] != curated_agenda.get("agenda_slug")):
        return dict(hold, reason="source_uid_or_agenda_mismatch")
    event_id = "openagenda-" + uid + "-" + str(lead.get("date_start"))
    if (any(ev.get("id") == event_id for ev in published_events)
            or covered_by_published_range(lead, published_events)):
        return dict(hold, reason="already_published")

    # A transport error, nonunique UID or any nonempty ODS result is a HOLD.
    # Only the existing exact-UID zero-result probe may open the route.
    probe = ods_probe if ods_probe is not None else probe_uid_in_index
    try:
        ods_state = probe(uid)
    except (OSError, ValueError, TypeError, KeyError, TimeoutError):
        ods_state = "probe_unavailable"
    if ods_state != "uid_absent":
        return dict(hold, reason="ods_unavailable_present_or_conflicting")

    read_agenda = agenda_reader if agenda_reader is not None else read_direct_agenda_v2
    read_event = event_reader if event_reader is not None else read_direct_v2
    try:
        agenda_uid = curated_agenda["agenda_uid"]
        agenda = read_agenda(agenda_uid, public_read_key)
        event = read_event(agenda_uid, uid, public_read_key)
    except (OSError, ValueError, TypeError, KeyError, TimeoutError):
        return dict(hold, reason="direct_api_unavailable")
    identity = agenda_identity_for_review(agenda, curated_agenda)
    reviewed = {
        "agenda_uid": curated_agenda.get("agenda_uid"),
        "agenda_slug": curated_agenda.get("agenda_slug"),
        "timezone": curated_agenda.get("timezone"),
    }
    direct = review_direct_v2(lead, event, reviewed, registered_venue, today)
    grouping = group_multi_day(event)
    linked = independently_linked_agenda(
        identity, curated_agenda, institutional_page)
    first_party = None
    if organizer_registry is not None or organizer_page is not None:
        from ptitesondes_openagenda_v2_organizer_bridge import (
            check_independent_session,
        )
        first_party = check_independent_session(
            lead, event, direct, organizer_registry, organizer_page)
    route = ods_fallback_preflight(
        ods_state, direct, identity, grouping,
        historic_uid_exists=False, independently_linked=linked,
        first_party_session_evidence=first_party,
    )
    return dict(route, mode="private_direct_source_followup_only")
