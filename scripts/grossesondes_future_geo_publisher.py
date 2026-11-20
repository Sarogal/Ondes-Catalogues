"""Second, independent publication gate for future festival venue coordinates.

A PRIVATE two-day review is a lead, never proof. For every eligible proposal,
the PUBLIC publisher selects the URL from the integrity-pinned signed
calendar and independently downloads the official current-edition page.
Only a geographically complete, exact-match event can add a map pin.

No discovery URL from the private report is ever visited. No historical
coordinates, venue, or city can be inherited. This module never writes files.
"""
from __future__ import annotations

import base64
from copy import deepcopy
from datetime import date
import json
from math import isfinite
from pathlib import Path
import sys
from urllib.error import HTTPError
from urllib.parse import quote

from grossesondes_preview import BRANCH, FOLDER, PRIVATE, fetch_json

FESTIVAL_AUTOMATION = str(Path(__file__).resolve().parents[1] / "festival-automation")
if FESTIVAL_AUTOMATION not in sys.path:
    sys.path.insert(0, FESTIVAL_AUTOMATION)
from dns_pinned_https import fetch_public_html, safe_public_url
from future_geo_preflight import SCHEMA as REVIEW_SCHEMA, exact_edition_geo
from grossesondes_structured_roster import iso_day

PROOF_MODE = "current-edition-geo-two-day.v1"
MAX_EVIDENCE_BYTES = 200_000
MAX_RECHECKS = 4
FIELDS = frozenset((
    "city", "venue", "lat", "lon", "showOnMap", "geoPrecision",
    "geoCity", "geoSource", "futureVenueConfirmed", "geoVerification",
))


def private_geo_report(token, reader=fetch_json):
    """Read ONE fixed private GitHub path; never a user-controlled URL.

    The report is optional. A missing/unavailable/invalid report can never
    become permission to publish, or block proven non-geographic updates.
    """
    if not isinstance(token, str) or not token:
        raise ValueError("Missing private read token")
    url = PRIVATE + FOLDER + "/future-festival-geo-review.json?ref=" + quote(
        BRANCH, safe="")
    try:
        data = reader(url, token)
        if (not isinstance(data, dict)
                or data.get("encoding") != "base64"
                or not isinstance(data.get("content"), str)
                or len(data["content"]) > MAX_EVIDENCE_BYTES * 2):
            return None
        raw = base64.b64decode(data["content"], validate=False)
        if not raw or len(raw) > MAX_EVIDENCE_BYTES:
            return None
        return json.loads(raw)
    except (HTTPError, OSError, ValueError, KeyError, TypeError, UnicodeError):
        return None


def _valid_coordinates(row):
    lat, lon = row.get("lat"), row.get("lon")
    return (type(lat) in (int, float) and type(lon) in (int, float)
            and isfinite(lat) and isfinite(lon)
            and -90 <= lat <= 90 and -180 <= lon <= 180)


def ready_reviews(review, today):
    """Validate the entire PRIVATE envelope before considering any claim.

    On an invalid or stale report, reject ALL geo proposals, not just one.
    No PRIVATE 'published' or 'approved' value is trusted as authority.
    """
    if review is None:
        return [], "unavailable"
    try:
        date.fromisoformat(today)
        if (not isinstance(review, dict)
                or review.get("schema") != REVIEW_SCHEMA
                or review.get("as_of") != today
                or review.get("review_only") is not True
                or review.get("safe_to_publish") is not False
                or review.get("publication_authorized") is not False
                or review.get("publisher_geo_sync_connected") is not False):
            return [], "invalid_or_stale"
        findings = review.get("findings")
        if (not isinstance(findings, list)
                or len(findings) > MAX_RECHECKS
                or review.get("checked") != len(findings)
                or type(review.get("two_day_stable")) is not int
                or review["two_day_stable"] != sum(
                    isinstance(item, dict)
                    and item.get("status") == "TWO_DAY_STABLE_REVIEW_ONLY"
                    for item in findings)):
            return [], "invalid_or_stale"
        slugs = set()
        ready = []
        for item in findings:
            if not isinstance(item, dict):
                return [], "invalid_or_stale"
            slug = item.get("slug")
            if not isinstance(slug, str) or not slug or slug in slugs:
                return [], "invalid_or_stale"
            slugs.add(slug)
            if item.get("status") != "TWO_DAY_STABLE_REVIEW_ONLY":
                continue
            claim = item.get("candidate_geo")
            first = item.get("first_seen")
            if (item.get("publication_authorized") is not False
                    or not isinstance(claim, dict)
                    or not isinstance(first, str)
                    or not (date.fromisoformat(first) < date.fromisoformat(today))
                    or claim.get("slug") != slug):
                return [], "invalid_or_stale"
            ready.append((slug, claim))
        return ready, "valid"
    except (TypeError, ValueError, KeyError):
        return [], "invalid_or_stale"


def apply_independently_verified_geo(target, published, review, today,
                                     fetcher=fetch_public_html):
    """Return an enriched COPY and safe, content-free diagnostics.

    The supplied PUBLISHED calendar must already have passed the signed-head
    check in cloud_sync.main. A report never supplies a network destination:
    the original officialSite in the signed row is the sole allowed fetch.
    """
    candidate = deepcopy(target)
    summary = {
        "private_report": "unavailable",
        "private_two_day_candidates": 0,
        "independent_rechecks": 0,
        "accepted_geo_updates": [],
        "held_geo": 0,
        "publication_authorized_by_private_report": False,
    }
    ready, report_state = ready_reviews(review, today)
    summary["private_report"] = report_state
    summary["private_two_day_candidates"] = len(ready)
    if not ready:
        return candidate, summary

    old_rows = {r.get("slug"): r for r in published.get("festivals", [])
                if isinstance(r, dict)}
    new_rows = {r.get("slug"): r for r in candidate.get("festivals", [])
                if isinstance(r, dict)}
    if len(old_rows) != len(published.get("festivals", [])) or \
            len(new_rows) != len(candidate.get("festivals", [])):
        return candidate, {**summary, "held_geo": len(ready)}

    for slug, private_claim in ready:
        old, new = old_rows.get(slug), new_rows.get(slug)
        if (not isinstance(old, dict) or not isinstance(new, dict)
                or any(old.get(key) != new.get(key) for key in (
                    "slug", "name", "startDate", "endDate", "officialSite",
                    "city", "venue", "lat", "lon", "showOnMap"))
                or old.get("showOnMap") is not False
                or old.get("lat") is not None or old.get("lon") is not None
                or old.get("futureVenueConfirmed") is True
                or old.get("geoVerification") is not None
                or old.get("venue") not in (None, "")
                or iso_day(old.get("startDate")) is None
                or iso_day(old.get("startDate")) <= date.fromisoformat(today)
                or safe_public_url(old.get("officialSite")) is None
                or private_claim.get("source") != old["officialSite"]):
            summary["held_geo"] += 1
            continue

        summary["independent_rechecks"] += 1
        try:
            official = exact_edition_geo(fetcher(old["officialSite"]), old)
        except (OSError, ValueError, TimeoutError, UnicodeError):
            official = None
        # A same-host official page must identify the CURRENT edition and
        # confirm one named venue, one commune and a French country code.
        if (official is None or official != private_claim
                or not official.get("venue")
                or official.get("country") != "FR"):
            summary["held_geo"] += 1
            continue

        certified = dict(new)
        certified.update({
            "city": official["city"],
            "venue": official["venue"],
            "lat": official["lat"],
            "lon": official["lon"],
            "geoPrecision": "lieu",
            "geoCity": official["city"],
            "geoSource": old["officialSite"],
            "futureVenueConfirmed": True,
            "showOnMap": True,
            "geoVerification": {
                "proofMode": PROOF_MODE,
                "firstObserved": next(
                    item["first_seen"] for item in review["findings"]
                    if item["slug"] == slug
                ),
                "verifiedAt": today,
                "officialSite": old["officialSite"],
            },
        })
        if set(certified) - set(new) - FIELDS:
            raise ValueError("Unexpected geographic field")
        # Only geography may differ; do not silently rewrite date/identity.
        if any(certified.get(key) != new.get(key)
               for key in set(certified) | set(new) if key not in FIELDS):
            raise ValueError("Non-geographic mutation")
        position = candidate["festivals"].index(new)
        candidate["festivals"][position] = certified
        new_rows[slug] = certified
        summary["accepted_geo_updates"].append(slug)

    if summary["accepted_geo_updates"]:
        candidate["generatedAt"] = today
    return candidate, summary
