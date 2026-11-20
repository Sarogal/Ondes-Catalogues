"""Reusable first-party RSS -> individually dated MusicEvent discovery bridge.

RSS publishing timestamps are NEVER concert dates. A fresh first-party
event page must present exactly one structured MusicEvent, or an explicitly
genre-tagged Event on a trusted, opt-in first-party discovery path.
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


def event_genres_from_own_bill(raw):
    """Read explicit genre attached to THIS Event or its named performers only.

    This does not consult artist catalogs, biographies, venue-wide menus or
    adjacent Events. Non-string, excessive or ambiguous labels fail closed.
    The independent reviewer and publisher remain genre authorities.
    Returns (labels, provenance_scope).
    """
    if not isinstance(raw, dict):
        return [], "official_event_card"

    def labels(value):
        if isinstance(value, str):
            value = [value]
        if (not isinstance(value, list) or len(value) > 20
                or any(not isinstance(x, str) or
                       not 2 <= len(x.strip()) <= 80 for x in value)):
            return None
        return [x.strip() for x in value]

    # Event.genre is an aggregate classification, not a required common
    # genre for every opening act. Check each named performer first.
    direct = raw.get("genre")
    event_labels = labels(direct) if direct not in (None, "", []) else []
    if event_labels is None:
        event_labels = []

    bill = official_named_bill(raw.get("performer"))
    if bill is None:
        return event_labels, "official_event_card"
    names = {x.casefold() for x in bill[0]}
    performers = raw.get("performer")
    performers = performers if isinstance(performers, list) else [performers]
    collected = []
    for performer in performers:
        if not isinstance(performer, dict):
            return [], "official_artist_in_event_detail"
        if performer.get("name", "").strip().casefold() not in names:
            if bill[1] and performer.get("name", "").strip().casefold() == bill[1].casefold():
                continue  # An explicitly unnamed support is not genre proof.
            return [], "official_artist_in_event_detail"
        genre = performer.get("genre")
        if genre is None:
            continue
        values = labels(genre)
        if values is None:
            return [], "official_artist_in_event_detail"
        collected.extend(values)
    # The publisher caps serialized GENRE labels to 20, never the number of
    # artists in the bill. For large mixed lineups, retain recognized rock/
    # metal/punk labels first: an eligible act at position 30 cannot disappear
    # because 29 earlier acts had different, irrelevant genre descriptions.
    unique = list(dict.fromkeys(collected))
    if len(unique) > 20:
        relevant = [label for label in unique
                    if triage.genre_evidence({"classification": [label]})]
        irrelevant = [label for label in unique if label not in relevant]
        unique = (relevant + irrelevant)[:20]
    # An explicitly named metal/punk/hard-rock performer makes a mixed
    # bill eligible even when the general event tag says Jazz, Pop, etc.
    # Conversely, do not treat that general tag as the genre of *all* bands.
    # When performer genre evidence is absent or irrelevant, retain the
    # historical event-level evidence as a fallback, never as a per-band fact.
    if triage.genre_evidence({"classification": unique}):
        return unique, "official_artist_in_event_detail"
    if triage.genre_evidence({"classification": event_labels}):
        return event_labels, "official_event_card"
    return unique or event_labels, (
        "official_artist_in_event_detail" if unique else "official_event_card")


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
        if len(generic) != 1:
            return None
        # A MusicGroup on this exact official Event can establish a relevant
        # genre even if the overall Event.genre is missing or unrelated.
        scoped_genres, _ = event_genres_from_own_bill(generic[0])
        if not triage.genre_evidence({"classification": scoped_genres}):
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
    # Keep individual performer genre evidence attached to the current
    # reviewed Event, rather than relying on the page's aggregate category.
    scoped_genres, genre_scope = event_genres_from_own_bill(event)
    if scoped_genres and triage.genre_evidence(
            {"classification": scoped_genres}):
        row["classification"] = scoped_genres
        row["genreEvidenceScope"] = genre_scope
    if row.get("publicationAllowed") is not False:
        return None
    if bill[1] is not None and (
            row.get("leadArtist") != " + ".join(bill[0])
            or row.get("unannouncedSupportLabel") != bill[1]):
        return None
    # Do not set officialDetailFound: this is the first discovery proof,
    # not an independent verification of a new performance or band.
    row["discoveryBridge"] = (
        "official-structured-generic-event-v1" if generic_event
        else "official-rss-music-event-v1"
    )
    return row
