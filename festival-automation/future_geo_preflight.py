"""Private, bounded geolocation observations for future PUBLISHED festivals.

Only the signed public catalogue selects first-party HTTPS endpoints. JSON-LD
must identify the exact edition and its dates, not an archived event or a
generic venue. Two separate calendar days are required for a stable clue.
This module NEVER edits the public catalogue, a publisher patch, or a map flag.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
from hashlib import sha256
import json
from math import isfinite
import os
from pathlib import Path
import re
import sys
import tempfile
from zoneinfo import ZoneInfo

from dns_pinned_https import fetch_public_html, safe_public_url

SCRIPTS = str(Path(__file__).resolve().parents[1] / "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
from grossesondes_structured_roster import (
    ALLOWED_EVENT_TYPES, SENSITIVE_STATUSES, JsonLD, edition_name, iso_day, walk,
)

SCHEMA = "grossesondes.future-festival-geo-private.v1"
STATE_KEY = "future_edition_geo_observations_private"
CURSOR_KEY = "future_edition_geo_rotation_cursor"
MAX_CHECKS = 4


def _coord(value, bound):
    if type(value) in (int, float):
        number = float(value)
    elif (isinstance(value, str)
          and re.fullmatch(r"-?\d{1,3}(?:\.\d{1,12})?", value)):
        number = float(value)
    else:
        return None
    return number if isfinite(number) and -bound <= number <= bound else None


def _name(value):
    if not isinstance(value, str) or not 2 <= len(value.strip()) <= 160:
        return None
    return value.strip()


def _matching_event(event, row):
    raw_types = event.get("@type", [])
    types = raw_types if isinstance(raw_types, list) else [raw_types]
    types = {str(v).rsplit("/", 1)[-1].casefold() for v in types}
    if not types.intersection(ALLOWED_EVENT_TYPES):
        return False
    title = event.get("name")
    start = iso_day(row.get("startDate"))
    return (isinstance(title, str) and start is not None
            and edition_name(title) == edition_name(row.get("name"))
            and len(edition_name(title)) >= 7
            and str(start.year) in re.findall(r"\b20[2-4][0-9]\b", title))


def exact_edition_geo(html, row):
    """Return one edition-specific structured venue claim or None, fail closed.

    Every matching current-edition Event must agree on the same date and site.
    A city alone never creates a pin; an archived or ambiguous location cannot
    certify current-year coordinates. JSON-LD is only PRIVATE evidence here.
    """
    if not isinstance(html, str) or not 0 < len(html) <= 650_000:
        return None
    start, end = iso_day(row.get("startDate")), iso_day(row.get("endDate"))
    if start is None or end is None or end < start:
        return None
    parser = JsonLD()
    try:
        parser.feed(html)
        parser.close()
    except (ValueError, TypeError):
        return None
    facts = []
    for document in parser.documents[:30]:
        for event in walk(document):
            if not _matching_event(event, row):
                continue
            if (iso_day(event.get("startDate")) != start
                    or iso_day(event.get("endDate")) != end
                    or str(event.get("eventStatus", "")).rsplit("/", 1)[-1].casefold()
                    in SENSITIVE_STATUSES):
                return None
            location = event.get("location")
            if not isinstance(location, dict):
                return None
            location_types = location.get("@type", [])
            location_types = location_types if isinstance(location_types, list) else [location_types]
            if "place" not in {str(t).rsplit("/", 1)[-1].casefold()
                               for t in location_types}:
                return None
            address = location.get("address")
            geo = location.get("geo")
            if not isinstance(address, dict) or not isinstance(geo, dict):
                return None
            locality = _name(address.get("addressLocality"))
            venue = _name(location.get("name"))
            lat = _coord(geo.get("latitude"), 90)
            lon = _coord(geo.get("longitude"), 180)
            if (locality is None or lat is None or lon is None
                    or (lat == 0 and lon == 0)
                    or (row.get("city") is not None
                        and edition_name(locality) != edition_name(row["city"]))):
                return None
            facts.append({
                "slug": row["slug"], "city": locality, "venue": venue,
                "lat": lat, "lon": lon, "source": row["officialSite"],
            })
    if not facts or any(value != facts[0] for value in facts[1:]):
        return None
    return facts[0]


def eligible(calendar, today):
    if (not isinstance(calendar, dict) or calendar.get("schema") != 1
            or not isinstance(calendar.get("festivals"), list)):
        raise ValueError("Invalid signed festival catalogue")
    today_date = date.fromisoformat(today)
    missing = []
    seen = set()
    for row in calendar["festivals"]:
        if not isinstance(row, dict) or not isinstance(row.get("slug"), str):
            raise ValueError("Invalid festival catalogue row")
        if row["slug"] in seen:
            raise ValueError("Duplicate signed festival slug")
        seen.add(row["slug"])
        start = iso_day(row.get("startDate"))
        if start is None or start <= today_date:
            continue
        lat, lon = row.get("lat"), row.get("lon")
        if (type(lat) in (int, float) and type(lon) in (int, float)
                and isfinite(lat) and isfinite(lon)
                and -90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        missing.append(row)
    return missing


def review(state, calendar, today, fetcher=fetch_public_html, limit=MAX_CHECKS):
    """Review <=4 first-party pages; never take an URL from private state."""
    today_date = date.fromisoformat(today)
    if (not isinstance(state, dict)
            or state.get("schema") != "grossesondes.source-watch.v1"
            or type(limit) is not int or not 0 <= limit <= MAX_CHECKS):
        raise ValueError("Invalid geo private intake")
    obs = state.setdefault(STATE_KEY, {})
    cursor = state.get(CURSOR_KEY, 0)
    if (not isinstance(obs, dict) or len(obs) > 150
            or type(cursor) is not int or not 0 <= cursor <= 1_000_000):
        raise ValueError("Invalid geo private observations")
    rows = eligible(calendar, today)
    available = [row for row in rows if safe_public_url(row.get("officialSite"))]
    active = {row["slug"] for row in available}
    for slug in list(obs):
        if slug not in active:
            del obs[slug]
    yesterday = (today_date - timedelta(days=1)).isoformat()
    # Give the previous day's first observations priority before fair rotation.
    pending = [row for row in available if (
        isinstance(obs.get(row["slug"]), dict)
        and obs[row["slug"]].get("firstSeen") == yesterday
        and obs[row["slug"]].get("lastSeen") == yesterday)]
    rest = [row for row in available if row not in pending]
    if rest:
        offset = cursor % len(rest)
        rest = rest[offset:] + rest[:offset]
    selected = (pending + rest)[:limit]
    state[CURSOR_KEY] = cursor + max(1, len(selected))
    findings = []
    for row in selected:
        slug = row["slug"]
        result = {"slug": slug, "status": "OFFICIAL_GEO_NOT_PROVEN"}
        try:
            html = fetcher(row["officialSite"])
            claim = exact_edition_geo(html, row)
        except (OSError, ValueError, TimeoutError, UnicodeError):
            claim = None
            result["status"] = "OFFICIAL_FETCH_UNAVAILABLE"
        if claim is None:
            obs.pop(slug, None)
            findings.append(result)
            continue
        digest = sha256(json.dumps(
            claim, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        previous = obs.get(slug)
        second = (isinstance(previous, dict)
                  and previous.get("digest") == digest
                  and previous.get("lastSeen") == yesterday
                  and (previous.get("firstSeen") == yesterday
                       or previous.get("stable") is True))
        first_seen = (previous["firstSeen"] if second
                      else today)
        obs[slug] = {"digest": digest, "firstSeen": first_seen,
                     "lastSeen": today, "stable": second}
        result.update(
            status="TWO_DAY_STABLE_REVIEW_ONLY" if second else "FIRST_DAY_REVIEW_ONLY",
            candidate_geo=claim, first_seen=first_seen,
            publication_authorized=False,
        )
        findings.append(result)
    return {
        "schema": SCHEMA, "as_of": today,
        "review_only": True, "safe_to_publish": False,
        "publication_authorized": False,
        "publisher_geo_sync_connected": False,
        "dated_future_without_coordinates": len(rows),
        "with_signed_safe_official_site": len(available),
        "checked": len(selected),
        "first_day": sum(x["status"] == "FIRST_DAY_REVIEW_ONLY" for x in findings),
        "two_day_stable": sum(x["status"] == "TWO_DAY_STABLE_REVIEW_ONLY" for x in findings),
        "findings": findings,
    }


def _atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, filename = tempfile.mkstemp(dir=path.parent, prefix=".geo-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(filename, path)
    finally:
        if os.path.exists(filename):
            os.unlink(filename)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--intake", type=Path, required=True)
    p.add_argument("--catalog", type=Path, required=True)
    p.add_argument("--limit", type=int, default=MAX_CHECKS)
    args = p.parse_args()
    today = datetime.now(ZoneInfo("Europe/Paris")).date().isoformat()
    state_file = args.intake / "source-watch-state.json"
    state = json.loads(state_file.read_text(encoding="utf-8"))
    calendar = json.loads(args.catalog.read_text(encoding="utf-8"))
    result = review(state, calendar, today, limit=args.limit)
    _atomic(state_file, state)
    _atomic(args.intake / "future-festival-geo-review.json", result)
    print("Private festival geo preflight complete; no map pin or publication")


if __name__ == "__main__":
    main()
