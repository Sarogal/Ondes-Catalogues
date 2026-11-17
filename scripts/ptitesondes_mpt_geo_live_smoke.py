#!/usr/bin/env python3
"""One-shot public IGN geocoder recheck, no event IO or GitHub state writes.

Only aggregated counts are printed. Never print addresses, source URLs, raw
responses, or arbitrary HTTP exception strings into public Actions logs.
"""
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
import json

from ptitesondes_mpt_independent_geo_pilot import (
    reviewed_pilot_records, geo_review_report, validate_curated_registry,
)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def get_reviewed_geocoder(url):
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname != "data.geopf.fr"
            or parsed.path != "/geocodage/search"
            or parsed.username or parsed.password
            or parsed.port not in (None, 443) or parsed.fragment):
        raise ValueError("unsafe_geocoder_origin")
    request = Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "PtitesOndesIndependentGeoAudit/0.1 (no event publication)",
    })
    with build_opener(NoRedirect).open(request, timeout=12) as response:
        if response.geturl() != url:
            raise ValueError("redirect_unreviewed")
        if "application/json" not in response.headers.get(
                "Content-Type", "").lower():
            raise ValueError("unexpected_geo_content_type")
        raw = response.read(80_001)
        if len(raw) > 80_000:
            raise ValueError("oversized_geocoder_reply")
    return json.loads(raw.decode("utf-8"))


def check_live_geo(*, fetch=get_reviewed_geocoder):
    records = reviewed_pilot_records()
    if not validate_curated_registry(records):
        raise ValueError("unreviewed_pilot_registry")
    responses = {}
    for row in records:
        # URLs originate only in the fixed separately curated registry.
        responses[row["venue_key"]] = fetch(row["geo_source_url"])
    return geo_review_report(records, responses)


if __name__ == "__main__":
    try:
        report = check_live_geo()
        print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
        if report["held_for_external_geo_review"]:
            raise SystemExit("INDEPENDENT_GEO_HOLD")
    except (OSError, ValueError, TypeError, UnicodeError):
        raise SystemExit("INDEPENDENT_GEO_RECHECK_INCOMPLETE")
