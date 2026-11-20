"""Publisher-side proof for a new concert at an ALREADY published venue.

Unlike an event-site approval, this adds no pin. A separate first-party
organizer authority, individually rechecked Event/MusicEvent and independent
named OSM feature are all required. Never trust a venue ID from the lead alone.
"""
from __future__ import annotations

import datetime as dt
import math
import re
from urllib.parse import urlsplit

from automation.concerts import organizer_source_contract as organizers
from automation.concerts import triage

PROOF_KIND = "independent-existing-venue-v1"
OSM = re.compile(r"https://www[.]openstreetmap[.]org/(?:node|way)/[1-9][0-9]*\Z")
FIELDS = frozenset({
    "url", "proofType", "checkedAt", "checkedFields",
    "venueId", "venueName", "city", "department", "postalCode",
    "latitude", "longitude", "geoPrecision", "authoritySourceUrl",
    "authorityArtistId",
})
CHECKED = [
    "venueId", "venueName", "city", "department", "postalCode",
    "coordinates", "authoritySourceUrl",
]
FIRST_FIELDS = frozenset({
    "url", "proofType", "checkedAt", "checkedFields",
    "officialArtistNames", "officialGenreLabels",
})
FIRST_CHECKED = ["artists", "date", "venue", "genre"]


def require(ok, reason):
    if not ok:
        raise ValueError("Existing venue concert: " + reason)


def norm(value):
    return triage.words(value) if isinstance(value, str) else ""


def validate(approval, venues, known_artists, today):
    """Reject spoofed organizer, unrelated venue and artist/bill mutation."""
    require(isinstance(today, dt.date) and not isinstance(today, dt.datetime),
            "invalid current date")
    require(isinstance(approval, dict)
            and approval.get("reviewDecision") == "approved"
            and approval.get("reviewedBy") == "independent-official-verifier",
            "not an independent event review")
    event = approval.get("event")
    require(isinstance(event, dict)
            and event.get("sourceType") == "organisateur"
            and event.get("status") == "confirmed",
            "not an official confirmed organizer concert")
    checked = approval.get("reviewedAt")
    try:
        reviewed = dt.date.fromisoformat(checked)
    except (ValueError, TypeError):
        raise ValueError("Existing venue concert: malformed review date")
    require(reviewed <= today, "review in the future")
    proof = approval.get("officialEvidence")
    require(isinstance(proof, list) and len(proof) == 2
            and all(isinstance(x, dict) for x in proof),
            "exact official bill and independent OSM evidence required")
    official, site = proof
    require(set(official) == FIRST_FIELDS
            and official.get("url") == event.get("officialUrl")
            and official.get("proofType") == "official-organizer-or-venue"
            and official.get("checkedAt") == checked
            and official.get("checkedFields") == FIRST_CHECKED,
            "official individual bill proof mismatch")
    require(set(site) == FIELDS
            and site.get("proofType") == PROOF_KIND
            and site.get("checkedAt") == checked
            and site.get("checkedFields") == CHECKED
            and site.get("venueId") == event.get("venueId")
            and site.get("authorityArtistId") is None,
            "existing-venue geographical proof mismatch")

    # The trusted organizer is a separately committed manifest: neither
    # discovery's own sourceRole nor its own claimed organizer ID is authority.
    matches = [
        entry for entry in organizers.read_sources()
        if entry.get("enabled") is True
        and entry.get("url") == site.get("authoritySourceUrl")
        and dt.date.fromisoformat(entry["checkedAt"]) <= reviewed
        and organizers.scoped_event_url(entry, event.get("officialUrl"))
    ]
    require(len(matches) == 1, "unreviewed organizer/event URL authority")
    url = site.get("url")
    require(isinstance(url, str) and OSM.fullmatch(url) is not None
            and site.get("geoPrecision") in {"named-site-point",
                                             "named-site-area"},
            "not an independently named OSM location")
    lat, lon = site.get("latitude"), site.get("longitude")
    require(type(lat) in (float, int) and type(lon) in (float, int)
            and math.isfinite(lat) and math.isfinite(lon)
            and -90 <= lat <= 90 and -180 <= lon <= 180,
            "invalid independent location coordinates")

    require(isinstance(venues, dict), "published venues unavailable")
    venue = venues.get(site.get("venueId"))
    require(isinstance(venue, dict), "venue not in published catalogue")
    require(norm(venue.get("name")) == norm(site.get("venueName"))
            and norm(venue.get("city")) == norm(site.get("city"))
            and str(venue.get("department") or "").upper()
                == str(site.get("department") or "").upper(),
            "published venue identity or department disagrees")
    postal = str(site.get("postalCode") or "")
    require(re.fullmatch(r"[0-9]{5}", postal) is not None,
            "unverifiable official postcode")
    catalogued_postal = str(venue.get("postalCode") or "")
    require(re.fullmatch(r"[0-9]{5}", catalogued_postal) is None
            or postal == catalogued_postal,
            "official postcode contradicts published venue")

    names = official.get("officialArtistNames")
    genres = official.get("officialGenreLabels")
    ids = event.get("artistIds")
    require(isinstance(names, list) and isinstance(ids, list)
            and 1 <= len(names) == len(ids)
            and len({norm(n) for n in names}) == len(names)
            and all(isinstance(n, str) and 2 <= len(n.strip()) <= 120
                    for n in names)
            and event.get("title") == " + ".join(names),
            "official named bill differs from signed event")
    require(isinstance(genres, list) and genres == event.get("genres")
            and bool(triage.genre_evidence({"classification": genres})),
            "official artist genre does not support this concert")
    new_artists = approval.get("newArtists") or []
    require(isinstance(new_artists, list)
            and all(isinstance(a, dict) and a.get("id") and a.get("name")
                    for a in new_artists), "invalid new artist list")
    resolved = dict(known_artists)
    resolved.update({a["id"]: a for a in new_artists})
    require(all(artist_id in resolved
                and norm(resolved[artist_id].get("name")) == norm(artist_name)
                for artist_id, artist_name in zip(ids, names)),
            "artist ID or named lineup not independently corroborated")
    return True
