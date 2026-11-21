"""Signed publisher gate for exact-edition 2027 town-centre map markers.

Private J+1 observations only trigger work. The published HEAD selects the
sole organizer homepage, from which the publisher re-derives SAME-HOST URLs.
A second independent DNS-pinned query resolves one administrative commune.
Marker is visibly approximate ('commune'), NEVER a venue entrance.
"""
from __future__ import annotations
import base64
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import sys
from urllib.error import HTTPError
from urllib.parse import quote

from grossesondes_preview import BRANCH, FOLDER, PRIVATE, fetch_json
from grossesondes_structured_roster import iso_day

AUTOMATION = str(Path(__file__).resolve().parents[1] / "festival-automation")
if AUTOMATION not in sys.path:
    sys.path.insert(0, AUTOMATION)
from dns_pinned_https import fetch_public_html, safe_public_url
from future_city_preflight import (
    SCHEMA as CITY_SCHEMA, _normal, exact_city_from_official_site,
    undated_future_year,
)
from official_admin_communes import verified_commune

PROOF_MODE = "current-edition-commune-two-day.v1"
MAX_BYTES = 200_000
MAX_CHECKS = 4
GEO_FIELDS = frozenset({
    "city", "lat", "lon", "showOnMap", "geoCity", "geoPrecision",
    "geoSource", "geoVerification", "geoInsee",
})


def private_city_report(token, reader=fetch_json):
    """Read a fixed private branch+path, never any private-supplied URL."""
    if not isinstance(token, str) or not token:
        raise ValueError("Private read token required")
    url = PRIVATE + FOLDER + "/future-festival-city-review.json?ref=" + quote(BRANCH, safe="")
    try:
        data = reader(url, token)
        if (not isinstance(data, dict) or data.get("encoding") != "base64"
                or not isinstance(data.get("content"), str)
                or len(data["content"]) > MAX_BYTES * 2):
            return None
        raw = base64.b64decode(data["content"], validate=True)
        if not 0 < len(raw) <= MAX_BYTES:
            return None
        return json.loads(raw)
    except (HTTPError, OSError, ValueError, TypeError, KeyError, UnicodeError):
        return None


def ready_city_reviews(report, today):
    """All envelope and stable-claim checks are mandatory; reject wholesale."""
    if report is None:
        return [], "unavailable"
    try:
        day = date.fromisoformat(today)
        if (not isinstance(report, dict) or report.get("schema") != CITY_SCHEMA
                or report.get("as_of") != today
                or report.get("review_only") is not True
                or report.get("safe_to_publish") is not False
                or report.get("publication_authorized") is not False
                or report.get("publisher_city_sync_connected") is not False
                or not isinstance(report.get("findings"), list)
                or len(report["findings"]) > MAX_CHECKS
                or type(report.get("checked")) is not int
                or report["checked"] != len(report["findings"])
                or type(report.get("two_day_stable")) is not int):
            return [], "invalid_or_stale"
        output = []
        seen = set()
        counted = 0
        for item in report["findings"]:
            slug = item.get("slug") if isinstance(item, dict) else None
            if not isinstance(slug, str) or not slug or slug in seen:
                return [], "invalid_or_stale"
            seen.add(slug)
            if item.get("status") != "TWO_DAY_STABLE_REVIEW_ONLY":
                continue
            counted += 1
            proof = item.get("candidate_city")
            if (item.get("publication_authorized") is not False
                    or not isinstance(proof, dict)
                    or set(proof) != {"slug", "city", "source"}
                    or proof.get("slug") != slug
                    or not isinstance(proof.get("city"), str)
                    or not 2 <= len(proof["city"]) <= 160
                    or not isinstance(proof.get("source"), str)
                    or not isinstance(item.get("first_seen"), str)
                    or not date.fromisoformat(item["first_seen"]) < day):
                return [], "invalid_or_stale"
            output.append((slug, proof, item["first_seen"]))
        return ((output, "valid") if counted == report["two_day_stable"]
                else ([], "invalid_or_stale"))
    except (TypeError, ValueError, KeyError):
        return [], "invalid_or_stale"


def apply_independently_verified_city(target, published, review, today,
                                      fetcher=fetch_public_html,
                                      admin_reader=None):
    """Return a copy plus strict, nonauthoritative counters."""
    candidate = deepcopy(target)
    leads, status = ready_city_reviews(review, today)
    counters = {"private_report": status, "private_two_day_candidates": len(leads),
                "independent_rechecks": 0, "accepted_city_updates": [],
                "held_city": 0, "publication_authorized_by_private_report": False}
    if not leads:
        return candidate, counters
    originals = {row.get("slug"): row for row in published.get("festivals", [])
                 if isinstance(row, dict)}
    merged = {row.get("slug"): row for row in candidate.get("festivals", [])
              if isinstance(row, dict)}
    if (len(originals) != len(published.get("festivals", []))
            or len(merged) != len(candidate.get("festivals", []))):
        counters["held_city"] = len(leads)
        return candidate, counters
    for slug, private_claim, first_seen in leads:
        old, new = originals.get(slug), merged.get(slug)
        if (not isinstance(old, dict) or not isinstance(new, dict)
                or any(old.get(k) != new.get(k) for k in (
                    "slug", "name", "startDate", "endDate", "officialSite",
                    "city", "venue", "lat", "lon", "showOnMap"))
                or old.get("lat") is not None or old.get("lon") is not None
                or new.get("lat") is not None or new.get("lon") is not None
                or old.get("showOnMap") is True
                or old.get("futureVenueConfirmed") is True
                or old.get("geoVerification") is not None
                or not (
                    (iso_day(old.get("startDate")) is not None
                     and iso_day(old.get("startDate")) > date.fromisoformat(today))
                    or undated_future_year(old, today) is not None
                )
                or safe_public_url(old.get("officialSite")) is None
                or private_claim.get("source") != old["officialSite"]
                or (old.get("city") is not None
                    and _normal(old["city"]) != _normal(private_claim["city"]))):
            counters["held_city"] += 1
            continue
        counters["independent_rechecks"] += 1
        try:
            fresh = exact_city_from_official_site(old, fetcher)
        except (OSError, ValueError, TimeoutError, UnicodeError):
            fresh = None
        if (fresh is None or fresh.get("slug") != slug
                or fresh.get("source") != old["officialSite"]
                or _normal(fresh.get("city")) != _normal(private_claim["city"])):
            counters["held_city"] += 1
            continue
        args = {"reader": admin_reader} if admin_reader is not None else {}
        national = verified_commune(fresh["city"], old.get("department"), **args)
        if national is None or _normal(national["city"]) != _normal(fresh["city"]):
            counters["held_city"] += 1
            continue
        enriched = dict(new)
        enriched.update({
            "city": national["city"],
            "lat": national["lat"], "lon": national["lon"],
            "geoCity": national["city"], "geoPrecision": "commune",
            "geoInsee": national["codeInsee"],
            "geoSource": national["geoSource"], "showOnMap": True,
            "geoVerification": {
                "proofMode": PROOF_MODE,
                "firstObserved": first_seen,
                "verifiedAt": today,
                "officialSite": old["officialSite"],
                "markerMeaning": "centre_indicatif_de_commune",
            },
        })
        if any(enriched.get(k) != new.get(k) for k in
               set(enriched) | set(new) if k not in GEO_FIELDS):
            raise ValueError("Invalid mutation outside town fields")
        candidate["festivals"][candidate["festivals"].index(new)] = enriched
        merged[slug] = enriched
        counters["accepted_city_updates"].append(slug)
    if counters["accepted_city_updates"]:
        candidate["generatedAt"] = today
    return candidate, counters
