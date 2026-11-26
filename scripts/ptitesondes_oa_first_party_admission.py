"""OpenAgenda-first factual admission. No municipality or second website required.

Only live public API v2 records can produce a candidate. The intake dossier
cannot supply approval, coordinates, category, timings or attribution.
"""
from datetime import date, datetime, timedelta, timezone
import re

from merge_policy import valid, PUBLISHABLE_CHILD_ARTS
from official_organizer_proof import canonical_event_title
from proof import norm
from ptitesondes_primary_editorial import primary_out_of_scope, audience_text
from ptitesondes_oa_evergreen_on_demand import (ambiguous_on_demand_studio_series,
                                               ambiguous_itinerant_availability)
from ptitesondes_candidate_promotion import category_for
from ptitesondes_family_activity_classification import propose_family_activity
from ptitesondes_openagenda_national_event_research import _french_text
from ptitesondes_openagenda_reuse_rights import review_event_rights
from ptitesondes_openagenda_v2_direct_evidence import (
    _sessions, _time, _calendar_review, _norm, CHILD, EXCLUSIVELY_ADULT, FR_TZ,
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
    "oa_direct_city_only_location",
    "oa_direct_evergreen_on_demand_review",
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
    "oa_direct_session_already_started",
    "oa_direct_invalid_publisher_clock",
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


# Minimum ages are audience evidence only when stated as a participation
# condition, a standalone age label, or explicitly attached to the public.
# A musician starting an instrument at age five is not an audience claim.
AGE_MINIMUM_LABEL = re.compile(
    r"^(?:(?:tout public|public|age|ages|accessible|spectacle|concert|atelier)"
    r"(?: a tous)? )?(?:des|a partir de) (\d{1,2}) ans(?: et plus)?$"
)
AGE_MINIMUM_CONTEXT = re.compile(
    r"\b(?:public|accessible|ouvert(?:e)?|adapte(?:e)?|"
    r"recommande(?:e)?|conseille(?:e)?|participation|inscription)"
    r"(?: a tous)? (?:des|a partir de) (\d{1,2}) ans\b"
)
AGE_NEGATIVE = re.compile(
    r"\b(?:non accessible|pas accessible|interdit|deconseille|"
    r"reserve aux adultes|adultes uniquement|sans enfants)\b"
)


def explicit_minimum_child_audience(description, conditions):
    # Parse explicit source fields separately, not concatenated artist bios.
    for raw in (conditions, description):
        if not isinstance(raw, str):
            continue
        text = _norm(raw)
        if AGE_NEGATIVE.search(text) or EXCLUSIVELY_ADULT.search(text):
            continue
        for match in AGE_MINIMUM_CONTEXT.finditer(text):
            if 1 <= int(match[1]) <= 17:
                return True
        # Split only on strong sentence/line boundaries, not commas.
        for clause in re.split(r"[.!?;\n\r]+", raw):
            match = AGE_MINIMUM_LABEL.fullmatch(_norm(clause))
            if match and 1 <= int(match[1]) <= 17:
                return True
    return False


def publishable_minimum_age(description, conditions, age):
    """Return only an unambiguous first-party minimum, never a guessed range."""
    minima = set()
    for raw in (conditions, description):
        if not isinstance(raw, str):
            continue
        text = _norm(raw)
        if AGE_NEGATIVE.search(text) or EXCLUSIVELY_ADULT.search(text):
            return None
        minima.update(int(m[1]) for m in AGE_MINIMUM_CONTEXT.finditer(text))
        for clause in re.split(r"[.!?;\n\r]+", raw):
            match = AGE_MINIMUM_LABEL.fullmatch(_norm(clause))
            if match:
                minima.add(int(match[1]))
    if len(minima) != 1:
        return None
    minimum = next(iter(minima))
    if not 1 <= minimum <= 17:
        return None
    if isinstance(age, dict):
        if age.get("min") is not None and age["min"] != minimum:
            return None
        if age.get("max") is not None and age["max"] < minimum:
            return None
    return minimum


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


# A generic concert bio ("l'enfant du rock") or convivial restaurant copy
# ("un moment entre amis ou en famille") is not evidence of a youth programme.
# Accept targeted child/family wording or explicit ages, regardless of genre,
# artist, venue, source or whether accompanying adults may attend.
CONCERT_AUDIENCE = re.compile(
    r"\b(?:jeune public|tout petits?|bebes?|petits et grands|"
    r"(?:pour|destine(?:e|s|es)? (?:a|aux)|adapte(?:e|s|es)? (?:a|aux)) "
    r"(?:les |des |l |la |toute la |toutes les )?"
    r"(?:enfants?|familles?|adolescents?|ados?|plus jeunes)|"
    r"concert(?:s)? (?:familial|familiaux|en famille|jeunesse|enfants?)|"
    r"concert(?:s)? (?:pour|avec) (?:les |des )?enfants?|"
    r"parents enfants|enfants? (?:accompagnes?|bienvenus?))\b"
)


def explicit_programme_category(title, description):
    """Recognise a first-party advertised format, after audience validation.

    A short artistic title can omit the format and the description can omit
    the audience when the official record has a structured child age. Do not
    turn incidental activities in an exhibition or other main programme into
    a separate children's performance.
    """
    name, body = _norm(title), _norm(description)
    if primary_out_of_scope(title, description) or re.search(
            r"\b(?:exposition|vernissage|visite guidee|vide grenier)\b", name):
        return None
    for pattern, category, label in (
        (r"^(?:un |une )?eveil musical\b", "eveil-musical", "Éveil musical"),
        (r"^(?:(?:un |une )?seance d |(?:un |une )?atelier d )?eveil corporel en musique\b",
         "eveil-musical", "Éveil musical"),
        (r"^(?:un |une )?eveil et decouverte musicale\b",
         "eveil-musical", "Éveil musical"),
        (r"^lectures? d albums (?:et )?comptines?\b",
         "lecture-jeunesse", "Lecture jeunesse"),
        (r"^(?:un |une )?spectacle musical\b", "spectacle-musical", "Spectacle musical"),
        (r"^(?:lectures?|histoires?) (?:et )?comptines?\b",
         "lecture-jeunesse", "Lecture jeunesse"),
    ):
        if re.search(pattern, body) or (category == "eveil-musical"
                                        and re.search(pattern, name)):
            return category, label
    # A youth performance can advertise its theatrical disciplines rather
    # than the literal words "spectacle pour enfants". Require an explicit
    # performance-format opening or an advertised musical adventure addressed
    # directly to the audience, never an incidental mention of a puppet.
    if (re.search(r"^(?:marionnettes?|mime|magie)(?: (?:et )?(?:marionnettes?|mime|magie)){1,3}\b", body)
            and re.search(r"\b(?:marionnettes?|mime)\b", body)
            and re.search(r"\b(?:jeune public|spectacles?|comedien(?:ne)?s?|compagnie|cie|interprete)\b", name + " " + body)):
        return "spectacle-jeunesse", "Spectacle jeune public"
    if re.search(r"\bpetits et grands (?:prenez part|participez|embarquez|partez) "
                 r"(?:a|dans|pour) (?:l |une )aventure musicale\b", body):
        return "spectacle-musical", "Spectacle musical"
    # An explicitly advertised participatory musical experience combines
    # its central music theme, vocal practice and sound/instrument exploration.
    # All three signals are required; merely mentioning music is insufficient.
    if (re.search(r"\b(?:moment|atelier|seance|experience|temps) autour de la musique\b", body)
            and re.search(r"\b(?:chanter|chantant|chantons|jouer avec la voix|jouant avec la voix)\b", body)
            and re.search(r"\b(?:instruments?|objets sonores)\b", body)):
        return "eveil-musical", "Éveil musical"
    return None


def admit_live_openagenda(lead, day_text, agenda, event, baseline, published,
                          today, *, as_of_utc=None):
    """Return (candidate, stable_reason). No network or catalogue writes."""
    def fail(reason):
        return None, reason

    if not isinstance(lead, dict) or type(today) is not date:
        return fail("oa_direct_invalid_lead")
    # The real Publisher supplies one UTC instant for the entire review batch;
    # tests can inject a fixed instant without trusting timestamps in dossiers.
    if as_of_utc is None:
        as_of_utc = datetime.now(timezone.utc)
    if (not isinstance(as_of_utc, datetime) or as_of_utc.tzinfo is None
            or as_of_utc.utcoffset() is None):
        return fail("oa_direct_invalid_publisher_clock")
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
    # A city-name-only OA location cannot prove a venue pin. A named event
    # place (including an unnumbered public square) remains admissible; an
    # entire municipality cannot be published as geo_precision="venue".
    # Requeue these events for independent, exact named-place resolution.
    if norm(city) == norm(venue):
        return fail("oa_direct_city_only_location")
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
    # The existing validator has checked every exact OA offset against its
    # IANA timezone. The calendar *date* alone is not enough: a 10:00
    # performance must not first appear on the family map at 21:00.
    # Keep only future starts when a UID has multiple sessions that day.
    starts = [_time(slot["begin"], event["timezone"]) for slot in actual]
    if any(start is None for start in starts):
        return fail("oa_direct_invalid_times")
    times = sorted({start.strftime("%H:%M") for start in starts
                    if start > as_of_utc})
    if not times:
        return fail("oa_direct_session_already_started")
    # The standard Publisher and the already-published reconciliation MUST
    # apply the same source-based hold: otherwise ordinary cloud sync can
    # flood the map with hundreds of daily bookable studio availabilities
    # that the reconciliation correctly refused to extend. No hard cap on
    # sessions: all three first-party textual signals are required.
    source_days = {
        x["begin"][:10]: True for x in event["timings"]
        if isinstance(x, dict) and isinstance(x.get("begin"), str)
    }
    if ambiguous_on_demand_studio_series(event, source_days):
        return fail("oa_direct_evergreen_on_demand_review")
    if ambiguous_itinerant_availability(event, day):
        return fail("oa_direct_itinerant_availability_review")
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
    audience = audience_text(title, source_text)
    if EXCLUSIVELY_ADULT.search(audience) or NOT_PUBLIC_ACCESS.search(audience):
        return fail("oa_direct_restricted_access")
    child_age = isinstance(age, dict) and type(age.get("max")) is int and age["max"] <= 17
    minimum_child_audience = explicit_minimum_child_audience(description, conditions)
    if (not CHILD.search(audience) and not child_age
            and not minimum_child_audience
            and not explicit_child_age_text(source_text)
            and not CONCERT_AUDIENCE.search(audience)):
        return fail("oa_direct_child_audience_missing")
    category = category_for(title, source_text)
    if (category is None and re.search(r"\bconcerts?\b", _norm(title))
            and CONCERT_AUDIENCE.search(audience)):
        category = ("concert", "Concert")
    if category is None:
        family = propose_family_activity(title, source_text)
        if family["category_proposal"] in PUBLISHABLE_CHILD_ARTS:
            category = (family["category_proposal"], family["category_label_proposal"])
    if category is None:
        category = explicit_programme_category(title, description)
    if category is None:
        return fail("oa_direct_out_of_editorial_scope")
    if (category[0] == "concert" and not child_age
            and not minimum_child_audience
            and not explicit_child_age_text(source_text)
            and not CONCERT_AUDIENCE.search(audience)):
        return fail("oa_direct_child_audience_missing")
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
    minimum = publishable_minimum_age(description, conditions, age)
    if minimum is not None and "age_min" in fields:
        candidate["age_min"] = minimum
        if "age_label" in fields:
            candidate["age_label"] = f"Dès {minimum} ans"
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
