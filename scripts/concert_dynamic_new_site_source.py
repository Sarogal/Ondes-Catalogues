#!/usr/bin/env python3
"""Independent live proof for an unlisted concert-origin domain AND a new site.

No committed venue/domain/organizer/artist allowlist determines authority.
The published venue which ANNOUNCES the event is an identity hint: fresh OSM
(or exact government-address + OSM) must independently attribute its HTTPS
site. The concert is elsewhere, at a NEW named French physical site whose
own address and geometry are checked separately. A second, independent event
domain must confirm the lead artist/date/new place before this proof can pass.

This module does NOT sign an approval, persist private ledgers, or publish.
The publisher's atomic event+site contract is a separate, required gate.
"""
from __future__ import annotations

import datetime as dt
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "automation/concerts"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIR))

import event_site_pair_recheck as sites
import source_cross_domain_corroboration as cross
import source_cross_domain_live_recheck as witnesses
import source_admission_intake as intake
import source_evidence_probe as probe
import venue_osm_self_discovery as origin_discovery
from scripts import concert_event_site_contract as contract

PROFILE = "dynamic-new-event-site-first-party-v1"
FIELDS = frozenset({
    "url", "proofType", "checkedAt", "checkedFields", "originVenueId",
    "originVenueOsmUrl", "corroboratingEventUrl",
    "officialArtistNames", "officialGenreLabels",
})
CHECKED = [
    "artists", "date", "venue", "genre", "sourceWebsite",
    "independentLocation", "independentEventWitness",
]


def require(ok, msg):
    if not ok:
        raise ValueError("Open-origin new concert site: " + msg)


def domain(value):
    host = intake.valid_https(value)
    require(isinstance(host, str), "unsafe HTTPS URL")
    return cross.domain(host)


def verify(event_approval, site_approval, published_venues, published_artists,
           today, *, fetch=probe.safe_fetch):
    """Fully verify an EVENT-SCOPED signed proof with FRESH independent reads.

    fetch(url, pinned_cache) -> text. Production uses DNS-pinned HTTPS,
    no redirects and robots.txt, including all geo and witness reads.
    Returned True is ONLY verification of the evidence, not a trust grant.
    """
    require(isinstance(today, dt.date) and not isinstance(today, dt.datetime),
            "invalid review date")
    require(isinstance(event_approval, dict) and isinstance(site_approval, dict)
            and event_approval.get("reviewDecision") == "approved"
            and event_approval.get("reviewedBy") == "independent-official-verifier"
            and site_approval.get("reviewDecision") == "approved"
            and site_approval.get("reviewedBy") == "independent-official-verifier"
            and isinstance(published_venues, dict)
            and isinstance(published_artists, dict),
            "untrusted approval or published anchors")
    event = event_approval.get("event")
    venue = site_approval.get("venue")
    binding = site_approval.get("eventBinding")
    require(isinstance(event, dict) and isinstance(venue, dict)
            and isinstance(binding, dict)
            and site_approval.get("venueKind") == contract.PROFILE,
            "unknown event or location evidence")
    day = event.get("date")
    try:
        checked = dt.date.fromisoformat(event_approval.get("reviewedAt"))
        show_day = dt.date.fromisoformat(day)
    except (TypeError, ValueError):
        raise ValueError("Open-origin new concert site: invalid signed date")
    require(site_approval.get("reviewedAt") == checked.isoformat()
            and 0 <= (today - checked).days <= 7
            and show_day >= today
            and event.get("status") == "confirmed"
            and event.get("time") is None
            and event.get("sourceType") == "organisateur",
            "stale or mismatched confirmed concert")
    url = event.get("officialUrl")
    require(isinstance(url, str) and intake.valid_https(url) is not None
            and urlsplit(url).path.strip("/") and not urlsplit(url).query
            and not urlsplit(url).fragment
            and binding.get("eventId") == event.get("id")
            and binding.get("eventDate") == day
            and binding.get("eventOfficialUrl") == url
            and binding.get("authorityArtistId") is None
            and binding.get("authoritySourceUrl") is not None
            and event.get("venueId") == venue.get("id")
            and venue.get("id") == contract.site_id(
                venue.get("name", ""),venue.get("city", ""),
                venue.get("geoSource", "")),
            "concert and site binding differs")
    proofs = event_approval.get("officialEvidence")
    require(isinstance(proofs, list) and len(proofs) == 2
            and isinstance(proofs[0], dict)
            and proofs[0].get("proofType") == "official-organizer-or-venue"
            and proofs[0].get("url") == url
            and proofs[0].get("checkedAt") == checked.isoformat()
            and {"artists", "date", "venue", "genre"}.issubset(
                set(proofs[0].get("checkedFields") or []))
            and isinstance(proofs[1], dict)
            and set(proofs[1]) == FIELDS,
            "official event or dynamic provenance proof missing")
    proof = proofs[1]
    require(proof.get("proofType") == PROFILE
            and proof.get("url") == url
            and proof.get("checkedAt") == checked.isoformat()
            and proof.get("checkedFields") == CHECKED
            and isinstance(proof.get("officialArtistNames"), list)
            and 1 <= len(proof["officialArtistNames"]) <= 100
            and all(isinstance(n, str) and n.strip()
                    for n in proof["officialArtistNames"])
            and isinstance(proof.get("officialGenreLabels"), list)
            and contract.relevant_genres(proof["officialGenreLabels"]),
            "specific signed first-party genre and full bill absent")
    anchor_id = proof.get("originVenueId")
    anchor = published_venues.get(anchor_id)
    require(isinstance(anchor, dict) and anchor.get("id") == anchor_id
            and anchor_id != venue.get("id")
            and proof.get("originVenueOsmUrl") == anchor.get("geoSource")
            and isinstance(proof.get("corroboratingEventUrl"), str),
            "announcing venue not a distinct independently published identity")
    cache = {}
    home = origin_discovery.official_source(anchor, fetch, cache)
    require(isinstance(home, str)
            and domain(home) == domain(url)
            and domain(binding["authoritySourceUrl"]) == domain(url)
            and binding["authoritySourceUrl"] == home,
            "OSM/BAN does not own the first-party event domain")
    witness_url = proof["corroboratingEventUrl"]
    require(domain(witness_url) != domain(url)
            and witness_url != url
            and urlsplit(witness_url).path.strip("/")
            and not urlsplit(witness_url).query
            and not urlsplit(witness_url).fragment,
            "event corroboration is not independent")
    html = fetch(url, cache)
    require(isinstance(html, str) and 100 <= len(html) <= probe.MAX_BYTES,
            "fresh individual first-party event page missing")
    lead = {
        "date": day, "name": event.get("title"),
        "leadArtist": proof["officialArtistNames"][0],
        "venue": venue.get("name"), "city": venue.get("city"),
    }
    _raw, names, _unnamed, genres, site = sites._official_event(
        lead, html, url, today)
    require(names == proof["officialArtistNames"]
            and genres == proof["officialGenreLabels"]
            and event.get("genres") == genres
            and event.get("title") == " + ".join(names),
            "fresh named bill or individual genre differs from signed event")
    ids, fresh = sites._artists(
        names, {"artists": list(published_artists.values())})
    require(event.get("artistIds") == ids
            and event_approval.get("newArtists", []) == fresh,
            "event artist IDs or newly discovered band identities differ")
    require(all(site.get(k) == venue.get(k)
                for k in ("name", "city", "address", "postalCode",
                          "department", "region")),
            "first-party new event location differs from approved location")

    def secure_geo(url_, cap):
        require(isinstance(cap, int) and 0 < cap <= 400_000,
                "geography budget invalid")
        body = fetch(url_, cache)
        require(isinstance(body, str) and len(body) <= cap,
                "geography response unavailable or oversized")
        return body, url_

    geo_url, lat, lon, precision = sites.corroborate_physical_site(
        site, secure_geo)
    require(geo_url == venue.get("geoSource")
            and lat == venue.get("latitude")
            and lon == venue.get("longitude")
            and precision == venue.get("geoPrecision"),
            "independently named OSM geometry differs from signed new site")
    other = witnesses.event_page_witness(
        fetch(witness_url, cache), url=witness_url,
        date=day, lead_artist=names[0],
        city=venue["city"], venue=venue["name"])
    require(names[0] in other["names"],
            "independent witness does not confirm the lead artist")
    return True
