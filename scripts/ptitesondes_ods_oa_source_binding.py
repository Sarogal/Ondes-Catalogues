#!/usr/bin/env python3
"""Read-only immutable UID binding for ODS-syndicated OpenAgenda venues.

A human-slug OpenAgenda event URL is a DISCOVERY LINK, not an immutable ID.
Only the ODS record fetched by its immutable UID may bind that URL to the
private lead. Direct OpenAgenda v2 must then independently confirm the UID,
venue, municipality and official website in the calling reader. No publisher.
"""
import math
import json
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
                "FR", "GP", "MQ", "GF", "RE", "YT")):
        return False
    state = record.get("status")
    if isinstance(state, str):
        if len(state) > 1500:
            return False
        try:
            state = json.loads(state)
        except (ValueError, TypeError):
            return False
    # The ODS mirror serializes "status" as a JSON string with an
    # embedded ID (real 2026-11-20 format). Never infer it from label.
    if not isinstance(state, dict) or type(state.get("id")) is not int or state["id"] != 1:
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


def ods_origin_agenda_uid(record):
    """Read an immutable ODS agenda UID; never infer it from its title."""
    if not isinstance(record, dict):
        return None
    raw = record.get("originagenda_uid")
    if type(raw) is int:
        value = raw
    elif (type(raw) is str
          and re.fullmatch(r"[1-9][0-9]{0,11}", raw) is not None):
        value = int(raw)
    else:
        return None
    return value if 0 < value < 10**12 else None


def independently_confirm_ods_agenda(record, slug, reader, public_read_key):
    """Corroborate ODS agenda UID+slug with one direct OpenAgenda API read.

    This permits venue DISCOVERY beyond a frozen curated list, but does not
    establish organizer ownership, rights, event trust or permission to
    publish. Returns None on ANY unknown or conflicting metadata.
    """
    uid = ods_origin_agenda_uid(record)
    if (uid is None or not isinstance(slug, str)
            or SLUG.fullmatch(slug) is None
            or not callable(reader)
            or not isinstance(public_read_key, str)
            or not public_read_key):
        return None
    try:
        doc = reader(uid, public_read_key)
    except (ValueError, OSError, TypeError, KeyError, TimeoutError):
        return None
    if (not isinstance(doc, dict)
            or str(doc.get("uid")) != str(uid)
            or doc.get("slug") != slug):
        return None
    return uid
