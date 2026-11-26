"""Generic guard for evergreen commercial booking calendars in children's arts.

An OpenAgenda first-party record is enough to authenticate an event, but
availability slots for a bespoke commercial service are not necessarily
genuinely scheduled youth performances. Hold ONLY when a long unbroken daily
calendar coincides with studio-service, reservation/on-demand, and
corporate/adult-customer cues. Do not limit ordinary multi-session shows.
"""
from datetime import date, datetime, timedelta
import re

from proof import norm


def _official_text(value):
    if isinstance(value, dict):
        value = value.get("fr")
    return value if isinstance(value, str) else ""


def ambiguous_on_demand_studio_series(source, sessions):
    """Hold long bookable studio availability, regardless of organizer name.

    The number of sessions alone does not block publication. A 50-show
    children's performance or recurring youth workshop stays eligible.
    """
    if not isinstance(source, dict) or not isinstance(sessions, dict):
        return False
    try:
        days = sorted(date.fromisoformat(day) for day in sessions)
    except (TypeError, ValueError):
        return False
    consecutive = longest = 0
    last = None
    for day in days:
        consecutive = consecutive + 1 if last and day - last == timedelta(days=1) else 1
        longest = max(longest, consecutive)
        last = day
    if longest < 14:
        return False
    content = norm(" ".join(_official_text(source.get(key)) for key in (
        "title", "description", "longDescription", "conditions")))
    studio = any(part in content for part in (
        "studio enregistrement", "enregistrement en studio",
        "studio professionnel", "louer un studio", "reservation studio"))
    on_demand = any(part in content for part in (
        "contactez nous", "sur reservation", "reservez", "reservation",
        "payant", "prendre rendez vous"))
    corporate = any(part in content for part in (
        "team building", "entreprises", "particuliers",
        "professionnels", "public adulte", "adultes"))
    return studio and on_demand and corporate


def ambiguous_itinerant_availability(source, day):
    """A touring offer with full-day windows is not an exact local showtime.

    Require a source-confirmed itinerant programme AND multiple hosting
    locations or explicitly advertised opening hours AND long availability
    intervals on the requested day. Neither a long session, a touring artist,
    nor the number of dates is a veto on its own. Short exact sessions on
    other days remain eligible; the source can provide a separate dated
    event for each confirmed host. A hold is not a permanent blacklist.
    """
    if not isinstance(source, dict) or type(day) is not date:
        return False
    content = norm(" ".join(_official_text(source.get(key)) for key in (
        "title", "description", "longDescription", "conditions")))
    itinerary = re.search(r"\b(?:dispositif|spectacle|installation|exposition|programme|atelier)"
                          r" itinerant(?:e)?\b", content)
    unresolved_hosts = re.search(
        r"\b(?:dans (?:differentes|plusieurs|diverses) (?:structures|lieux|salles|monuments|communes|bibliotheques|mediatheques)"
        r"|itinerant(?:e)? dans les monuments|horaires d ouverture (?:du|des|de la|de l) (?:monument|monuments|musee|musees|site|sites))\b",
        content)
    if not itinerary or not unresolved_hosts:
        return False
    slots = source.get("timings")
    if not isinstance(slots, list):
        return False
    durations = []
    for slot in slots:
        if not isinstance(slot, dict) or not isinstance(slot.get("begin"), str):
            return False
        if slot["begin"][:10] != day.isoformat():
            continue
        try:
            begin = datetime.fromisoformat(slot["begin"])
            end = datetime.fromisoformat(slot["end"])
            if begin.utcoffset() is None or end.utcoffset() is None or end <= begin:
                return False
            durations.append(end - begin)
        except (KeyError, TypeError, ValueError, OverflowError):
            return False
    # A real festival can be long. The explicit multi-host/opening-hour
    # evidence above is essential; no arbitrary series-length requirement.
    return bool(durations and all(d >= timedelta(hours=5) for d in durations))
