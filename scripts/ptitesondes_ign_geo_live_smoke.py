#!/usr/bin/env python3
"""Read-only live IGN recheck of four independently documented venues.

No GitHub token, private intake, catalogues, publisher or event-level admission.
Reports only aggregate counts; errors never expose URLs or private leads.
"""
import json
from pathlib import Path
import sys
from urllib.request import Request, build_opener, HTTPRedirectHandler

from ptitesondes_independent_ign_venue_recheck import (
    reviewed_search, redacted_report,
)
from venue_registry import VENUES

TARGETS = (
    ("Villeurbanne", "Studio 24"),
    ("Rouen", "Bibliothèque Aretha-Franklin"),
    ("Rouen", "Bibliothèque Simone de Beauvoir"),
    ("Roubaix", "Médiathèque de Roubaix - La Grand-Plage"),
)
MAX_BYTES = 120_000


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def live_response(venue, opener=None):
    if reviewed_search(venue) is None:
        raise ValueError("untrusted_reviewed_geo_source")
    url = venue["geo_source"]
    fetch = opener or build_opener(NoRedirect()).open
    with fetch(Request(url, headers={
        "User-Agent": "PtitesOndesIndependentGeo/1.0 (readonly)",
        "Accept": "application/json",
    }), timeout=18) as response:
        if response.status != 200 or response.geturl() != url:
            raise ValueError("external_geo_source_not_exact")
        body = response.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValueError("geo_response_too_large")
    return json.loads(body)


def main():
    from ptitesondes_independent_ign_venue_recheck import recheck_ign
    matched = failures = 0
    for city, name in TARGETS:
        entries = [v for v in VENUES
                   if v["city"] == city and name in v.get("aliases", [])]
        if len(entries) != 1:
            failures += 1
            continue
        try:
            response = live_response(entries[0])
            ok, _ = recheck_ign(entries[0], response)
            matched += int(ok)
            failures += int(not ok)
        except (OSError, ValueError, TypeError, KeyError, TimeoutError):
            failures += 1
    # No individual source/venue/response data appears in public CI output.
    result = {
        "schema": "ptitesondes.independent_ign_venue_live_smoke.v1",
        "mode": "four_curated_buildings_external_read_only_no_admission",
        "target_buildings": len(TARGETS),
        "independently_reconfirmed": matched,
        "held_or_unavailable": failures,
        "private_candidates_read": 0,
        "public_writes": 0,
        "approved_events": 0,
    }
    if matched + failures != len(TARGETS):
        raise AssertionError("incomplete_check")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
