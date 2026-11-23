"""Generic guard for evergreen commercial booking calendars in children's arts.

An OpenAgenda first-party record is enough to authenticate an event, but
availability slots for a bespoke commercial service are not necessarily
genuinely scheduled youth performances. Hold ONLY when a long unbroken daily
calendar coincides with studio-service, reservation/on-demand, and
corporate/adult-customer cues. Do not limit ordinary multi-session shows.
"""
from datetime import date, timedelta

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
