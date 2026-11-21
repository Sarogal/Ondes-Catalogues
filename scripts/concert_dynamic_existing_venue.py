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
from urllib.parse import urlsplit, urlencode
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
# Existing published venues with historical non-OSM geoSource may be
# independently checked via their EXACT French street + named OSM feature.
# A city centroid or venue name alone never creates source authority.
OSM_ADDRESS_PROFILE = "dynamic-existing-venue-address-official-v1"
PROOF_FIELDS = frozenset({
    "url", "proofType", "checkedAt", "checkedFields",
    "officialArtistNames", "officialGenreLabels", "namedOsmUrl",
    "corroboratingEventUrl",
})
OSM_SINGLE_PROOF_FIELDS = PROOF_FIELDS - {"corroboratingEventUrl"}
OSM_ADDRESS_PROOF_FIELDS = OSM_SINGLE_PROOF_FIELDS | {
    "publishedVenueGeoSource", "sourceWebsite"}
CHECKED = ["artists", "date", "venue", "genre", "sourceWebsite"]
ADDRESS_CHECKED = CHECKED + ["independentLocation"]
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
    # Both hosts are official OpenStreetMap API origins. Some public runners
    # cannot reach one origin reliably. Retry ONLY a network failure, never
    # a successfully fetched but contradictory/malformed OSM identity.
    # The numeric node is still taken solely from the published venue ref.
    api_paths = (
        "https://api.openstreetmap.org/api/0.6/node/",
        "https://www.openstreetmap.org/api/0.6/node/",
    )
    body = None
    for prefix in api_paths:
        try:
            body = fetch(prefix + matched.group(1), cache)
            break
        except (ValueError, OSError, TimeoutError):
            continue
    if body is None:
        # OpenStreetMap's Editing API is not a dependable READ-ONLY data
        # source for national concert research. Use a dedicated Overpass
        # read-only provider with a FIXED bounded, single-node query.
        # No candidate-controlled URL, user-supplied query or redirect.
        # This still uses the robots-aware, DNS-pinned HTTPS fetcher.
        overpass_url = (
            "https://overpass.private.coffee/api/interpreter?" +
            urlencode({"data": "[out:xml][timeout:12];node(" +
                       matched.group(1) + ");out body;"}))
        try:
            body = fetch(overpass_url, cache)
        except (ValueError, OSError, TimeoutError) as exc:
            raise ValueError(
                "Unlisted official source: OSM and read-only Overpass unavailable"
            ) from exc
    require(body is not None, "OSM feature not independently fetched")
    require(isinstance(body, str) and len(body) <= probe.MAX_BYTES
            and "<!DOCTYPE" not in body.upper()
            and "<!ENTITY" not in body.upper(), "OSM answer invalid")
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as exc:
        raise ValueError("Unlisted official source: malformed OSM XML") from exc
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



def address_identity(venue, event_url, fetch, cache):
    """Authenticate existing published venue by exact BAN/OSM + HTTPS website.

    All external geography requests use fixed government/OSM origins.
    Neither a discovery claim nor the venue's historical geoSource hostname
    is trusted as proof of the currently attributed official event website.
    """
    import independent_named_site_geo as named_geo
    import venue_address_osm_source as address_osm
    require(address_osm.eligible_address(venue),
            "published venue has no exact geocodable street address")

    def bounded(url, limit):
        response = fetch(url, cache)
        require(isinstance(response, str) and
                0 < len(response) <= min(limit, probe.MAX_BYTES),
                "independent French address or OSM proof unavailable")
        return response, url

    # The publisher enforces government score >= 0.89 and exact street,
    # municipality and postcode, then a single matching named OSM point/way.
    feature, lat, lon, precision = named_geo.verify(venue, bounded)
    require(precision in {"named-site-point", "named-site-area"},
            "independent OSM feature is not a physical named location")
    try:
        distance = _distance_meters(
            lat, lon, float(venue["latitude"]), float(venue["longitude"]))
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        raise ValueError(
            "Unlisted official source: published venue has no map coordinates") from exc
    require(distance <= MAX_DISTANCE,
            "published venue map pin differs from independently named site")

    # Re-fetch the exact named OSM feature and its own website tags.
    homepage, independently_named = address_osm.website_from_address(
        venue, fetch=fetch, cache=cache)
    require(independently_named == feature,
            "independent named OSM feature changed across fresh checks")
    require(origin_match(event_url, homepage),
            "named OSM site does not attribute the event's HTTPS domain")
    return feature, homepage


def individual_event_nodes(html, *, accept_generic=False):
    """Read isolated official event facts; never borrow fields from other cards.

    Only the independently OSM-attributed source-unique profile may use
    generic schema.org Event or visible HTML microdata. If JSON-LD already
    declares an Event, bad or contradictory structured claims must not be
    masked by falling back to another HTML representation.
    """
    types = {"MusicEvent", "Event"} if accept_generic else {"MusicEvent"}
    nodes = [n for n in discover.read_ld(html)
             if isinstance(n, dict)
             and bridge._event_types(n.get("@type")) & types]
    if accept_generic and not nodes:
        import event_site_microdata
        nodes = event_site_microdata.read_microdata_events(html)
    return nodes


def _event(raw, event, venue, artists, *, accept_generic=False):
    """Verify one complete first-party concert event; never join evidence."""
    types = bridge._event_types(raw.get("@type")) if isinstance(raw, dict) else set()
    require("MusicEvent" in types or (accept_generic and "Event" in types),
            "first-party music event schema required")
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
    is_address = proof.get("proofType") == OSM_ADDRESS_PROFILE
    required_fields = (OSM_ADDRESS_PROOF_FIELDS if is_address else
                       OSM_SINGLE_PROOF_FIELDS if is_single_osm else
                       PROOF_FIELDS)
    require(set(proof) == required_fields,
            "wrong first-party source evidence fields")
    require(proof["url"] == event.get("officialUrl")
            and proof["proofType"] in {
                PROFILE, OSM_SINGLE_PROFILE, OSM_ADDRESS_PROFILE}
            and proof["checkedAt"] == approval.get("reviewedAt")
            and proof["checkedFields"] == (
                ADDRESS_CHECKED if is_address else CHECKED)
            and (proof["publishedVenueGeoSource"] == venue.get("geoSource")
                 if is_address else
                 proof["namedOsmUrl"] == venue.get("geoSource")),
            "first-party source evidence differs")
    origin = url_host(event["officialUrl"])
    witness = proof.get("corroboratingEventUrl")
    if not (is_single_osm or is_address):
        witness_host = url_host(witness)
        require(cross.domain(witness_host) != cross.domain(origin),
                "cross-domain witness is controlled by the same source apex")
    cache = {}
    # Verify named public OSM feature AND its website attribution on each
    # prospective publication. This also detects later ownership changes.
    if is_address:
        feature, homepage = address_identity(
            venue, event["officialUrl"], fetch, cache)
        require(feature == proof["namedOsmUrl"]
                and homepage == proof["sourceWebsite"],
                "fresh named-site OSM identity or official website changed")
    else:
        osm_identity(venue, event["officialUrl"], fetch, cache)
    html = fetch(event["officialUrl"], cache)
    require(isinstance(html, str) and
            100 <= len(html) <= probe.MAX_BYTES,
            "individual first-party HTML missing")
    events = individual_event_nodes(
        html, accept_generic=(is_single_osm or is_address))
    valid = []
    for raw in events:
        try:
            valid.append(_event(raw, event, venue, resolved,
                                accept_generic=(is_single_osm or is_address)))
        except (ValueError, KeyError, TypeError):
            continue
    require(len(valid) == 1, "no unique exact first-party MusicEvent")
    names, genres = valid[0]
    require(names == proof["officialArtistNames"]
            and genres == proof["officialGenreLabels"],
            "independent live event differs from signed first-party proof")
    if not (is_single_osm or is_address):
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
