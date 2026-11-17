#!/usr/bin/env python3
"""One-shot anonymous LIVE smoke of two real city feeds; read-only by design.

Not scheduled or called by any publisher. Never prints candidate titles,
URLs, addresses, raw HTML/JSON or city feed content. Failures are reported
by reason; they never become positive discovery counts.
"""
import json
from datetime import date
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.parse import urlencode, urlsplit

from ptitesondes_real_family_source_adapters import (
    parse_montpellier_mpt_detail, parse_paris_explore,
    coverage_report, scope_proposals,
)

MAX_HTML = 1_500_000
MAX_JSON = 1_000_000
MPT_SOURCE = "https://mpt.montpellier.fr/evenement/parcours-motricite"
PARIS_API = ("https://opendata.paris.fr/api/explore/v2.1/catalog/"
             "datasets/que-faire-a-paris-/records")
ALLOWED = {
    "mpt.montpellier.fr": "/evenement/",
    "opendata.paris.fr": "/api/explore/v2.1/catalog/datasets/que-faire-a-paris-/records",
}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def get_one(url, byte_limit, expected_content_type):
    p = urlsplit(url)
    if (p.scheme != "https" or not p.hostname or
            p.hostname not in ALLOWED or
            not p.path.startswith(ALLOWED[p.hostname]) or
            p.username or p.password or p.port not in (None, 443) or
            p.fragment):
        raise ValueError("unsafe_origin")
    req = Request(url, headers={
        "User-Agent": "PtitesOndesFamilySourceAudit/0.1 (no-publish)",
        "Accept": expected_content_type,
    })
    with build_opener(NoRedirect).open(req, timeout=12) as res:
        if res.geturl() != url:
            raise ValueError("redirect_disallowed")
        content_type = res.headers.get("Content-Type", "").lower()
        if expected_content_type not in content_type:
            raise ValueError("unexpected_content_type")
        body = res.read(byte_limit + 1)
        if len(body) > byte_limit:
            raise ValueError("response_too_large")
    return body.decode("utf-8-sig")


def collect_once(today):
    state = {}
    collected = {"paris_opendatasoft": [], "montpellier_mpt": []}
    api_url = PARIS_API + "?" + urlencode({
        "limit": 100, "where": "date_end >= '" + today.isoformat() + "'",
    })
    for provider, url, size, content_type in (
        ("paris_opendatasoft", api_url, MAX_JSON, "application/json"),
        ("montpellier_mpt", MPT_SOURCE, MAX_HTML, "text/html"),
    ):
        try:
            raw = get_one(url, size, content_type)
            if provider == "paris_opendatasoft":
                document = json.loads(raw)
                records = document.get("results", [])
                collected[provider] = parse_paris_explore(document, today)
                state[provider] = {
                    "status": "fetched_and_parsed",
                    "sampled_records": len(records),
                    "total_records_unfiltered": None, # no unsupported extrapolation
                }
            else:
                collected[provider] = parse_montpellier_mpt_detail(raw, url, today)
                state[provider] = {"status": "fetched_and_parsed",
                                   "sampled_pages": 1}
        except Exception as exc:
            # Predeclared reasons only; never log arbitrary URLs or
            # response bodies, which could contain personal data.
            if isinstance(exc, TimeoutError):
                reason = "timeout"
            elif isinstance(exc, ValueError):
                reason = "invalid_data_or_shape"
            else:
                reason = "source_unavailable"
            state[provider] = {"status": "held", "reason": reason}
    report = coverage_report(collected, today)
    scope = scope_proposals(
        collected["montpellier_mpt"] + collected["paris_opendatasoft"], today)
    report["structurally_plausible_for_independent_review"] = sum(
        n["structurally_plausible_for_independent_review"] for n in scope)
    report["checked_sources"] = state
    report["sample_only_not_national_exhaustiveness"] = True
    return report


if __name__ == "__main__":
    result = collect_once(date.today())
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    # A failed source is never considered a successful live validation.
    # The other source can still be diagnosed with its own counts.
    if any(v.get("status") != "fetched_and_parsed"
           for v in result["checked_sources"].values()):
        raise SystemExit("LIVE_SAMPLE_INCOMPLETE: at least one source held")
