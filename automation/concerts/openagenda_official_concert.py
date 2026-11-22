"""One published OpenAgenda event page is enough to prove a concert.

The official OpenAgenda public page itself supplies the named event, concert
date, listed performers (including + delimited co-headliners), event-scoped
genre and location. No second website, artist allowlist, municipality or OSM
lookup is required for a site ALREADY on the Grosses Ondes public map.

Discovery/OpendataSoft metadata is never admission authority. An actual fresh
OpenAgenda page is fetched by independent publisher and is compared against
the exact signed event at each initial admission. No description or image is
republished; the public event URL attributes the originating record.
"""
from __future__ import annotations

import datetime as dt
import re
from urllib.parse import urlsplit

from automation.concerts import discover
from automation.concerts import official_rss_jsonld_bridge as bridge
from scripts import concert_event_site_contract as contract
from automation.concerts.source_admission_intake import normalized

AGENDA_PATH = re.compile(
    r"/(?:fr/|en/)?[a-z0-9][a-z0-9-]{1,119}/events/"
    r"[a-z0-9][a-z0-9_-]{2,180}/?\Z", re.I)
CANCELLED = ("cancel", "postpon", "resched", "report", "annul")
PLACEHOLDERS = frozenset(("concert", "soiree", "festival", "concert punk",
                          "concert metal", "live", "show", "spectacle"))


def is_openagenda_event_url(url):
    if not isinstance(url, str) or not 20 <= len(url) <= 1000:
        return False
    try:
        u = urlsplit(url)
        return (u.scheme == "https" and u.hostname == "openagenda.com"
                and not u.username and not u.password and u.port is None
                and not u.query and not u.fragment
                and AGENDA_PATH.fullmatch(u.path) is not None)
    except ValueError:
        return False


def _performer_names(value):
    rows = value if isinstance(value, list) else [value]
    out = []
    for item in rows:
        if isinstance(item, str):
            n = item
        elif isinstance(item, dict) and bridge._event_types(
                item.get("@type")) & {"MusicGroup", "Person",
                                      "PerformingGroup", "Organization"}:
            n = item.get("name")
        else:
            continue
        if isinstance(n, str) and 2 <= len(n.strip()) <= 120:
            out.append(" ".join(n.split()))
    return out


def _bill(event):
    title = event.get("name")
    if not isinstance(title, str) or not 3 <= len(title) <= 900:
        raise ValueError("OpenAgenda: missing named event title")
    named = _performer_names(event.get("performer"))
    # A first-party title explicitly listing GROUP + GROUP is itself a named
    # complete bill, even when schema.org performer lists only the headliner.
    # Never generalize one headliner's genre to the support act; event.genre
    # is stored as an EVENT-level label.
    parts = re.split(r"\s+\+\s+", title)
    if len(parts) > 1:
        if any(not 2 <= len(part.strip()) <= 120 for part in parts):
            raise ValueError("OpenAgenda: malformed named lineup")
        title_names = [" ".join(part.split()) for part in parts]
        known = {normalized(n) for n in title_names}
        if any(normalized(n) not in known for n in named):
            raise ValueError("OpenAgenda: structured performer contradicts title")
        names = title_names
    elif named:
        names = named
    elif normalized(title) not in PLACEHOLDERS and "concert " not in normalized(title):
        # A single explicitly named act is sufficient only if the page is a
        # MusicEvent, not a generic exhibition or conference.
        if "MusicEvent" not in bridge._event_types(event.get("@type")):
            raise ValueError("OpenAgenda: untyped single-act concert")
        names = [title]
    else:
        raise ValueError("OpenAgenda: no explicitly named performers")
    if (len({normalized(s) for s in names}) != len(names)
            or any(not normalized(s) for s in names)):
        raise ValueError("OpenAgenda: duplicate or malformed performers")
    return names


def verified_bill(html, url, when, venue):
    """Return (names, event_genres) from one fresh, source-bound OA page."""
    if not is_openagenda_event_url(url):
        raise ValueError("Not an individual public OpenAgenda event URL")
    if not isinstance(html, str) or not 100 <= len(html) <= 400_000:
        raise ValueError("OpenAgenda: event page unavailable or oversized")
    rows = [e for e in discover.read_ld(html) if isinstance(e, dict) and
            bridge._event_types(e.get("@type")) & {"Event", "MusicEvent"}]
    eligible = []
    for row in rows:
        if discover.reject_listing(row.get("name")):
            continue
        if discover.iso_day(row.get("startDate")) != when:
            continue
        try:
            dt.date.fromisoformat(when)
        except (ValueError, TypeError):
            continue
        state = str(row.get("eventStatus") or "").casefold()
        if any(s in state for s in CANCELLED):
            continue
        location = row.get("location")
        if not isinstance(location, dict):
            continue
        if normalized(location.get("name")) != normalized(venue.get("name")):
            continue
        addr = location.get("address")
        if isinstance(addr, dict):
            if (addr.get("addressLocality") and normalized(
                    addr["addressLocality"]) != normalized(venue.get("city"))):
                continue
            if (addr.get("postalCode") and str(addr["postalCode"]) != str(
                    venue.get("postalCode"))):
                continue
            street = addr.get("streetAddress")
        elif isinstance(addr, str):
            street = addr
        else:
            street = None
        # The Opendata event is venue-scoped: an explicitly contradictory
        # postal/street address fails. If absent, the already published venue
        # supplies the map point, never a fabricated city-centre coordinate.
        if (street and venue.get("address") and
                normalized(street) != normalized(venue["address"])):
            continue
        genre = row.get("genre")
        genre = ([genre] if isinstance(genre, str) else genre)
        if (not isinstance(genre, list)
                or any(not isinstance(g, str) for g in genre)
                or not contract.relevant_genres(genre)):
            # The same event's structured performers may contain individual
            # genre labels even when Event.genre is omitted.
            genre, _ = bridge.event_genres_from_own_bill(row)
            if not contract.relevant_genres(genre):
                continue
        try:
            names = _bill(row)
        except ValueError:
            continue
        eligible.append((names, list(dict.fromkeys(genre))))
    if len(eligible) != 1:
        raise ValueError("OpenAgenda: no unique exact dated musical event")
    return eligible[0]
