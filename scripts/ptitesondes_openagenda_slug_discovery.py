#!/usr/bin/env python3
"""Discover a previously UNCONFIGURED OpenAgenda agenda via its exact public slug.

This is evidence of a public API UID/slug pairing, not a curator decision or
proof that an institution controls that agenda. The publisher and venue
admission paths cannot consume the result as permission to publish.
No user-chosen endpoints, redirects, secrets, writes, or unbounded searches.
"""
import json
from urllib.parse import urlencode
from urllib.request import Request, build_opener

from ptitesondes_openagenda_v2_direct_evidence import (
    API_ORIGIN, SLUG, _uid, _valid_public_read_key, _NoRedirect,
)

SCHEMA = "ptitesondes.oa2.unconfigured_agenda_slug_discovery.v1"
MAX_BYTES = 150_000


def lookup_agenda_by_slug(slug, public_read_key, *, opener=None):
    """Exact GET /v2/agendas?slug=..., then require exactly one UID.

    Official=1, a self-asserted institutional URL and the appearance of an
    official-looking agenda do NOT establish its ownership or publication
    rights. The result is only an isolated source for subsequent corroboration.
    """
    if (type(slug) is not str or SLUG.fullmatch(slug) is None
            or not _valid_public_read_key(public_read_key)):
        raise ValueError("invalid_slug_or_nonpublic_read_key")
    url = API_ORIGIN + "/v2/agendas?" + urlencode({"slug": slug, "size": 2})
    request = Request(url, headers={
        "key": public_read_key,
        "Accept": "application/json",
        "User-Agent": "PtitesOndesUnconfiguredAgendaResearch/1.0",
    })
    fetch = opener or build_opener(_NoRedirect()).open
    try:
        with fetch(request, timeout=18) as response:
            if response.status != 200 or response.geturl() != url:
                raise ValueError("unexpected_search_endpoint_or_status")
            payload = response.read(MAX_BYTES + 1)
    except (OSError, TimeoutError):
        raise ValueError("public_agenda_search_unavailable") from None
    if len(payload) > MAX_BYTES:
        raise ValueError("public_agenda_search_oversized")
    try:
        result = json.loads(payload)
    except (ValueError, UnicodeDecodeError):
        raise ValueError("public_agenda_search_invalid_json") from None
    if (type(result) is not dict
            or type(result.get("total")) is not int
            or result["total"] != 1
            or type(result.get("agendas")) is not list
            or len(result["agendas"]) != 1):
        raise ValueError("public_agenda_search_not_unique")
    found = result["agendas"][0]
    if (type(found) is not dict
            or type(found.get("uid")) is not int
            or not _uid(found["uid"])
            or found.get("slug") != slug):
        raise ValueError("public_agenda_search_slug_uid_mismatch")
    return {
        "schema": SCHEMA,
        "uid": found["uid"], "slug": slug,
        "status": "public_uid_slug_only_independent_ownership_pending",
        "independent_ownership_verified": False,
        "organizer_verified": False,
        "rights_reviewed": False,
        "publication_ready": False,
        "approval_granted": False,
        "publisher_connected": False,
        "public_writes": 0,
    }


__all__ = ["lookup_agenda_by_slug", "SCHEMA"]
