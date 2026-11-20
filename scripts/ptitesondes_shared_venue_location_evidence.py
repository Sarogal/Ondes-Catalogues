#!/usr/bin/env python3
"""Private-only, in-memory geographic evidence shared by Sorties and Lieux.

Only a DILA-confirmed municipal venue page + exact independent BAN geocode
may mint a proof. Caller-supplied dicts and flags can NEVER mint a proof.
This is a location contract, not approval of an event or permission to publish.
"""
from datetime import date
import math

from proof import meters, norm
from ptitesondes_dila_municipal_domains import approved_municipal_page_host
from ptitesondes_generic_venue_official_geocode import extract_official_address
from ptitesondes_generic_venue_ign_corroboration import (
    MIN_SCORE, MAX_FEATURES, MAX_DISTANCE_M,
)

MAX_AGE_DAYS = 30
_SEAL = object()


class VenueLocationProof:
    """Unserializable-in-practice, factory-only private geographic result."""
    __slots__ = ("city", "venue", "lat", "lng", "checked_on",
                 "official_page", "method", "_seal")

    def __init__(self, city, venue, lat, lng, checked_on, official_page, seal):
        if seal is not _SEAL:
            raise ValueError("venue_proof_must_be_minted_by_verifier")
        self.city, self.venue = city, venue
        self.lat, self.lng = lat, lng
        self.checked_on = checked_on
        self.official_page = official_page
        self.method = "dila_official_page_plus_exact_ban"
        self._seal = seal

    def __setattr__(self, name, value):
        if hasattr(self, "_seal"):
            raise AttributeError("venue_proof_is_immutable")
        object.__setattr__(self, name, value)

    def __delattr__(self, name):
        raise AttributeError("venue_proof_is_immutable")


def _coordinates(value):
    if (not isinstance(value, (list, tuple)) or len(value) != 2
            or any(type(x) not in (int, float) or not math.isfinite(x)
                   for x in value)
            or not -90 <= value[0] <= 90 or not -180 <= value[1] <= 180):
        return None
    return tuple(value)


def mint_private_location_proof(group, directory, page_url, html,
                                ign_fetch, checked_on, source_center=None):
    """Corroborate the place once and reuse it across *independent* sessions.

    source_center is optional for permanent places. When supplied by an
    untrusted event index, it MUST agree with the independent BAN point.
    directory and HTML must be read with separately authenticated readers.
    No network calls are made by this function other than supplied ign_fetch.
    """
    if (not isinstance(group, dict) or type(checked_on) is not date
            or not callable(ign_fetch) or not isinstance(page_url, str)
            or approved_municipal_page_host(
                page_url, group.get("city"), directory) is None):
        return None
    if source_center is not None and _coordinates(source_center) is None:
        return None
    candidate = extract_official_address(group, html)
    if candidate is None:
        return None
    try:
        result = ign_fetch(candidate)
    except (OSError, ValueError, TypeError, KeyError, TimeoutError):
        return None
    if not isinstance(result, dict) or result.get("type") != "FeatureCollection":
        return None
    features = result.get("features")
    if not isinstance(features, list) or len(features) > MAX_FEATURES:
        return None
    matched = []
    for feature in features:
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            continue
        prop, geometry = feature.get("properties"), feature.get("geometry")
        if not isinstance(prop, dict) or not isinstance(geometry, dict):
            continue
        score = prop.get("score")
        if (prop.get("type") != "housenumber"
                or prop.get("postcode") != candidate["postcode"]
                or norm(prop.get("housenumber")) != norm(candidate["housenumber"])
                or norm(prop.get("city")) != norm(candidate["city"])
                or norm(prop.get("label")) != norm(candidate["address_query"])
                or type(score) not in (float, int)
                or not math.isfinite(score)
                or not MIN_SCORE <= score <= 1):
            continue
        raw_point = geometry.get("coordinates")
        if geometry.get("type") != "Point" or _coordinates(
                (raw_point[1], raw_point[0])
                if isinstance(raw_point, list) and len(raw_point) == 2
                else None) is None:
            continue
        point = (raw_point[1], raw_point[0])
        if (source_center is not None
                and meters(point, source_center) > MAX_DISTANCE_M):
            continue
        if ("official_coordinates_hint" in candidate
                and meters(point, candidate["official_coordinates_hint"])
                > MAX_DISTANCE_M):
            continue
        matched.append(point)
    if len(matched) != 1:
        return None
    if (norm(group.get("city")) != norm(candidate["city"])
            or not norm(group.get("venue"))):
        return None
    return VenueLocationProof(
        group["city"], group["venue"], *matched[0], checked_on, page_url,
        _SEAL)


def location_from_proof(proof, city, venue, checked_on, source_point=None):
    """Return a registry-compatible location without approving any session.

    Fail closed for forged/unsealed, mismatched or stale proofs. Coordinates
    provided by a source must agree with the independently proven BAN point.
    """
    if (not isinstance(proof, VenueLocationProof)
            or proof._seal is not _SEAL
            or type(checked_on) is not date
            or type(proof.checked_on) is not date
            or not 0 <= (checked_on - proof.checked_on).days <= MAX_AGE_DAYS
            or not norm(city) or not norm(venue)
            or norm(city) != norm(proof.city)
            or norm(venue) != norm(proof.venue)):
        return None
    if source_point is not None:
        point = _coordinates(source_point)
        if point is None or meters(point, (proof.lat, proof.lng)) > MAX_DISTANCE_M:
            return None
    return {"city": proof.city, "aliases": [proof.venue],
            "lat": proof.lat, "lng": proof.lng,
            "official": proof.official_page,
            "geo_source": "IGN/BAN verified exact housenumber"}


__all__ = ["VenueLocationProof", "mint_private_location_proof",
           "location_from_proof"]
