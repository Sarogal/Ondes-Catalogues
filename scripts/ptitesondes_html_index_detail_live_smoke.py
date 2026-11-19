#!/usr/bin/env python3
"""Bounded PUBLIC source-only live smoke: official index -> exact child pages.

Invoked only by a PR diagnostic workflow. No secrets, scheduling,
catalogue access, incoming candidate URLs, private state or publishing.
Never logs page contents, titles, child URLs, city/venue or exceptions.
"""
from datetime import date
import json

from ptitesondes_html_index_detail_funnel import (
    diagnose_html_index_detail_funnel,
    redact_detail_funnel_report,
)

# Public source already present in the pre-existing city adapter. This is
# a smoke target, NOT approval of every page or an institution registry.
MPT_INDEX = {
    "approved_host": "mpt.montpellier.fr",
    "exact_index_url": "https://mpt.montpellier.fr/evenements",
}


def main():
    report = diagnose_html_index_detail_funnel(
        MPT_INDEX, "montpellier_mpt", date.today(),
        max_details=3,
    )
    print(json.dumps(
        redact_detail_funnel_report(report),
        ensure_ascii=False, sort_keys=True,
    ))
    # A fetch failure cannot be reported as a real successful sample;
    # no participant detail is exposed on failure.
    if report["child_pages_read"] < 1:
        raise SystemExit("READ_ONLY_LIVE_SAMPLE_INCOMPLETE")
    print("READ_ONLY_SOURCE_TO_DETAIL_SAMPLE_OK_NO_PUBLICATION")


if __name__ == "__main__":
    main()
