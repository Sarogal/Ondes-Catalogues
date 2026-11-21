"""Admission of an UNLISTED first-party concert venue source.

The existing published venue is an identity anchor, NOT an allowlist of domains.
On every initial publication, the independent publisher fetches the fresh
individual MusicEvent and the named OpenStreetMap feature. The OSM feature
must explicitly link to the event site's actual HTTPS origin. A forged source
label, unknown organizer manifest entry, ticket listing, or merely matching
venue name cannot establish source authority.

Only for events at EXISTING catalogue venues with an OSM NODE source. New site
and organizer/producer cases use separate contracts and remain pending.
"""
from __future__ import annotations

import datetime as dt
import re
import sys
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "automation/concerts"
if str(SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIR))
import discover
import official_rss_jsonld_bridge as bridge
import source_admission_intake as intake
import source_evidence_probe as probe
import source_cross_domain_live_recheck as cross_live
import source_cross_domain_corroboration as cross
import triage
from independent_named_site_geo import _distance_meters

PROFILE = "dynamic-existing-venue-first-party-v1"
# A verified OSM node is independent location+website authority. A concert
# on that attributed HTTPS domain can stand on its own after a fresh exact
# MusicEvent recheck by the publisher; a second event domain is optional.
OSM_SINGLE_PROFILE = "dynamic-existing-venue-osm-official-v1"
PROOF_FIELDS = frozenset({
    "url", "proofType", "checkedAt", "checkedFields",
    "officialArtistNames", "officialGenreLabels", "namedOsmUrl",
    "corroboratingEventUrl",
})
OSM_SINGLE_PROOF_FIELDS = PROOF_FIELDS - {"corroboratingEventUrl"}
CHECKED = ["artists", "date", "venue", "genre", "sourceWebsite"]
# Publicly signed venue coordinates may reference either the human-friendly
# node page or the canonical API node path. Both encode the SAME immutable
# numeric OSM object ID; neither provides a network destination.
OSM_NODE = re.compile(
    r"https://(?:www[.]openstreetmap[.]org/(?:api/0[.]6/)?node/|"
    r"api[.]openstreetmap[.]org/api/0[.]6/node/)([1-9][0-9]*)\Z"
)
MAX_DISTANCE = 125
MAX_ARTIST_NAME = 120


def require(ok, message):
    if not ok:
        raise ValueError("Unlisted official source: " + message)


def normal(value):
    return triage.words(value) if isinstance(value, str) else ""


def url_host(value):
    host = intake.valid_https(value)
    require(bool(host), "unsafe HTTPS URL")
    parts = urlsplit(value)
    require(bool(parts.path and parts.path != "/") and
            not parts.fragment, "individual event detail required")
    return host


def origin_match(url_a, url_b):
    """Only an identical HTTPS origin, with an optional www prefix, matches."""
    try:
        a, b = url_host(url_a), intake.valid_https(url_b)
        require(bool(b), "OSM website is not a valid HTTPS source")
    except (TypeError, ValueError):
        return False
    return a.removeprefix("www.") == b.removeprefix("www.")


def safe_fetch(url, cache):
    return probe.safe_fetch(url, cache)


def osm_identity(venue, event_url, fetch, cache):
    """Independently read OSM feature identity; never trust venue.geoSource only."""
    raw = venue.get("geoSource")
    require(isinstance(raw, str), "venue has no independent OSM feature")
    matched = OSM_NODE.fullmatch(raw)
    require(bool(matched), "named OSM node (web/API) required for this admission route")
    api = "https://api.openstreetmap.org/api/0.6/node/" + matched.group(1)
    body = fetch(api, cache)
    require(isinstance(body, str) and len(body) <= probe.MAX_BYTES
            and "<!DOCTYPE" not in body.upper()
            and "<!ENTITY" not in body.upper(), "OSM answer invalid")
    root = ElementTree.fromstring(body)
    require(root.tag == "osm", "OSM document invalid")
    nodes = root.findall("node")
    require(len(nodes) == 1 and nodes[0].get("id") == matched.group(1),
            "named OSM node mismatched")
    node = nodes[0]
    tags = {tag.get("k"): tag.get("v") for tag in node.findall("tag")
            if isinstance(tag.get("k"), str)
            and isinstance(tag.get("v"), str)}
    require(normal(tags.get("name")) == normal(venue.get("name")),
            "OSM node does not identify published venue")
    for tag, field in (("addr:city", "city"), ("addr:postcode", "postalCode"),
                       ("addr:country", "country")):
        if tag == "addr:country":
            require(tags.get(tag, "FR").upper() == "FR", "OSM site outside France")
        elif tags.get(tag):
            require(normal(tags[tag]) == normal(venue.get(field)),
                    "OSM place/address differs from catalogue")
    try:
        lat, lon = float(node.get("lat")), float(node.get("lon"))
        require(_distance_meters(lat, lon,
                float(venue["latitude"]), float(venue["longitude"]))
                <= MAX_DISTANCE, "OSM point differs from signed published map")
    except (ValueError, TypeError, OverflowError):
        raise ValueError("Unlisted official source: invalid OSM coordinates")
    websites = [tags[key] for key in ("website", "contact:website")
                if isinstance(tags.get(key), str) and tags[key].strip()]
    require(len(websites) >= 1 and
            all(origin_match(event_url, value) for value in websites),
            "OSM does not independently attribute event domain to this venue")
    return raw


def _event(raw, event, venue, artists):
    """Parse this individual MusicEvent alone, no artist/venue master list."""
    require(isinstance(raw, dict)
            and "MusicEvent" in bridge._event_types(raw.get("@type")),
            "first-party MusicEvent schema required")
    require(not discover.reject_listing(raw.get("name")),
            "festival, cancelled or non-concert title is not a concert")
    canonical = raw.get("url")
    require(canonical is None or canonical == event["officialUrl"],
            "individual event canonical URL differs")
    require(discover.iso_day(raw.get("startDate")) == event["date"],
            "official event date differs")
    status = str(raw.get("eventStatus") or "").casefold()
    require(not any(s in status for s in (
        "cancel", "postpon", "resched", "report", "annul")),
        "official concert not confirmed")
    lineup = bridge.official_named_bill(raw.get("performer"))
    require(lineup is not None and bool(lineup[0]), "named official artists missing")
    names, _unnamed = lineup
    require(normal(" + ".join(names)) == normal(event.get("title")),
            "signed title differs from individual MusicEvent bill")
    require([normal(x) for x in names] ==
            [normal(artists[aid]["name"]) for aid in event.get("artistIds", [])],
            "artist IDs or names differ from individual official MusicEvent")
    genres, scope = bridge.event_genres_from_own_bill(raw)
    require(bool(triage.genre_evidence({
        "classification": genres,
        "genreEvidenceScope": scope,
        "officialDetailFound": True,
    })), "no explicit metal/rock/punk event-or-artist genre")
    # Different support artists may have different styles. Do not infer that
    # all performers belong to a single genre or require individual tags.
    require(all(normal(g) in {normal(x) for x in genres}
                for g in event.get("genres", [])),
            "signed genre differs from first-party MusicEvent")
    location = raw.get("location")
    require(isinstance(location, dict) and
            normal(location.get("name")) == normal(venue["name"]),
            "first-party event names another venue")
    addr = location.get("address")
    require(isinstance(addr, dict), "physical venue address absent")
    country = addr.get("addressCountry")
    if isinstance(country, dict):
        country = country.get("name") or country.get("@id")
    require(normal(country) in {"fr", "france", "republique francaise"},
            "event takes place outside France")
    require(normal(addr.get("addressLocality")) == normal(venue["city"]) and
            str(addr.get("postalCode")) == venue.get("postalCode"),
            "first-party postal address differs from published venue")
    # Missing street number is acceptable. It must still identify the site.
    require(normal(addr.get("streetAddress")) == normal(venue.get("address")),
            "official street conflicts with published venue")
    return names, genres


def validate(approval, venues, artists, today, *, fetch=None):
    """Publisher-bound source admission: fully re-fetch and compare the signed bill."""
    if fetch is None:
        fetch = safe_fetch
    require(isinstance(approval, dict)
            and approval.get("reviewDecision") == "approved"
            and approval.get("reviewedBy") == "independent-official-verifier",
            "independent event review missing")
    event = approval.get("event")
    require(isinstance(event, dict)
            and event.get("sourceType") == "salle"
            and event.get("status") == "confirmed"
            and event.get("time") is None,
            "only confirmed venue concerts without invented start time")
    require(event.get("date") >= today.isoformat(), "event expired")
    try:
        checked = dt.date.fromisoformat(approval.get("reviewedAt"))
        require(dt.timedelta(days=0) <= today - checked <= dt.timedelta(days=7),
                "first-party verification stale or future")
    except (ValueError, TypeError):
        raise ValueError("Unlisted official source: invalid review date")
    require(isinstance(event.get("artistIds"), list)
            and event["artistIds"]
            and len(set(event["artistIds"])) == len(event["artistIds"]),
            "named artist bill malformed")
    new = approval.get("newArtists") or []
    require(isinstance(new, list) and
            all(isinstance(row, dict) and row.get("id") not in artists
                and isinstance(row.get("name"), str) for row in new),
            "unverified new artist")
    resolved = dict(artists)
    resolved.update({a["id"]: a for a in new})
    require(len(resolved) == len(artists) + len(new)
            and all(aid in resolved for aid in event["artistIds"]),
            "unknown or duplicated new artist identity")
    venue = venues.get(event.get("venueId"))
    require(isinstance(venue, dict)
            and venue.get("id") == event["venueId"],
            "event physical venue is not published")
    proofset = approval.get("officialEvidence")
    require(isinstance(proofset, list) and len(proofset) == 1
            and isinstance(proofset[0], dict),
            "exact source-identity proof required")
    proof = proofset[0]
    is_single_osm = proof.get("proofType") == OSM_SINGLE_PROFILE
    require(set(proof) == (
                OSM_SINGLE_PROOF_FIELDS if is_single_osm else PROOF_FIELDS),
            "wrong first-party source evidence fields")
    require(proof["url"] == event.get("officialUrl")
            and proof["proofType"] in {PROFILE, OSM_SINGLE_PROFILE}
            and proof["checkedAt"] == approval.get("reviewedAt")
            and proof["checkedFields"] == CHECKED
            and proof["namedOsmUrl"] == venue.get("geoSource"),
            "first-party source evidence differs")
    origin = url_host(event["officialUrl"])
    witness = proof.get("corroboratingEventUrl")
    if not is_single_osm:
        witness_host = url_host(witness)
        require(cross.domain(witness_host) != cross.domain(origin),
                "cross-domain witness is controlled by the same source apex")
    cache = {}
    # Verify named public OSM feature AND its website attribution on each
    # prospective publication. This also detects later ownership changes.
    osm_identity(venue, event["officialUrl"], fetch, cache)
    html = fetch(event["officialUrl"], cache)
    require(isinstance(html, str) and
            100 <= len(html) <= probe.MAX_BYTES,
            "individual first-party HTML missing")
    events = [item for item in discover.read_ld(html)
              if isinstance(item, dict)
              and "MusicEvent" in bridge._event_types(item.get("@type"))]
    valid = []
    for raw in events:
        try:
            valid.append(_event(raw, event, venue, resolved))
        except (ValueError, KeyError, TypeError):
            continue
    require(len(valid) == 1, "no unique exact first-party MusicEvent")
    names, genres = valid[0]
    require(names == proof["officialArtistNames"]
            and genres == proof["officialGenreLabels"],
            "independent live event differs from signed first-party proof")
    if not is_single_osm:
        # The legacy two-domain proof still requires its fresh witness.
        corroboration = fetch(witness, cache)
        matched = cross_live.event_page_witness(
            corroboration, url=witness, date=event["date"],
            lead_artist=names[0], city=venue["city"], venue=venue["name"])
        require(normal(names[0]) in {normal(x) for x in matched["names"]},
                "independent event witness does not include named lead artist")
    # For OSM_SINGLE_PROFILE, trust comes from the freshly re-fetched,
    # independently named OSM feature AND this exact attributed venue-origin
    # MusicEvent. Neither a registry claim nor an OSM hostname by itself is
    # an event-level or artist-genre proof.
    return True
