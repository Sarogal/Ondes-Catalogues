#!/usr/bin/env python3
"""Event-scoped location approvals: a concert site is NOT a permanent hall.

This is a fail-closed, pure, offline PUBLISHER gate. The independent official
rechecker must produce a signed event approval and a separate, independently
checked location approval in the private ledger. This function cannot scrape,
geocode, create trust, or issue those approvals.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import re
from pathlib import Path
from urllib.parse import urlsplit

SOURCES = Path(__file__).resolve().parents[1] / "automation/concerts/artist-tour-sources.json"
PROFILE = "independent-event-site-v1"
KINDS = frozenset({"public-square", "street", "park", "temporary-stage", "outdoor-site"})
VENUE_FIELDS = frozenset({
    "id", "name", "address", "postalCode", "city", "department", "region",
    "latitude", "longitude", "geoPrecision", "geoSource",
})
APPROVAL_FIELDS = frozenset({
    "reviewDecision", "reviewedBy", "reviewedAt", "venueKind",
    "locationKind", "venue", "eventBinding", "officialEvidence",
})
BINDING_FIELDS = frozenset({
    "eventId", "eventDate", "eventOfficialUrl",
    "authoritySourceUrl", "authorityArtistId",
})
EVENT_FIELDS = frozenset({
    "url", "proofType", "checkedAt", "checkedFields", "eventId",
    "venueName", "city", "country",
})
GEO_FIELDS = frozenset({
    "url", "proofType", "checkedAt", "checkedFields",
    "venueName", "city", "country", "latitude", "longitude",
    "geoPrecision",
})
DEPT = re.compile(r"(?:0[1-9]|[1-8][0-9]|9[0-5]|2A|2B|97[1-8]|98[0-9])")
ZIP = re.compile(r"(?:[0-9]{5})")
SLUG = re.compile(r"go-c-[a-z0-9-]{7,150}")
MUSIC = re.compile(
    r"(?<![a-z])(?:metal|metalcore|deathcore|thrash|grindcore|"
    r"blackgaze|doom|sludge|stoner|punk|post punk|hard rock|"
    r"hardcore|screamo|skramz|shoegaze|grunge|"
    r"garage rock|noise rock|post rock|psych rock|"
    r"psychedelic rock|math rock|progressive rock)(?![a-z])"
)
ELECTRONIC_ONLY = re.compile(
    r"(?<![a-z])(?:hardcore techno|hardtek|frenchcore|gabber|"
    r"hardcore electronic|hardcore electro)(?![a-z])"
)


def relevant_genres(labels):
    if not isinstance(labels, list) or not 1 <= len(labels) <= 20:
        return False
    def normalize(value):
        import unicodedata
        v = unicodedata.normalize("NFKD", value.casefold())
        return re.sub(r"[^a-z0-9]+", " ", v.encode("ascii", "ignore").decode()).strip()
    return any(
        isinstance(value, str) and 2 <= len(value) <= 80
        and MUSIC.search(normalize(value))
        and not ELECTRONIC_ONLY.search(normalize(value))
        for value in labels
    )


def demand(condition, msg):
    if not condition:
        raise ValueError("Concert event-site: " + msg)


def official_url(value):
    if not isinstance(value, str) or len(value) > 2048:
        return None
    try:
        p = urlsplit(value)
        if (p.scheme != "https" or not p.hostname or p.username or p.password
                or p.port is not None or p.query or p.fragment
                or not p.path or p.path == "/"):
            return None
    except ValueError:
        return None
    return p


def geo_url(value):
    p = official_url(value)
    if not p or p.hostname != "www.openstreetmap.org":
        return False
    return bool(re.fullmatch(r"/(?:node|way|relation)/[1-9][0-9]{0,18}/?", p.path))


def number(x):
    return type(x) in (int, float) and math.isfinite(x)


def site_id(name, city, geo_source):
    """Stable physical site ID across concerts, without trusting the site."""
    text = "|".join((
        name.casefold().strip(), city.casefold().strip(),
        geo_source.rstrip("/").casefold(),
    ))
    return "go-site-" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:20]


def _sources(raw=None):
    if raw is None:
        raw = json.loads(SOURCES.read_text(encoding="utf-8"))
    demand(isinstance(raw, dict) and raw.get("schema")
           == "grossesondes.concert.artist_tour_sources.v1", "source registry absent")
    rows = raw.get("sources")
    demand(isinstance(rows, list), "source registry invalid")
    return rows


def validate(row, today, event_approvals, *, sources=None):
    """Return a defensive copy of a new public site only with TWO signed proofs.

    Requires a matching independent event approval already in the PRIVATE
    ledger; the publisher will separately validate that concert. No generic
    trust in a location, source discovery, Ticketmaster or an OSM pin.
    """
    import copy

    demand(isinstance(today, dt.date) and not isinstance(today, dt.datetime),
           "invalid day")
    demand(isinstance(row, dict) and set(row) == APPROVAL_FIELDS,
           "unexpected location approval structure")
    demand(row.get("reviewDecision") == "approved"
           and row.get("reviewedBy") == "independent-official-verifier"
           and row.get("venueKind") == PROFILE
           and row.get("locationKind") in KINDS,
           "location not independently reviewed")
    reviewed = row.get("reviewedAt")
    try:
        checked = dt.date.fromisoformat(reviewed)
    except (TypeError, ValueError):
        raise ValueError("Concert event-site: invalid review date")
    demand(checked <= today, "future review date")
    venue = row.get("venue")
    binding = row.get("eventBinding")
    demand(isinstance(venue, dict) and set(venue) == VENUE_FIELDS,
           "invalid public venue fields")
    demand(isinstance(binding, dict) and set(binding) == BINDING_FIELDS,
           "invalid event identity")
    ev_id, ev_day, ev_url = (binding.get("eventId"),
                             binding.get("eventDate"),
                             binding.get("eventOfficialUrl"))
    demand(isinstance(ev_id, str) and SLUG.fullmatch(ev_id) is not None,
           "invalid concert identifier")
    try:
        actual_day = dt.date.fromisoformat(ev_day)
    except (TypeError, ValueError):
        raise ValueError("Concert event-site: invalid concert date")
    demand(checked <= actual_day, "site proof recorded after concert")
    official = official_url(ev_url)
    authority = official_url(binding.get("authoritySourceUrl"))
    demand(official is not None and authority is not None,
           "missing official event and authority URLs")
    authority_id = binding.get("authorityArtistId")
    demand(isinstance(authority_id, str) and authority_id,
           "missing source artist")
    eligible = [
        x for x in _sources(sources)
        if isinstance(x, dict) and x.get("enabled") is True
        and x.get("url") == binding["authoritySourceUrl"]
        and x.get("artistId") == authority_id
        and x.get("sourceRole") in {"artist_official", "promoter_official"}
    ]
    demand(len(eligible) == 1 and authority.hostname == official.hostname,
           "official event not bound to a reviewed artist/promoter source")

    demand(isinstance(event_approvals, list), "event approvals missing")
    matches = [
        x for x in event_approvals
        if isinstance(x, dict) and isinstance(x.get("event"), dict)
        and x["event"].get("id") == ev_id
    ]
    demand(len(matches) == 1, "independent concert approval missing/ambiguous")
    signed = matches[0]
    event = signed["event"]
    demand(signed.get("reviewDecision") == "approved"
           and signed.get("reviewedAt") == reviewed
           and isinstance(event.get("artistIds"), list)
           and signed.get("reviewedBy") == "independent-official-verifier"
           and event.get("date") == ev_day
           and event.get("officialUrl") == ev_url
           and event.get("venueId") == venue.get("id")
           and authority_id in event.get("artistIds", [])
           and event.get("status") == "confirmed"
           and relevant_genres(event.get("genres")),
           "event/artist/date/site/genre binding mismatch")
    event_proof = signed.get("officialEvidence")
    demand(isinstance(event_proof, list) and any(
        isinstance(p, dict) and p.get("url") == ev_url
        and p.get("checkedAt") == signed.get("reviewedAt")
        and p.get("proofType") == "official-organizer-or-venue"
        and {"artists", "date", "venue", "genre"}.issubset(
            set(p.get("checkedFields") or []))
        for p in event_proof),
        "independent event proof missing exact bill, date, venue or genre")

    name, city = venue.get("name"), venue.get("city")
    for field in ("name", "address", "city", "region", "geoPrecision"):
        demand(isinstance(venue.get(field), str)
               and 3 <= len(venue[field].strip()) <= 180
               and "a verifier" not in venue[field].casefold()
               and "à vérifier" not in venue[field].casefold(),
               "incomplete site address: " + field)
    demand(type(venue.get("department")) is str
           and DEPT.fullmatch(venue["department"]) is not None
           and type(venue.get("postalCode")) is str
           and ZIP.fullmatch(venue["postalCode"]) is not None,
           "unknown department or postcode")
    demand(venue.get("id") == site_id(name, city, venue.get("geoSource", "")),
           "site identifier does not match the named geographic feature")
    lat, lon = venue.get("latitude"), venue.get("longitude")
    demand(number(lat) and number(lon) and -56 <= lat <= 52
           and -180 <= lon <= 180 and not (lat == 0 and lon == 0),
           "invalid or non-French approximate coordinates")
    demand(venue["geoPrecision"] in {"named-site-point", "named-site-area"},
           "location must be a named real site, not a city centre")
    demand(geo_url(venue.get("geoSource")), "OSM feature URL required")

    proofs = row.get("officialEvidence")
    demand(isinstance(proofs, list) and len(proofs) == 2
           and all(isinstance(p, dict) for p in proofs),
           "two independent site proofs required")
    official_proofs = [x for x in proofs if x.get("proofType") == "official-event-location"]
    geo_proofs = [x for x in proofs if x.get("proofType") == "independent-osm-site"]
    demand(len(official_proofs) == len(geo_proofs) == 1,
           "official event and independent OSM proofs required")
    p, g = official_proofs[0], geo_proofs[0]
    demand(set(p) == EVENT_FIELDS and set(g) == GEO_FIELDS,
           "unknown proof fields")
    demand(p.get("url") == ev_url and g.get("url") == venue["geoSource"]
           and p.get("checkedAt") == reviewed
           and g.get("checkedAt") == reviewed
           and p.get("eventId") == ev_id
           and p.get("venueName") == name == g.get("venueName")
           and p.get("city") == city == g.get("city")
           and p.get("country") == g.get("country") == "FR"
           and p.get("checkedFields") == ["eventId", "date", "venueName", "city", "country"]
           and g.get("checkedFields") == ["venueName", "city", "coordinates", "country"]
           and number(g.get("latitude")) and number(g.get("longitude"))
           and g.get("latitude") == lat and g.get("longitude") == lon
           and g.get("geoPrecision") == venue["geoPrecision"],
           "event-specific site and mapped feature not corroborated")
    demand(official.hostname != urlsplit(venue["geoSource"]).hostname,
           "same publisher cannot certify event and location independently")
    return copy.deepcopy(venue)
