"""Generic, quarantined first-party concert cards visible in ordinary HTML.

Some official sites present a semantic *sequence* of visible elements:
complete date -> named artist bill -> explicitly labelled concert genre ->
visible venue attribution, without Event/MusicEvent JSON-LD. This parser
recognizes the INFORMATION RELATIONSHIP, not a site-specific CSS selector,
domain, artist or address. A site URL from the private registry is NOT proof
that the room owns that domain. Results are discovery hints only; Publisher
must independently re-fetch, authenticate and geolocate the event.
"""
from __future__ import annotations

import datetime as dt
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import official_html_evidence as visible
from triage import words

MAX_HTML = 1_000_000
DATE_SEPARATOR = re.compile(r"\s+[–—―]\s+")
CONCERT_GENRE = re.compile(r"(?i)^\s*(?:concert|live concert|concert live)\s*[–—―-]\s*(.+?)\s*$")
VENUE_ARROW = re.compile(r"^\s*[→➡]\s*(.+?)\s*$")
TRAILING_KIND = re.compile(r"\s+[–—―-]\s+(?:salle\b|music venue\b|concert hall\b).*", re.I)
CANCELLED = re.compile(
    r"\b(?:annule|annulee|report|reporte|reportee|cancelled|canceled|postponed|rescheduled)\b")
ARTIST_SPLIT = re.compile(r"\s+\+\s+")
PLACEHOLDER = frozenset({"tba", "guest", "special guest",
                         "premiere partie", "artiste surprise", "a confirmer"})


def _room_key(raw):
    key = words(raw)
    return re.sub(r"^(?:le|la|les|l|the)\s+", "", key)


def _date(text):
    # The standalone em dash joining day and month is decorative; the date
    # still MUST supply an explicit full year and a valid calendar day.
    normalized = DATE_SEPARATOR.sub(" ", text)
    found = visible._date_in(normalized)
    if not isinstance(found, str) or not re.fullmatch(r"20\d{2}-\d{2}-\d{2}", found):
        return None
    return found


def _artists(label):
    label = " ".join(str(label or "").split())
    if not 2 <= len(label) <= 600:
        return None
    names = [x.strip() for x in ARTIST_SPLIT.split(label)]
    if (not 1 <= len(names) <= 30
            or any(not 2 <= len(x) <= 120 for x in names)
            or any(words(x) in PLACEHOLDER for x in names)
            or len({words(x) for x in names}) != len(names)):
        return None
    if any(re.search(r"(?i)\b(?:billetterie|concert|ouverture|portes|salle)\b", x)
           for x in names):
        return None
    return names


def extract(html, room, city, today):
    """Return strictly associated event-card leads, never a publication claim.

    Use only <p>-level visible blocks. Recommendation panels often have
    <h2> date / <h5> genre / <h3> artist but are NOT official detail proof:
    do not join them with the primary venue page or nearby paragraphs.
    """
    if (not isinstance(html, str) or len(html) > MAX_HTML
            or not isinstance(room, str) or not 2 <= len(room) <= 140
            or not isinstance(city, str) or not 2 <= len(city) <= 120
            or not isinstance(today, dt.date) or isinstance(today, dt.datetime)):
        return []
    parser = visible.VisibleBlocks()
    try:
        parser.feed(html)
        parser.close()
    except (ValueError, TypeError, RecursionError):
        return []
    blocks = parser.blocks
    # An official venue page must at least display the asserted city.
    # This is a weak correlation, not origin or geographic attestation.
    if not visible._contains(" ".join(x for _, x in blocks), city):
        return []
    paras = [x for tag, x in blocks if tag == "p"]
    matches, identities = [], set()
    for i in range(len(paras) - 3):
        date = _date(paras[i])
        if not date or date < today.isoformat():
            continue
        artists = _artists(paras[i + 1])
        if not artists:
            continue
        genre_match = CONCERT_GENRE.fullmatch(paras[i + 2])
        place_match = VENUE_ARROW.fullmatch(paras[i + 3])
        if not genre_match or not place_match:
            continue
        genre = visible._explicit_label(genre_match[1])
        name = TRAILING_KIND.sub("", place_match[1]).strip()
        if (not genre or _room_key(name) != _room_key(room)
                or not _room_key(name)):
            continue
        around = " ".join(paras[max(0, i - 2): i + 4])
        if CANCELLED.search(words(around)):
            continue
        key = (date, tuple(words(a) for a in artists), _room_key(name))
        if key in identities:
            continue
        identities.add(key)
        matches.append({
            "date": date, "artists": artists, "genre": genre,
            "venue": room, "city": city,
            "evidenceScope": "visible-event-card-review-only",
        })
    return matches
