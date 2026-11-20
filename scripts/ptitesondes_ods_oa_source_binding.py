#!/usr/bin/env python3
"""Read-only immutable UID binding for ODS-syndicated OpenAgenda venues.

A human-slug OpenAgenda event URL is a DISCOVERY LINK, not an immutable ID.
Only the ODS record fetched by its immutable UID may bind that URL to the
private lead. Direct OpenAgenda v2 must then independently confirm the UID,
venue, municipality and official website in the calling reader. No publisher.
"""
import math
import re
from urllib.parse import urlsplit

from proof import norm

UID = re.compile(r"[0-9]{1,12}\Z")
SLUG = re.compile(r"[a-z0-9][a-z0-9-]{0,100}\Z")
EVENT_SLUG = re.compile(r"[a-z0-9][a-z0-9-]{0,180}\Z")


def ods_source_parts(url):
    """Extract agenda slug from a pinned human-slug event URL, without UID."""
    if not isinstance(url, str) or not 1 <= len(url) <= 700:
        return None
    try:
        p = urlsplit(url)
        if (p.scheme != "https" or p.hostname != "openagenda.com"
                or p.username or p.password or p.port not in (None, 443)
                or p.query or p.fragment):
            return None
        parts = p.path.strip("/").split("/")
        if len(parts) == 4 and parts[0] in ("fr", "en"):
            parts = parts[1:]
        if (len(parts) != 3 or parts[1] != "events"
                or SLUG.fullmatch(parts[0]) is None
                or EVENT_SLUG.fullmatch(parts[2]) is None):
            return None
        return parts[0]
    except ValueError:
        return None


def ods_immutable_source_match(group, uid, source_url, record):
    """Require exact ODS URL+UID+place+geo on a unique UID GET record.

    The caller must use an independent exact-UID ODS reader, never search by
    title or accept a row embedded in OpenAgenda event content. This is
    sufficient to admit an OpenAgenda agenda-URL as a source candidate only.
    """
    if (not isinstance(group, dict) or not isinstance(record, dict)
            or not isinstance(uid, str) or UID.fullmatch(uid) is None
            or ods_source_parts(source_url) is None
            or str(record.get("uid")) != uid
            or record.get("canonicalurl") != source_url
            or norm(record.get("location_name")) != norm(group.get("venue"))
            or norm(record.get("location_city")) != norm(group.get("city"))
            or record.get("location_countrycode") not in (
                "FR", "GP", "MQ", "GF", "RE", "YT")
            or type(record.get("status")) not in (int,)
            or record["status"] != 1):
        return False
    point = record.get("location_coordinates")
    if not isinstance(point, dict):
        return False
    try:
        lat, lon = float(point["lat"]), float(point["lon"])
    except (ValueError, KeyError, TypeError, OverflowError):
        return False
    return (math.isfinite(lat) and math.isfinite(lon)
            and -90 <= lat <= 90 and -180 <= lon <= 180)
