"""OpenAgenda-first factual admission. No municipality or second website required.

Only live public API v2 records can produce a candidate. The intake dossier
cannot supply approval, coordinates, category, timings or attribution.
"""
from datetime import date, timedelta
import re

from merge_policy import valid, PUBLISHABLE_CHILD_ARTS
from official_organizer_proof import canonical_event_title
from proof import norm
from ptitesondes_primary_editorial import primary_out_of_scope
from ptitesondes_candidate_promotion import category_for
from ptitesondes_family_activity_classification import propose_family_activity
from ptitesondes_openagenda_national_event_research import _french_text
from ptitesondes_openagenda_reuse_rights import review_event_rights
from ptitesondes_openagenda_v2_direct_evidence import (
    _sessions, _calendar_review, _norm, CHILD, EXCLUSIVELY_ADULT, FR_TZ,
    ADDITIONAL_TERRITORY_ZONES, OVERSEAS_ADMIN,
)
from ptitesondes_open_world_release_rehearsal import _sessions_for_day, NOT_PUBLIC_ACCESS
from ptitesondes_shared_venue_location_evidence import _coordinates

# Safe status codes only: do not expose private names, event URLs or UIDs.
PUBLIC_OA_DIRECT_REASONS = frozenset({
    "oa_direct_admin_boundaries_missing",
    "oa_direct_already_published",
    "oa_direct_child_audience_missing",
    "oa_direct_invalid_age",
    "oa_direct_invalid_coordinates",
    "oa_direct_invalid_date",
    "oa_direct_invalid_lead",
    "oa_direct_invalid_published_date",
    "oa_direct_invalid_slug",
    "oa_direct_invalid_times",
    "oa_direct_invalid_timings",
    "oa_direct_location_missing",
    "oa_direct_missing_live_source",
    "oa_direct_no_exact_session",
    "oa_direct_not_public_or_identity_changed",
    "oa_direct_out_of_editorial_scope",
    "oa_direct_primary_activity_outside_scope",
    "oa_direct_out_of_window",
    "oa_direct_outside_france",
    "oa_direct_public_contract_rejected",
    "oa_direct_restricted_access",
    "oa_direct_reuse_rights_missing",
    "oa_direct_semantic_duplicate",
    "oa_direct_session_changed",
    "oa_direct_territory_timezone_mismatch",
    "oa_direct_title_changed",
    "oa_direct_url_uid_or_slug_mismatch",
    "oa_direct_venue_changed",
})


# Explicit ages in first-party descriptions and participation conditions are
# valid audience evidence even if no structured OpenAgenda age.max is present.
# E.g. "pour les plus jeunes jusqu'à 11 ans" or "de 3 à 12 ans".
# These patterns make no assumption about the city, agenda, venue or organiser.
AGE_UPPER_TEXT = re.compile(
    r"\b(?:jusqu a|moins de)\s+(\d{1,2})\s+ans\b"
)
AGE_RANGE_TEXT = re.compile(
    r"\b(?:de|entre|pour les)\s+(\d{1,2})\s+(?:a|et)\s+(\d{1,2})\s+ans\b"
)


def explicit_child_age_text(value):
    if not isinstance(value, str):
        return False
    text = _norm(value)
    for match in AGE_UPPER_TEXT.finditer(text):
        if int(match[1]) <= 17:
            return True
    for match in AGE_RANGE_TEXT.finditer(text):
        low, high = int(match[1]), int(match[2])
        if low <= high <= 17:
            return True
    return False


def admit_live_openagenda(lead, day_text, agenda, event, baseline, published, today):
    """Return (candidate, stable_reason). No network or catalogue writes."""
    def fail(reason):
        return None, reason

    if not isinstance(lead, dict) or type(today) is not date:
        return fail("oa_direct_invalid_lead")
    try:
        day = date.fromisoformat(day_text)
    except (TypeError, ValueError):
        return fail("oa_direct_invalid_date")
    if not today <= day <= today + timedelta(days=184):
        return fail("oa_direct_out_of_window")
    if not isinstance(agenda, dict) or not isinstance(event, dict):
        return fail("oa_direct_missing_live_source")
    reviewed = {
        "agenda_uid": lead.get("agenda_uid"),
        "agenda_slug": lead.get("agenda_slug"),
        "timezone": event.get("timezone"),
    }
    # OA v2 may return a status integer or a structured {id, label} value.
    # 1 = scheduled, 2 = rescheduled with new published timings.
    # 3-6 are moved-online, postponed, sold-out or cancelled: not admissible.
    status = event.get("status")
    if type(status) is dict:
        status = status.get("id")
    if (not _calendar_review(reviewed)
            or str(agenda.get("uid")) != str(lead["agenda_uid"])
            or agenda.get("slug") != lead["agenda_slug"]
            or type(event.get("uid")) is not int
            or event["uid"] != lead.get("event_uid")
            or event.get("state") != 2 or type(status) is not int
            or status not in (1, 2) or event.get("removed") is True
            or event.get("attendanceMode") not in (1, 3)):
        return fail("oa_direct_not_public_or_identity_changed")
    loc = event.get("location")
    if not isinstance(loc, dict):
        return fail("oa_direct_location_missing")
    country = loc.get("countryCode")
    if (country != "FR" and country not in ADDITIONAL_TERRITORY_ZONES
            and country not in OVERSEAS_ADMIN):
        return fail("oa_direct_outside_france")
    if (country in ADDITIONAL_TERRITORY_ZONES
            and event["timezone"] not in ADDITIONAL_TERRITORY_ZONES[country]):
        return fail("oa_direct_territory_timezone_mismatch")
    point = _coordinates((loc.get("latitude"), loc.get("longitude")))
    if point is None or point == (0, 0):
        return fail("oa_direct_invalid_coordinates")
    city, venue = loc.get("adminLevel4"), loc.get("name")
    if (not isinstance(city, str) or not city.strip()
            or not isinstance(venue, str) or not venue.strip()
            or norm(city) != norm(lead.get("city_unverified"))
            or norm(venue) != norm(lead.get("venue_unverified"))):
        return fail("oa_direct_venue_changed")
    title = _french_text(event, "title")
    if not title or norm(title) != norm(lead.get("title")):
        return fail("oa_direct_title_changed")
    selected = _sessions_for_day(lead, day)
    if not selected:
        return fail("oa_direct_no_exact_session")
    if not isinstance(event.get("timings"), list):
        return fail("oa_direct_invalid_timings")
    actual = [x for x in event["timings"] if (
        isinstance(x, dict) and isinstance(x.get("begin"), str)
        and x["begin"][:10] == day_text)]
    if (len(actual) != len(selected)
            or {(x.get("begin"), x.get("end")) for x in actual}
               != {(x["begin"], x["end"]) for x in selected}):
        return fail("oa_direct_session_changed")
    times, days, error = _sessions(event, event["timezone"], day, today)
    if error or not times:
        return fail("oa_direct_invalid_times")
    # A recurring UID may have several days: each observed exact day is
    # separately eligible, and duplicate day IDs remain guarded by Publisher.
    age = event.get("age")
    if age is not None and (not isinstance(age, dict)
            or any(type(v) is not int or not 0 <= v <= 120
                   for v in (age.get("min"), age.get("max")) if v is not None)
            or (type(age.get("min")) is int and type(age.get("max")) is int
                and age["min"] > age["max"])):
        return fail("oa_direct_invalid_age")
    description = _french_text(event, "description") + " " + _french_text(event, "longDescription")
    # OA's official registration/attendance conditions can contain the only
    # explicit child-age statement (e.g. "pour les enfants de 0 à 6 ans").
    # Read them from the UID-bound live record, never from a collector hint.
    # The same field can also DENY admission for adults-only or private
    # sessions. No inferred age or free/registration claim is published.
    conditions = _french_text(event, "conditions")
    source_text = description + " " + conditions
    # The live first-party title describes the main activity. A minor
    # lecture or concert within a school programme/forum is not enough.
    if primary_out_of_scope(title, source_text):
        return fail("oa_direct_primary_activity_outside_scope")
    audience = _norm(title + " " + source_text)
    if EXCLUSIVELY_ADULT.search(audience) or NOT_PUBLIC_ACCESS.search(audience):
        return fail("oa_direct_restricted_access")
    child_age = isinstance(age, dict) and type(age.get("max")) is int and age["max"] <= 17
    if not CHILD.search(audience) and not child_age and not explicit_child_age_text(source_text):
        return fail("oa_direct_child_audience_missing")
    category = category_for(title, source_text)
    if category is None:
        family = propose_family_activity(title, source_text)
        if family["category_proposal"] in PUBLISHABLE_CHILD_ARTS:
            category = (family["category_proposal"], family["category_label_proposal"])
    if category is None:
        return fail("oa_direct_out_of_editorial_scope")
    rights = review_event_rights(event, today)
    if not rights["licensed_factual_reuse_confirmed"]:
        return fail("oa_direct_reuse_rights_missing")
    department, region = loc.get("adminLevel2"), loc.get("adminLevel1")
    if not all(isinstance(x, str) and x.strip() for x in (department, region)):
        return fail("oa_direct_admin_boundaries_missing")
    slug = event.get("slug")
    if not isinstance(slug, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,139}", slug):
        return fail("oa_direct_invalid_slug")
    source_url = ("https://openagenda.com/" + lead["agenda_slug"]
                  + "/events/" + str(event["uid"]) + "_" + slug)
    candidate = {
        "id": "openagenda-" + str(event["uid"]) + "-" + day_text,
        "title": title, "category": category[0], "category_label": category[1],
        "date_start": day_text, "date_end": day_text,
        "time": " ; ".join(times),
        "city": city, "department": department, "region": region, "venue": venue,
        "source_url": source_url, "source_label": rights["attribution_display"],
        "verified_at": today.isoformat(), "geo_verified_at": today.isoformat(),
        "geo_precision": "venue", "lat": point[0], "lng": point[1],
    }
    fields = set().union(*(set(x) for x in baseline["events"]))
    categories = {x["category"] for x in baseline["events"]} | PUBLISHABLE_CHILD_ARTS
    if not valid(candidate, categories, fields, today)[0]:
        return fail("oa_direct_public_contract_rejected")
    signature = (canonical_event_title(candidate), norm(city), norm(venue))
    for existing in published["events"]:
        if existing.get("id") == candidate["id"]:
            return fail("oa_direct_already_published")
        if (canonical_event_title(existing), norm(existing.get("city")),
                norm(existing.get("venue"))) != signature:
            continue
        try:
            if date.fromisoformat(existing["date_start"]) <= day <= date.fromisoformat(existing["date_end"]):
                return fail("oa_direct_semantic_duplicate")
        except (ValueError, KeyError, TypeError):
            return fail("oa_direct_invalid_published_date")
    return candidate, "oa_direct_live_source_accepted"
