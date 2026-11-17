#!/usr/bin/env python3
"""One-shot Montpellier source+IGN preview, NEVER a publisher.

As-of audit date is pinned to Nov 17, 2026. If the source disappears or
changes, fail closed. Do not rerun as a recurring data-intake workflow.
Raw first-party HTML and candidate identities are NEVER printed to logs.
"""
from datetime import date
import json
from pathlib import Path
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.parse import urlsplit

from ptitesondes_mpt_family_independent_preflight import (
    independent_family_preview, safe_mpt_event_url,
)
from ptitesondes_mpt_geo_live_smoke import get_reviewed_geocoder

PILOT_DAY = date(2026, 11, 17)
SOURCE = "https://mpt.montpellier.fr/evenement/bebes-lecteurs"
MAX_HTML = 1_500_000


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def official_page(url):
    if not safe_mpt_event_url(url) or url != SOURCE:
        raise ValueError("outside_pinned_municipal_pilot")
    req = Request(url, headers={
        "Accept": "text/html",
        "User-Agent": "PtitesOndesFamilyOfficialEvidencePilot/0.1 (no-publish)",
    })
    with build_opener(NoRedirect).open(req, timeout=12) as res:
        if res.geturl() != url:
            raise ValueError("municipal_redirect_unreviewed")
        if "text/html" not in res.headers.get("Content-Type", "").lower():
            raise ValueError("municipal_content_type_mismatch")
        raw = res.read(MAX_HTML + 1)
        if len(raw) > MAX_HTML:
            raise ValueError("municipal_page_exceeds_limit")
    return raw.decode("utf-8", "replace")


def live_review():
    catalogue = json.loads((
        Path(__file__).resolve().parents[1] /
        "docs/ptitesondes/sorties.json"
    ).read_text(encoding="utf-8"))
    lead = {
        "provider": "montpellier_mpt", "title": "Bébés lecteurs",
        "city": "Montpellier", "venue": "Maison pour tous Frida Kahlo",
        "source_url": SOURCE,
        "date_start": "2026-11-18", "date_end": "2026-11-18",
        "start_local": "10:30", "audience_claim": "explicit_baby",
        "category": "lecture-jeunesse",
        # A free event is not proof every participation condition is waived.
        "price_evidence": "explicit_free",
        "registration_evidence": "explicit_required",
        "verification": "discovery_only_needs_official_and_independent_proof",
    }
    return independent_family_preview(
        [lead], catalogue, PILOT_DAY,
        official_get=official_page, geocoder_get=get_reviewed_geocoder)


if __name__ == "__main__":
    try:
        data = live_review()
        print(json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2))
        if data["official_source_cues_passed"] != 1:
            raise SystemExit("PILOT_SOURCE_OR_GEO_INDEPENDENT_PROOF_HELD")
    except (OSError, ValueError, TypeError, UnicodeError, KeyError):
        raise SystemExit("PILOT_SOURCE_OR_GEO_UNAVAILABLE")
