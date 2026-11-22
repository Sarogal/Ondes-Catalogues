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
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

# The existing discovery modules have legacy top-level sibling imports.
# One explicit local path supports both standalone CLI and package tests.
_SOURCE_DIR = Path(__file__).resolve().parent
_ROOT = Path(__file__).resolve().parents[2]
for _path in (str(_ROOT), str(_SOURCE_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

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



def _numeric_uid(value):
    """Only decimal OpenAgenda IDs can enter a pinned first-party export URL."""
    if type(value) not in (int, str):
        raise ValueError("OpenAgenda: malformed numeric identifier")
    raw = str(value)
    if (not raw.isascii() or not raw.isdecimal()
            or not 1 <= len(raw) <= 12 or int(raw) == 0):
        raise ValueError("OpenAgenda: malformed numeric identifier")
    return int(raw)


def official_export_url(agenda_uid, event_uid):
    """OpenAgenda's own public read-only export, never a candidate URL."""
    agenda_uid = _numeric_uid(agenda_uid)
    event_uid = _numeric_uid(event_uid)
    return (f"https://openagenda.com/agendas/{agenda_uid}/events.json"
            f"?uid={event_uid}&limit=1")


def verified_export(raw_json, url, when, venue, *, agenda_uid, event_uid):
    """Fresh OpenAgenda-owned single-event export; no external corroboration.

    The public national index may suggest IDs, but cannot sign a concert.
    The actual OpenAgenda export must bind both IDs to the exact source slug,
    date, published location and music classification.
    """
    if not is_openagenda_event_url(url):
        raise ValueError("OpenAgenda: noncanonical event URL")
    origin_id = _numeric_uid(agenda_uid)
    record_id = _numeric_uid(event_uid)
    if not isinstance(raw_json, str) or not 20 <= len(raw_json) <= 400_000:
        raise ValueError("OpenAgenda: official JSON export missing")
    try:
        doc = json.loads(raw_json)
    except (TypeError, ValueError) as exc:
        raise ValueError("OpenAgenda: invalid official JSON export") from exc
    if (not isinstance(doc, dict) or doc.get("total") != 1
            or not isinstance(doc.get("events"), list)
            or len(doc["events"]) != 1
            or not isinstance(doc["events"][0], dict)):
        raise ValueError("OpenAgenda: no unique original event")
    record = doc["events"][0]
    agenda = record.get("originAgenda")
    path_parts = [x for x in urlsplit(url).path.split("/") if x]
    if path_parts and path_parts[0] in ("fr", "en"):
        path_parts = path_parts[1:]
    if len(path_parts) != 3 or path_parts[1] != "events":
        raise ValueError("OpenAgenda: invalid original event slug")
    event_slug = str(record.get("slug") or "")
    source_slug = re.sub(r"^[0-9]{1,12}[_-]", "", path_parts[2])
    if (type(record.get("uid")) is not int or record["uid"] != record_id
            or not isinstance(agenda, dict)
            or type(agenda.get("uid")) is not int
            or agenda["uid"] != origin_id
            or normalized(agenda.get("slug")) != normalized(path_parts[0])
            or not event_slug or event_slug != source_slug):
        raise ValueError("OpenAgenda: original event identity not authenticated")
    # OpenAgenda status 1 means published/scheduled; cancelled, postponed
    # and deprogrammed records never enter the public confirmed catalogue.
    if record.get("status") != 1:
        raise ValueError("OpenAgenda: event is not currently scheduled")
    try:
        exact = dt.date.fromisoformat(when)
        if (record.get("firstDate") != exact.isoformat()
                or dt.date.fromisoformat(record.get("lastDate")) < exact):
            raise ValueError("OpenAgenda: contradictory event date")
    except (ValueError, TypeError) as exc:
        raise ValueError("OpenAgenda: invalid event date") from exc
    place = record.get("location")
    if (not isinstance(place, dict)
            or normalized(place.get("name")) != normalized(venue.get("name"))
            or normalized(place.get("city")) != normalized(venue.get("city"))):
        raise ValueError("OpenAgenda: official physical venue mismatch")
    if (place.get("postalCode") and venue.get("postalCode")
            and str(place["postalCode"]) != str(venue["postalCode"])):
        raise ValueError("OpenAgenda: postal code mismatch")
    street = place.get("address")
    if (street and venue.get("address")
            and not normalized(street).startswith(
                normalized(venue["address"]))):
        raise ValueError("OpenAgenda: official street location mismatch")
    if str(place.get("countryCode") or "").lower() not in ("fr", "gp",
            "mq", "gf", "re", "yt", "nc", "pf", "wf", "pm", "bl", "mf"):
        raise ValueError("OpenAgenda: non-French event location")
    title = record.get("title")
    title = (title.get("fr") or title.get("en")) if isinstance(
        title, dict) else None
    if (not isinstance(title, str) or not 3 <= len(title) <= 900
            or any(x in normalized(title)
                   for x in ("festival", "annule", "annulled"))):
        raise ValueError("OpenAgenda: missing concert bill or festival")
    keys = record.get("keywords")
    raw_genres = ((keys.get("fr") or keys.get("en"))
                  if isinstance(keys, dict) else None)
    if not isinstance(raw_genres, list):
        raise ValueError("OpenAgenda: original music tags missing")
    # Event-level keywords attest musical relevance; never assign each band's
    # style from the headliner's tags.
    genres = [x for x in raw_genres
              if isinstance(x, str) and contract.relevant_genres([x])]
    genres = list(dict.fromkeys(genres))
    if not genres or len(genres) > 20:
        raise ValueError("OpenAgenda: outside metal/hard-rock/punk universe")
    names = _bill({"@type": "MusicEvent", "name": title})
    return names, genres


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
