#!/usr/bin/env python3
"""One-shot MPT Montpellier source smoke: bounded official reads, no publishing.

Never stores candidate details, names, URLs, raw HTML or private content.
Only aggregate counts go to GitHub Actions logs. No cron, secrets or write.
"""
from collections import Counter
from datetime import datetime
import json
import time
from urllib.request import Request, HTTPRedirectHandler, build_opener
from zoneinfo import ZoneInfo

from ptitesondes_mpt_listing_discovery import (
    LISTING_URL, MAX_HTML_BYTES, trusted_detail, discover_listing,
)
from ptitesondes_real_family_source_adapters import (
    _MptVisible, _mpt_reviewable_address_venue, DATE_FR, CHILD, BLOCKED,
    fold_accents, norm,
)

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def read_official(url):
    if url != LISTING_URL and not trusted_detail(url):
        raise ValueError("unsafe_mpt_source")
    request = Request(url, headers={
        "User-Agent": "PtitesOndesOutingsReadOnlyAudit/1.0",
        "Accept": "text/html",
    })
    with build_opener(NoRedirect).open(request, timeout=12) as r:
        if r.geturl() != url:
            raise ValueError("source_redirect_unreviewed")
        if "text/html" not in r.headers.get("Content-Type", "").lower():
            raise ValueError("source_not_html")
        body = r.read(MAX_HTML_BYTES + 1)
        if len(body) > MAX_HTML_BYTES:
            raise ValueError("page_too_large")
    return body.decode("utf-8", "replace")


def live_sample(today, *, list_get=read_official, detail_get=read_official):
    listing = list_get(LISTING_URL)
    requests = 0
    cues = Counter()
    def throttled(url):
        nonlocal requests
        if requests:
            time.sleep(0.2)
        requests += 1
        raw = detail_get(url)
        # Anonymous diagnostics only: no event titles, URLs or HTML in logs.
        parser = _MptVisible()
        parser.feed(raw)
        body = " ".join(parser.parts)
        visible = norm(body)
        flags = {
            "main_title_visible": bool(parser.heading),
            "family_signal_visible": bool(CHILD.search(visible)),
            "exact_date_time_visible": bool(DATE_FR.findall(
                fold_accents(body))),
            "street_address_confirmed": (
                _mpt_reviewable_address_venue(raw) is not None),
            "explicit_lieu_label": any(
                norm(s).startswith("lieu ") for s in parser.parts),
            "status_blocker_visible": bool(BLOCKED.search(visible)),
        }
        for label, enabled in flags.items():
            if enabled:
                cues[label] += 1
        return raw
    _, report = discover_listing(
        listing, today=today, detail_get=throttled, page_limit=24)
    report["live_sample"] = True
    report["remote_details_read_attempted"] = requests
    report["independent_diagnostic_counts_only"] = dict(sorted(cues.items()))
    return report


if __name__ == "__main__":
    try:
        today = datetime.now(ZoneInfo("Europe/Paris")).date()
        result = live_sample(today)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
        if result["held_unreadable_details"] > 0:
            raise SystemExit("LIVE_MPT_SOURCE_INCOMPLETE")
    except (OSError, UnicodeError, ValueError, TypeError):
        raise SystemExit("LIVE_MPT_SOURCE_HELD")
