"""Open-world, independent venue-website and named-OSM source proof.

An OA-supplied website alone is never official authority. A newly encountered
website is eligible only when a separately retrieved exact-name OSM place
attributes that SAME host to the venue, the OSM point agrees with the exact
live OA point, and the actual page independently repeats all future sessions.
A website tag is evidence of attribution, not a license or event approval.
No host, town, agenda, performer or venue allowlist is used.
"""
from datetime import date
from urllib.parse import urlsplit

from proof import norm
from ptitesondes_delegated_source_authority import _url_host
from ptitesondes_generic_venue_osm_preflight import osm_hints
from ptitesondes_shared_venue_location_evidence import (
    VenueLocationProof, _SEAL, _coordinates, location_from_proof,
)

METHOD = "named_osm_venue_website_plus_live_oa"


def _osm_website_host(url):
    """Read website/contact:website tags, never follow an untrusted URL."""
    if not isinstance(url, str) or len(url) > 600:
        return None
    try:
        parsed = urlsplit(url)
        if (parsed.scheme not in ("http", "https") or not parsed.hostname
                or parsed.username or parsed.password or parsed.query
                or parsed.fragment or parsed.port not in (None, 80, 443)):
            return None
        # The ordinary organizer-domain validator rejects private addresses,
        # platforms and lookalikes, and requires a real HTTPS publication URL.
        return _url_host("https://" + parsed.hostname + "/venue")
    except (TypeError, ValueError):
        return None


def mint_named_osm_venue_website_proof(
        group, official_event_url, source_center, osm_response, checked_on):
    """Only one exact OSM venue with an independently attributed website.

    A guessed street centroid, approximate locality, duplicate named venue,
    mismatching website or contradictory address fails closed. This factory
    never reads caller-supplied GPS from a dossier: the caller must pass the
    fresh, UID-bound OpenAgenda event's location.
    """
    if (type(checked_on) is not date or not isinstance(group, dict)
            or not norm(group.get("city")) or not norm(group.get("venue"))
            or group.get("key") != [norm(group["city"]), norm(group["venue"])]
            or _coordinates(source_center) is None
            or not isinstance(official_event_url, str)):
        return None
    host = _url_host(official_event_url)
    if host is None:
        return None
    try:
        candidates = osm_hints(group, source_center, osm_response)
        if len(candidates) != 1:
            return None
        hint = candidates[0]
        typ, raw_id = hint["osm_object_hint"].split("/")
        oid = int(raw_id)
        items = [item for item in osm_response["elements"]
                 if (isinstance(item, dict) and item.get("type") == typ
                     and item.get("id") == oid)]
        if len(items) != 1:
            return None
        tags = items[0].get("tags")
        if not isinstance(tags, dict):
            return None
        if tags.get("addr:country") and norm(tags["addr:country"]) not in (
                "fr", "france"):
            return None
        websites = [tags[name] for name in ("website", "contact:website")
                    if name in tags]
        if not websites:
            return None
        hosts = [_osm_website_host(url) for url in websites]
        if any(value is None for value in hosts):
            return None
        if any(value.removeprefix("www.") != host.removeprefix("www.")
               for value in hosts):
            return None
        lat, lng = hint["lat_unverified"], hint["lng_unverified"]
        return VenueLocationProof(
            group["city"], group["venue"], lat, lng, checked_on,
            official_event_url, _SEAL, method=METHOD)
    except (KeyError, IndexError, ValueError, TypeError, OverflowError):
        return None


def verified_named_osm_venue_website(
        proof, official_event_url, city, venue, checked_on):
    """Authenticate only the exact same publisher-minted venue/site proof."""
    return bool(
        type(proof) is VenueLocationProof
        and proof.method == METHOD
        and proof.official_page == official_event_url
        and _url_host(official_event_url) is not None
        and location_from_proof(proof, city, venue, checked_on) is not None
    )


__all__ = [
    "mint_named_osm_venue_website_proof",
    "verified_named_osm_venue_website",
]
