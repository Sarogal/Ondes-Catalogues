#!/usr/bin/env python3
"""PR-only multi-event MPT -> independent official/IGN preview (no publish).

Reads the official MPT listing (max 24 details) and reviewed IGN addresses
only. No secrets, persistence, private repo access, or user-facing publication.
All output is aggregated counts without titles, candidate URLs or raw HTML.
"""
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import json
import sys

from ptitesondes_mpt_listing_discovery import LISTING_URL
from ptitesondes_mpt_listing_live_smoke import read_official
from ptitesondes_mpt_geo_live_smoke import get_reviewed_geocoder
from ptitesondes_mpt_batch_independent_review import (
    review_official_listing_batch,
)


def live_batch():
    today = datetime.now(ZoneInfo("Europe/Paris")).date()
    catalogue = json.loads((
        Path(__file__).resolve().parents[1] / "docs/ptitesondes/sorties.json"
    ).read_text(encoding="utf-8"))
    return review_official_listing_batch(
        read_official(LISTING_URL), catalogue, today,
        detail_get=read_official, geocoder_get=get_reviewed_geocoder,
        page_limit=24,
    )


if __name__ == "__main__":
    try:
        report = live_batch()
        print(json.dumps(report, sort_keys=True, ensure_ascii=False, indent=2))
        if report["unreadable_detail_pages_held"]:
            raise SystemExit("MPT_BATCH_INCOMPLETE_SOURCES_HOLD")
        # One-shot read-only signal: zero can be legitimate as events expire,
        # but must NOT be silently described as a qualified event.
    except (OSError, UnicodeError, ValueError, TypeError, KeyError):
        raise SystemExit("MPT_BATCH_INDEPENDENT_SOURCE_REVIEW_HELD")
