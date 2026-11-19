#!/usr/bin/env python3
"""Bounded PUBLIC source-only live smoke: official index -> exact child pages.

Invoked only by a PR diagnostic workflow. No secrets, scheduling,
catalogue writes, incoming candidate URLs, private state or publishing.
Reads the separately maintained public venue registries and historical
catalogue snapshot, for an anonymized collision diagnostic only.
Never logs page contents, titles, child URLs, city/venue or exceptions.
"""
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import json

from venue_registry import VENUES
from ptitesondes_public_place_venues import approved_public_venues
from ptitesondes_html_index_detail_funnel import (
    diagnose_html_index_detail_funnel,
    redact_detail_funnel_report, MAX_DETAILS,
)

# Public source already present in the pre-existing city adapter. This is
# a smoke target, NOT approval of every page or an institution registry.
MPT_INDEX = {
    "approved_host": "mpt.montpellier.fr",
    "exact_index_url": "https://mpt.montpellier.fr/evenements",
}


def _independent_context():
    snapshot_path = Path(__file__).resolve().parents[1] / "docs/ptitesondes/sorties.json"
    data = snapshot_path.read_bytes()
    if len(data) > 1_000_000:
        raise ValueError("historical_snapshot_oversize")
    catalogue = json.loads(data.decode("utf-8"))
    places = approved_public_venues()
    if (not isinstance(catalogue, dict)
            or not isinstance(catalogue.get("events"), list)
            or not catalogue.get("updated_at")
            or not places):
        raise ValueError("independent_registry_snapshot_invalid")
    return {
        "legacy_venues": VENUES,
        "public_places": places,
        "historical_catalogue": catalogue,
    }


def main():
    now_local = datetime.now(ZoneInfo("Europe/Paris"))
    try:
        context = _independent_context()
    except (OSError, ValueError, TypeError, UnicodeError):
        raise SystemExit("READ_ONLY_INDEPENDENT_SNAPSHOT_UNAVAILABLE") from None
    report = diagnose_html_index_detail_funnel(
        MPT_INDEX, "montpellier_mpt", now_local.date(),
        max_details=MAX_DETAILS, as_of=now_local,
        independent_context=context,
        # Probe at most two distinct already-reviewed buildings, not one
        # lookup per event. Non-structured addresses remain unverified.
        geo_probe_limit=2,
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
