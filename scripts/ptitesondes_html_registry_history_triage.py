"""Read-only join of an extracted child session with separately reviewed registries.

This is intentionally not a verifier of the current organizer, licensing,
session, access rules, or a fresh geocoder result. No GPS, source registration,
approval, or publishable event is returned. Calling code only emits counts.

The location registries are maintained separately from source discovery. Never
build this context using a candidate's coordinates, URLs, or claimed aliases.
"""
from datetime import date
import math
import re
from urllib.parse import urlsplit

from proof import norm, meters

CLOCK = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d\Z")
VENUE_KEYS = frozenset({"city", "aliases", "lat", "lng", "official", "geo_source"})
CONTEXT_KEYS = frozenset({"legacy_venues", "public_places", "historical_catalogue"})
VENUE_STATUSES = frozenset({"matched", "missing", "ambiguous", "untrusted", "not_checked"})
HISTORY_STATUSES = frozenset({"clear", "duplicate", "ambiguous", "not_checked"})


def _safe_host(raw):
    if not isinstance(raw, str):
        return None
    try:
        p = urlsplit(raw)
        if (p.scheme != "https" or not p.hostname or p.username or p.password
                or p.port not in (None, 443) or p.fragment):
            return None
        return p.hostname.casefold()
    except ValueError:
        return None


def _valid_venue(row):
    if not isinstance(row, dict) or not VENUE_KEYS <= set(row):
        return False
    city, aliases = row["city"], row["aliases"]
    if (not isinstance(city, str) or not city.strip()
            or not isinstance(aliases, (list, tuple)) or not aliases
            or any(not isinstance(x, str) or not x.strip() for x in aliases)
            or any(len(x) > 160 for x in aliases)):
        return False
    a, b = _safe_host(row["official"]), _safe_host(row["geo_source"])
    if not a or not b or a == b:
        return False
    lat, lng = row["lat"], row["lng"]
    return (type(lat) in (float, int) and type(lng) in (float, int)
            and math.isfinite(lat) and math.isfinite(lng)
            and -90 <= lat <= 90 and -180 <= lng <= 180
            and (lat, lng) != (0, 0))


def _matched_venue(lead, legacy, public):
    city, venue = lead.get("city"), lead.get("venue")
    if not isinstance(city, str) or not isinstance(venue, str):
        return "not_checked"
    matches, suspicious = [], False
    for row in [*legacy, *public]:
        if not isinstance(row, dict):
            continue
        aliases = row.get("aliases")
        if (not isinstance(row.get("city"), str)
                or not isinstance(aliases, (list, tuple))):
            continue
        if norm(row["city"]) != norm(city):
            continue
        if norm(venue) not in {norm(v) for v in aliases if isinstance(v, str)}:
            continue
        if not _valid_venue(row):
            suspicious = True
            continue
        matches.append(row)
    if suspicious:
        return "untrusted"
    if len(matches) > 1:
        # Two records can denote the same building, but conflicting source
        # claims are not resolved by picking a convenient coordinate.
        return "ambiguous"
    return "matched" if matches else "missing"


def _historical_collision(lead, events):
    if not isinstance(events, list):
        return "not_checked"
    title, city, venue, day, clock, source = (
        lead.get("title"), lead.get("city"), lead.get("venue"),
        lead.get("date_start"), lead.get("start_local"), lead.get("source_url"),
    )
    if not all(isinstance(x, str) and x for x in
               (title, city, venue, day, clock, source)):
        return "not_checked"
    if not CLOCK.fullmatch(clock):
        return "not_checked"
    ambiguous = False
    for old in events:
        if not isinstance(old, dict):
            return "not_checked"
        start, end = old.get("date_start"), old.get("date_end", old.get("date_start"))
        if not isinstance(start, str) or not isinstance(end, str):
            continue
        if not start <= day <= end:
            continue
        same = (
            norm(old.get("title", "")) == norm(title)
            and norm(old.get("city", "")) == norm(city)
            and norm(old.get("venue", "")) == norm(venue)
        )
        if same:
            old_clock = old.get("time")
            if isinstance(old_clock, str) and CLOCK.fullmatch(old_clock):
                if old_clock == clock:
                    return "duplicate"
                # A different time may be a distinct session, but it must
                # be independently paired with the dated source block.
                ambiguous = True
            else:
                ambiguous = True
        elif old.get("source_url") == source:
            # Shared programme URL and date: possible identity collision.
            ambiguous = True
    return "ambiguous" if ambiguous else "clear"


def triage_independent_context(lead, context):
    """Fixed statuses only, no event/venue/source payload or publication."""
    result = {
        "venue_status": "not_checked",
        "history_status": "not_checked",
        "venue_registry_is_previously_reviewed_not_refetched": True,
        "individual_session_independently_attested": False,
        "organizer_independently_attested": False,
        "rights_reviewed": False,
        "publication_ready": False,
        "approval_granted": False,
        "public_writes": 0,
    }
    if not isinstance(lead, dict) or not isinstance(context, dict):
        return result
    if set(context) != CONTEXT_KEYS:
        return result
    legacy = context["legacy_venues"]
    public = context["public_places"]
    catalogue = context["historical_catalogue"]
    if (not isinstance(legacy, list) or len(legacy) > 500
            or not isinstance(public, list) or len(public) > 500
            or not isinstance(catalogue, dict)
            or not isinstance(catalogue.get("events"), list)
            or len(catalogue["events"]) > 10_000
            or not isinstance(catalogue.get("updated_at"), str)):
        return result
    result["venue_status"] = _matched_venue(lead, legacy, public)
    result["history_status"] = _historical_collision(lead, catalogue["events"])
    return result
