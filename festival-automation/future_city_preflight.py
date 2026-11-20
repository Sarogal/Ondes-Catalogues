"""Observe CURRENT-edition commune announcements without inventing a venue.

Official organizer homepage and at most two SAME-HOST current-edition/visit
pages. A city is only a first-party, edition-dated claim; no coordinates
or map pin exist here. Re-observe on separate days; public publisher must
independently re-fetch official proof and the national commune registry.
"""
from __future__ import annotations
import argparse
from datetime import date, datetime, timedelta
from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
import unicodedata
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from dns_pinned_https import fetch_public_html, safe_public_url
from future_geo_preflight import (
    MAX_CHECKS, _VisibleOrganizerLinks, _matching_event, _name, _country,
    _atomic, eligible, official_access_links,
)
SCRIPTS = str(Path(__file__).resolve().parents[1] / "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
from grossesondes_structured_roster import (
    JsonLD, SENSITIVE_STATUSES, edition_name, iso_day, walk,
)
from grossesondes_official_html_edition import (
    CANCEL, VisibleParagraphs, dominant_visible_range, explicit_ranges, fold,
)

SCHEMA = "grossesondes.future-festival-city-private.v1"
STATE_KEY = "future_edition_city_observations_private"
CURSOR_KEY = "future_edition_city_rotation_cursor"
MAX_INTERNAL_PAGES = 2
CITY_PATTERN = re.compile(
    r"\b(?:à|au|in|at)\s+([A-ZÀ-ÖØ-Ý][a-zà-öø-ÿ]+"
    r"(?:[-'][A-ZÀ-ÖØ-Ý][a-zà-öø-ÿ]+)*"
    r"(?:\s+[A-ZÀ-ÖØ-Ý][a-zà-öø-ÿ]+(?:[-'][A-ZÀ-ÖØ-Ý][a-zà-öø-ÿ]+)*){0,3})"
)
EXCLUDE = re.compile(r"(?:202[0-6]|201\d|archive|photo|contact|cookie|mentions|"
                     r"billet|ticket|shop|boutique|privacy|partenaire)", re.I)
CURRENT = re.compile(r"(?:2027|2028|2029|20[3-4]\d|edition|nouvelle|new|"
                     r"actu|news|actualite|nouveaute|dates)", re.I)


def _normal(value):
    return "".join(re.findall(r"[a-z0-9]+", fold(value)))


def _city_jsonld(html, row):
    parser = JsonLD()
    try:
        parser.feed(html)
        parser.close()
    except (ValueError, TypeError, UnicodeError):
        return None
    start, end = iso_day(row.get("startDate")), iso_day(row.get("endDate"))
    if not start or not end:
        return None
    facts = set()
    for document in parser.documents[:30]:
        for event in walk(document):
            if not _matching_event(event, row):
                continue
            if (iso_day(event.get("startDate")) != start
                    or iso_day(event.get("endDate")) != end
                    or str(event.get("eventStatus", "")).rsplit("/", 1)[-1].casefold()
                       in SENSITIVE_STATUSES):
                return False
            location = event.get("location")
            if not isinstance(location, dict):
                return None
            raw_types = location.get("@type", [])
            types = raw_types if isinstance(raw_types, list) else [raw_types]
            if "place" not in {str(t).rsplit("/", 1)[-1].casefold() for t in types}:
                return False
            address = location.get("address")
            if not isinstance(address, dict):
                return None
            city = _name(address.get("addressLocality"))
            # Require either explicit FR or pre-registered same-city context.
            if (city is None or
                    (address.get("addressCountry") not in (None, "")
                     and _country(address) != "FR") or
                    (_country(address) != "FR"
                     and _normal(city) != _normal(row.get("city")))):
                return False
            facts.add(city)
    return next(iter(facts)) if len(facts) == 1 else (False if facts else None)


def _city_visible(html, row):
    start, end = iso_day(row.get("startDate")), iso_day(row.get("endDate"))
    if start is None or end is None or start.year != end.year:
        return None
    words = re.findall(r"[a-z0-9]+",
                       re.sub(r"\b20[2-4]\d\b", "", fold(row.get("name", ""))))
    if len("".join(words)) < 8:
        return None
    name = re.compile(r"(?<![a-z0-9])" + r"[\W_]+".join(map(re.escape, words))
                      + r"(?![a-z0-9])")
    parser = VisibleParagraphs()
    try:
        parser.feed(html)
        parser.close()
    except (ValueError, TypeError, UnicodeError):
        return None
    facts = set()
    for raw in " ".join(parser.parts).split(VisibleParagraphs.SEP):
        if not 0 < len(raw) <= 1100:
            continue
        paragraph = " ".join(fold(raw).split())
        if (not name.search(paragraph) or CANCEL.search(paragraph)
                or {int(y) for y in re.findall(r"(?<!\d)20[2-4]\d(?!\d)", raw)}
                   != {start.year}):
            continue
        ranges = {(a, b) for _, _, a, b
                  in explicit_ranges(paragraph, start.year)}
        if dominant_visible_range(ranges) != (start, end):
            continue
        # Exact edition and locality must share the SAME visible paragraph.
        # Capitalization is retained for municipality extraction.
        for match in CITY_PATTERN.finditer(raw):
            city = _name(match.group(1))
            if city and not re.search(r"\b(?:Festival|France|Parisien|Vente|Billetterie)\b", city):
                facts.add(city)
    return next(iter(facts)) if len(facts) == 1 else None


def exact_edition_city(html, row):
    """One city of one 2027 edition, or nothing. Never infer from old years."""
    if not isinstance(html, str) or not 0 < len(html) <= 650_000:
        return None
    start = iso_day(row.get("startDate"))
    if start is None or start.year not in range(2026, 2050):
        return None
    structured = _city_jsonld(html, row)
    if structured is False:
        return None
    visible = _city_visible(html, row)
    if structured is not None and visible is not None and _normal(structured) != _normal(visible):
        return None
    city = structured or visible
    if not city or (row.get("city") and _normal(city) != _normal(row["city"])):
        return None
    return {"slug": row["slug"], "city": city, "source": row["officialSite"]}


def official_city_links(home_html, homepage):
    """Select only same-host current-edition news + access pages.

    Link text is NOT trusted as evidence, merely a bounded discovery hint.
    """
    if (safe_public_url(homepage) is None or not isinstance(home_html, str)
            or not 0 < len(home_html) <= 650_000):
        return []
    parser = _VisibleOrganizerLinks()
    try:
        parser.feed(home_html)
        parser.close()
    except (ValueError, TypeError, UnicodeError):
        return []
    host = urlsplit(homepage).hostname
    selected = {}
    for href, label in parser.links[:250]:
        if not isinstance(href, str) or not 1 <= len(href) <= 900:
            continue
        try:
            candidate = urljoin(homepage, href)
            parts = urlsplit(candidate)
            decoded = unquote(parts.path)
            url = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
            if (parts.hostname != host or parts.query
                    or not decoded.startswith("/")
                    or any(p in (".", "..") for p in decoded.split("/"))
                    or re.search(r"%(?:2f|5c|2e|00)", parts.path, re.I)
                    or safe_public_url(url) is None or url == homepage):
                continue
            target = decoded.replace("-", " ").replace("_", " ")
            text = f"{target} {label}"
            if EXCLUDE.search(target) or not CURRENT.search(text):
                continue
            selected[url] = 0 if re.search(r"\b20[2-4]\d\b", text) else 1
        except (ValueError, TypeError, UnicodeError):
            continue
    for i, url in enumerate(official_access_links(home_html, homepage)):
        selected.setdefault(url, 3 + i)
    return sorted(selected, key=lambda url: (selected[url], len(url), url))[:MAX_INTERNAL_PAGES]


def exact_city_from_official_site(row, fetcher=fetch_public_html):
    """A fresh bounded first-party download; never trust a private URL."""
    home = row.get("officialSite")
    if safe_public_url(home) is None:
        return None
    body = fetcher(home)
    facts = []
    claim = exact_edition_city(body, row)
    if claim is not None:
        facts.append(claim)
    for url in official_city_links(body, home):
        try:
            claim = exact_edition_city(fetcher(url), row)
        except (OSError, ValueError, TimeoutError, UnicodeError):
            continue
        if claim is not None:
            facts.append(claim)
    if not facts or any(_normal(c["city"]) != _normal(facts[0]["city"]) for c in facts):
        return None
    return facts[0]


def review(state, calendar, today, fetcher=fetch_public_html, limit=MAX_CHECKS):
    day = date.fromisoformat(today)
    if (not isinstance(state, dict)
            or state.get("schema") != "grossesondes.source-watch.v1"
            or type(limit) is not int or not 0 <= limit <= MAX_CHECKS):
        raise ValueError("Invalid private city observer input")
    observations = state.setdefault(STATE_KEY, {})
    cursor = state.get(CURSOR_KEY, 0)
    if (not isinstance(observations, dict) or len(observations) > 150
            or type(cursor) is not int or not 0 <= cursor <= 1_000_000):
        raise ValueError("Invalid city observer state")
    rows = [r for r in eligible(calendar, today)
            if safe_public_url(r.get("officialSite")) and r.get("showOnMap") is not True
            and r.get("futureVenueConfirmed") is not True]
    active = {r["slug"] for r in rows}
    for slug in list(observations):
        if slug not in active:
            del observations[slug]
    yesterday = (day - timedelta(days=1)).isoformat()
    pending = [r for r in rows if (
        isinstance(observations.get(r["slug"]), dict)
        and observations[r["slug"]].get("lastSeen") == yesterday
        and observations[r["slug"]].get("firstSeen") == yesterday)]
    rest = [r for r in rows if r not in pending]
    rotated = rest[cursor % len(rest):] + rest[:cursor % len(rest)] if rest else []
    selected = (pending + rotated)[:limit]
    state[CURSOR_KEY] = cursor + max(1, len(selected))
    findings = []
    for row in selected:
        slug = row["slug"]
        result = {"slug": slug, "status": "CITY_NOT_PROVEN"}
        try:
            claim = exact_city_from_official_site(row, fetcher)
        except (OSError, ValueError, TimeoutError, UnicodeError):
            claim = None
            result["status"] = "OFFICIAL_FETCH_UNAVAILABLE"
        if claim is None:
            observations.pop(slug, None)
            findings.append(result)
            continue
        digest = sha256(json.dumps(
            {"city": _normal(claim["city"]), "source": claim["source"]},
            sort_keys=True).encode("utf-8")).hexdigest()
        previous = observations.get(slug)
        stable = (isinstance(previous, dict) and previous.get("digest") == digest
                  and ((previous.get("lastSeen") == yesterday
                        and (previous.get("firstSeen") == yesterday
                             or previous.get("stable") is True))
                       or (previous.get("lastSeen") == today
                           and previous.get("stable") is True)))
        first = previous["firstSeen"] if stable else today
        observations[slug] = {"digest": digest, "firstSeen": first,
                              "lastSeen": today, "stable": stable}
        result.update(status=("TWO_DAY_STABLE_REVIEW_ONLY" if stable
                              else "FIRST_DAY_REVIEW_ONLY"),
                      candidate_city=claim, first_seen=first,
                      publication_authorized=False)
        findings.append(result)
    return {
        "schema": SCHEMA, "as_of": today, "review_only": True,
        "safe_to_publish": False, "publication_authorized": False,
        "publisher_city_sync_connected": False,
        "eligible": len(rows), "checked": len(selected),
        "first_day": sum(r["status"] == "FIRST_DAY_REVIEW_ONLY" for r in findings),
        "two_day_stable": sum(
            r["status"] == "TWO_DAY_STABLE_REVIEW_ONLY" for r in findings),
        "findings": findings,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--intake", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=MAX_CHECKS)
    args = parser.parse_args()
    today = datetime.now(ZoneInfo("Europe/Paris")).date().isoformat()
    state_file = args.intake / "source-watch-state.json"
    state = json.loads(state_file.read_text(encoding="utf-8"))
    catalogue = json.loads(args.catalog.read_text(encoding="utf-8"))
    report = review(state, catalogue, today, limit=args.limit)
    _atomic(state_file, state)
    _atomic(args.intake / "future-festival-city-review.json", report)
    print("Private exact-edition city research; no map pin or public write")


if __name__ == "__main__":
    main()
