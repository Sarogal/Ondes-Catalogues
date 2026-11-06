"""Sources complémentaires ICS (agrégateurs). Découverte SEULEMENT, publication interdite.

Les données de tiers ne peuvent servir de confirmation officielle.
"""
from __future__ import annotations
import datetime as dt
import hashlib
import re
import urllib.parse

from feeds import unfold_ics, ics_unescape

DATE = re.compile(r"^(\d{4})(\d\d)(\d\d)(?:T\d{6}Z?)?$")
ALLOWED_KEYS = {"UID", "SUMMARY", "DTSTART", "STATUS", "URL", "CATEGORIES", "LOCATION"}


def _events(body):
    """Parser iCal minimal, uniquement les VEVENT, sans descriptions ni HTML."""
    event = None
    for line in unfold_ics(body):
        if line.strip() == "BEGIN:VEVENT":
            event = {}
            continue
        if line.strip() == "END:VEVENT":
            if event:
                yield event
            event = None
            continue
        if event is None or ":" not in line:
            continue
        key, val = line.split(":", 1)
        key = key.split(";", 1)[0].upper().strip()
        if key in ALLOWED_KEYS and key not in event:
            event[key] = ics_unescape(val.strip())


def _date(value):
    match = DATE.fullmatch(value or "")
    if not match:
        return None
    try:
        return dt.date(*[int(x) for x in match.groups()[:3]]).isoformat()
    except ValueError:
        return None


def _safe_event_url(value, feed_url):
    if not value:
        return None
    event = urllib.parse.urlsplit(value)
    origin = urllib.parse.urlsplit(feed_url)
    if (event.scheme == "https" and event.hostname and origin.hostname
        and event.hostname.lower() == origin.hostname.lower()
        and event.path.startswith("/evenement/")):
        return value.split("#", 1)[0]
    return None


def partner_ics_candidates(body, source, today):
    """Dater uniquement selon DTSTART complet; préserver la nature tierce."""
    if len(body) > 2_000_000 or "BEGIN:VCALENDAR" not in body:
        raise ValueError("Flux iCal invalide ou trop long")
    result = []
    for raw in _events(body):
        day = _date(raw.get("DTSTART"))
        name = raw.get("SUMMARY", "").strip()
        if not day or day < today or not name or len(name) > 220:
            continue
        status = raw.get("STATUS", "").casefold()
        cancelled = status in ("cancelled", "canceled") or bool(
            re.search(r"\b(annul[eé]|report[eé]|cancelled|postponed)\b", name, re.I)
        )
        event_url = _safe_event_url(raw.get("URL"), source["url"])
        stable = hashlib.sha256(
            (source["id"] + "|" + day + "|" + name.casefold()).encode()
        ).hexdigest()[:18]
        categories = [x.strip() for x in raw.get("CATEGORIES", "").split(",") if x.strip()]
        candidate = {
            "candidateId": "partner-ics:" + stable,
            "source": "third_party_calendar_lead",
            "sourcePage": source["url"],
            "sourceUrl": event_url or source["url"],
            "sourceLabel": source["sourceLabel"],
            "confirmationRequiredFrom": source["officialVenuePage"],
            "date": day,
            "name": name,
            "leadArtist": name,
            "venue": source["venueName"],
            "city": source["city"],
            "department": source["department"],
            "classification": categories,
            "genreToConfirm": True,
            "reviewRequired": True,
            "publicationAllowed": False,
            "thirdPartyOnly": True,
            "cancellationNotice": cancelled,
            "sourceConfidence": "Calendrier agrégateur public; date et affiche à recouper avec organisateur",
        }
        result.append(candidate)
        if len(result) >= int(source.get("maxEntriesPerRun", 50)):
            break
    # Ne jamais fusionner aveuglément deux séances d'un jour : simple alerte.
    day_counts = {}
    for item in result:
        day_counts[item["date"]] = day_counts.get(item["date"], 0) + 1
    for item in result:
        item["otherListingsSameDay"] = day_counts[item["date"]] > 1
    return result
