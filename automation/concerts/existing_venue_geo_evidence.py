"""Read-only generic evidence for correcting existing municipal-centroid pins.

A published concert supplies an identity anchor, not new publishing authority.
Read its individual official MusicEvent/ Event address, verify the exact French
postal address and independently named OSM object, and bind the event origin
to the known official source or an independently attributed OSM website.
This never edits the catalogue or produces a signed approval.
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import discover
import independent_named_site_geo as geo
import official_rss_jsonld_bridge as bridge
import official_venue_single_source as official
import source_admission_intake as intake
import source_evidence_probe as probe
import triage
import venue_address_osm_source as address_source

SCHEMA = "grossesondes.concert.existing-venue-geo-evidence.v1"


def require(ok, message):
    if not ok:
        raise ValueError("Existing venue geo evidence: " + message)


def eligible(venue):
    # A building centroid with an explicit independently named location is
    # not the same as a municipality centroid. Do not redo accurate pins.
    precision = triage.words(venue.get("geoPrecision"))
    return ("centre de commune" in precision or
            precision == "salle a recontroler")


def extract_address(html, event, venue):
    """Only an unambiguous, exact, dated event and its own physical Place."""
    url = event.get("officialUrl")
    require(isinstance(url, str) and bool(intake.valid_https(url)),
            "invalid published event URL")
    require(event.get("venueId") == venue.get("id")
            and event.get("sourceType") == "salle", "event/venue mismatch")
    require(isinstance(html, str) and 0 < len(html) <= probe.MAX_BYTES,
            "invalid event response")
    nodes = [n for n in discover.read_ld(html) if isinstance(n, dict)
             and bridge._event_types(n.get("@type")) & {"MusicEvent", "Event"}]
    require(len(nodes) == 1, "single structured event required")
    node = nodes[0]
    raw_url = node.get("url")
    require(isinstance(raw_url, str) and raw_url.rstrip("/") == url.rstrip("/"),
            "structured event URL differs from published source")
    raw_day = node.get("startDate")
    require(isinstance(raw_day, str) and re.fullmatch(
        r"20\d{2}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})?)?", raw_day)
        and dt.date.fromisoformat(raw_day[:10]).isoformat() == event.get("date"),
        "structured event day differs from published date")
    place = node.get("location")
    require(isinstance(place, dict)
            and bridge._event_types(place.get("@type")) & {"Place", "MusicVenue"}
            and triage.words(place.get("name")) == triage.words(venue.get("name"))
            and bool(triage.words(venue.get("name"))), "named place mismatch")
    address = place.get("address")
    require(isinstance(address, dict)
            and "PostalAddress" in bridge._event_types(address.get("@type")),
            "structured postal address missing")
    street, postcode = address.get("streetAddress"), address.get("postalCode")
    require(isinstance(street, str) and 6 <= len(street.strip()) <= 160
            and isinstance(postcode, str) and re.fullmatch(r"\d{5}", postcode)
            and triage.words(address.get("addressLocality")) == triage.words(venue.get("city"))
            and bool(triage.words(venue.get("city"))), "exact postal identity missing")
    country = address.get("addressCountry")
    require(isinstance(country, str) and country.casefold() in {"fr", "fra", "france"},
            "French postal country not established")
    # Existing published regional identity is retained, never inferred from
    # a search result or changed by the event page.
    site = dict(venue, address=street.strip(), postalCode=postcode)
    require(address_source.eligible_address(site), "non-geocodable postal address")
    return site


def verify(event, venue, *, fetch=probe.safe_fetch, cache=None):
    """Return evidence only, with no signature or catalogue write permission."""
    require(isinstance(event, dict) and isinstance(venue, dict)
            and eligible(venue), "only municipal-centroid/recheck pins eligible")
    url = event.get("officialUrl")
    require(isinstance(url, str) and bool(intake.valid_https(url)),
            "unsafe event URL")
    cache = {} if cache is None else cache
    site = extract_address(fetch(url, cache), event, venue)

    def bounded(endpoint, limit):
        body = fetch(endpoint, cache)
        require(isinstance(body, str) and 0 < len(body) <= min(limit, probe.MAX_BYTES),
                "independent geographical evidence unavailable")
        return body, endpoint

    feature, lat, lon, precision = geo.verify(site, bounded)
    require(precision in {"named-site-point", "named-site-area"},
            "no independent named physical site")
    # The existing source manifest is only one provenance route. Unlisted
    # venues may use the independently matched OSM website, without a PR.
    homepage = official.official_origin(venue, url)
    if homepage is None:
        homepage, independently_named = address_source.website_from_address(
            site, fetch=fetch, cache=cache)
        require(independently_named == feature, "independent site changed")
    a, b = intake.valid_https(url), intake.valid_https(homepage)
    require(bool(a and b) and a.removeprefix("www.") == b.removeprefix("www."),
            "event domain not independently attributable to venue")
    patch = {"address": site["address"], "postalCode": site["postalCode"],
             "latitude": lat, "longitude": lon, "geoSource": feature,
             "geoPrecision": precision}
    return {"schema": SCHEMA, "venueId": venue["id"], "eventId": event["id"],
            "eventDate": event["date"], "officialUrl": url,
            "officialVenueSourceUrl": homepage, "originalVenue": dict(venue),
            "venuePatch": patch, "publicationAllowed": False,
            "publisherAuthorityGranted": False}
