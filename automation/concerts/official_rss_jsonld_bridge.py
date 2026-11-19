"""Reusable first-party RSS -> individually dated MusicEvent discovery bridge.

RSS publishing timestamps are NEVER concert dates. Only a fresh first-party
event page with exactly one structured MusicEvent can contribute a dated lead.
Discovery remains quarantined: no signature, automatic approval or publisher
invocation occurs here. Designed for different official venues, not one concert.
"""
from __future__ import annotations

import datetime as dt
import re
from urllib.parse import urlsplit

import triage

_UNANNOUNCED = frozenset({
    "guest", "guests", "special guest", "surprise", "tba", "to be announced",
    "premiere partie", "première partie", "a confirmer", "à confirmer",
    "various artists", "invite surprise", "invité surprise",
    "artiste surprise", "guest surprise", "première partie surprise",
})
_BLOCKED_PATH = re.compile(
    r"(?i)(?:^|/)(?:feed|comments?|category|tag|wp-json)(?:/|$)|"
    r"[.](?:pdf|ics|xml|json|jpeg|jpg|png|webp)$"
)


def official_event_url(link, source_url):
    """Exact host, HTTPS and non-generic path, without credentials or tracking."""
    if not isinstance(link, str) or not isinstance(source_url, str):
        return False
    try:
        u, parent = urlsplit(link), urlsplit(source_url)
        if (u.scheme != "https" or parent.scheme != "https"
                or not u.hostname or not parent.hostname
                or u.username or u.password or u.port is not None
                or u.query or u.fragment
                or u.hostname.lower().removeprefix("www.")
                != parent.hostname.lower().removeprefix("www.")):
            return False
        path = u.path.strip("/")
        if (not path or len(path) < 5
                or path.lower() in {"agenda", "programmation", "events",
                                    "concerts", "actualites", "news"}
                or _BLOCKED_PATH.search(u.path)):
            return False
        return True
    except ValueError:
        return False


def select_leads(leads, source_url, day, slot, limit=2):
    """Bounded deterministic rotation; never re-read only the newest RSS leads."""
    if not isinstance(day, dt.date) or slot not in (0, 1, 2) or limit < 0:
        raise ValueError("Invalid RSS rotation")
    valid, seen = [], set()
    for item in leads:
        link = item.get("sourceUrl") if isinstance(item, dict) else None
        if (official_event_url(link, source_url) and link not in seen):
            valid.append(item)
            seen.add(link)
    if not valid or not limit:
        return []
    # A non-overlapping two-lead window for each of the three daily slots.
    # Advancing by one per day would re-read almost the same 2 links and
    # starve older announcements, even when three runs/day succeed.
    offset = ((day.toordinal() * 3 + slot) * limit) % len(valid)
    return [valid[(offset + n) % len(valid)]
            for n in range(min(limit, len(valid)))]


def select_venue_probes(queue, day, slot, limit=12, per_venue=2):
    """Fair bounded selection across ALL available first-party venue RSS feeds.

    Each queue item is (trusted source, official base URL, RSS leads, diagnostics).
    First rotate over venues, then probe at most two individual pages per venue.
    This prevents the first six sources in a fixed list from monopolizing the
    whole cycle. Neither untrusted RSS URLs nor candidate data choose venues.
    """
    if (not isinstance(day, dt.date) or slot not in (0, 1, 2)
            or not isinstance(limit, int) or not 0 <= limit <= 12
            or not isinstance(per_venue, int) or not 1 <= per_venue <= 2):
        raise ValueError("Invalid RSS fair-probe budget")
    groups = []
    for source, base, leads, diagnostics in queue:
        candidates = select_leads(leads, base, day, slot, limit=per_venue)
        if candidates:
            groups.append((source, base, diagnostics, candidates))
    if not groups or limit == 0:
        return []
    turn = day.toordinal() * 3 + slot
    start = (turn * limit) % len(groups)
    ordered = groups[start:] + groups[:start]
    selected = []
    # Round-robin: first sample as many distinct venues as possible before
    # spending second probes on any one venue.
    for position in range(per_venue):
        for source, base, diagnostics, candidates in ordered:
            if len(selected) >= limit:
                return selected
            if position < len(candidates):
                selected.append((source, base, diagnostics, candidates[position]))
    return selected


def _event_types(value):
    if isinstance(value, str):
        return {value.rsplit("/", 1)[-1]}
    if isinstance(value, list):
        return {x.rsplit("/", 1)[-1] for x in value if isinstance(x, str)}
    return set()


def official_named_bill(value):
    """Return named performers and optional trailing non-nominative guest.

    An officially announced placeholder is NOT a performer. It is acceptable
    only at the end of a bill containing at least one real, explicitly typed
    MusicGroup/Person; never invent the support's identity.
    """
    performers = value if isinstance(value, list) else [value]
    if not performers:
        return None
    names, identities, unnamed = [], set(), None
    for index, performer in enumerate(performers):
        if not isinstance(performer, dict) or not (
                _event_types(performer.get("@type")) & {"MusicGroup", "Person"}):
            return None
        name = performer.get("name")
        if not isinstance(name, str) or not 2 <= len(name.strip()) <= 120:
            return None
        name = " ".join(name.split())
        normalized = name.casefold()
        if normalized in _UNANNOUNCED:
            if not names or index != len(performers) - 1 or unnamed is not None:
                return None
            unnamed = name
            continue
        if normalized in identities:
            return None
        identities.add(normalized)
        names.append(name)
    return (names, unnamed) if names else None


def candidate_from_event_page(
        lead, html, actual_url, source, known, day, *,
        read_ld, venue_candidate, norm, allow_generic_event=False):
    """Require one event, a real named performer, venue and source corroboration.

    This function returns a QUARANTINED discovery lead only. In particular,
    matching a MusicEvent here is not an independent publisher proof.
    """
    expected = lead.get("sourceUrl")
    if (not official_event_url(expected, source.get("url"))
            or not official_event_url(actual_url, source.get("url"))
            or expected.rstrip("/") != actual_url.rstrip("/")
            or not isinstance(html, str) or len(html) > 1_000_000):
        return None
    structures = [e for e in read_ld(html) if isinstance(e, dict)]
    music = [e for e in structures
             if "MusicEvent" in _event_types(e.get("@type"))]
    # The ordinary RSS bridge retains its original MusicEvent-only policy.
    # During independent recheck we may also inspect a generic schema.org
    # Event, but only with an explicit, recognized event-level music genre.
    # A venue's global tags, an artist biography or generic Rock do not count.
    generic_event = False
    if len(music) == 1:
        event = music[0]
    elif len(music) == 0 and allow_generic_event:
        generic = [e for e in structures
                   if "Event" in _event_types(e.get("@type"))]
        if len(generic) != 1 or not triage.genre_evidence(
                {"classification": generic[0].get("genre")}):
            return None
        event = generic[0]
        generic_event = True
    else:
        return None
    canonical = event.get("url")
    if (canonical is not None
            and (not official_event_url(canonical, source.get("url"))
                 or canonical.rstrip("/") != expected.rstrip("/"))):
        return None
    status = event.get("eventStatus")
    if isinstance(status, dict):
        status = status.get("@id") or status.get("name") or ""
    if isinstance(status, str) and re.search(
            r"cancel|postpon|reschedul|report|annul", status, re.I):
        return None
    bill = official_named_bill(event.get("performer"))
    if bill is None:
        return None
    location = event.get("location")
    if isinstance(location, list):
        if len(location) != 1:
            return None
        location = location[0]
    if not isinstance(location, dict) or not isinstance(location.get("name"), str):
        return None
    address = location.get("address")
    if not isinstance(address, dict) or not address.get("addressLocality"):
        return None
    country = address.get("addressCountry")
    if isinstance(country, dict):
        country = country.get("name") or country.get("@id")
    if country is not None and norm(country) not in (
            "fr", "france", "french republic", "republique francaise"):
        return None
    row = venue_candidate(event, source, actual_url, known, day.isoformat())
    if not row or row.get("sourceUrl", "").rstrip("/") != actual_url.rstrip("/"):
        return None
    if row.get("publicationAllowed") is not False:
        return None
    if bill[1] is not None and (
            row.get("leadArtist") != " + ".join(bill[0])
            or row.get("unannouncedSupportLabel") != bill[1]):
        return None
    # Do not set officialDetailFound: this is the first discovery proof,
    # not an independent verification of a new performance or band.
    row["discoveryBridge"] = (
        "independent-generic-event-genre-v1" if generic_event
        else "official-rss-music-event-v1"
    )
    return row
