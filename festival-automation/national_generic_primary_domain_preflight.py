"""Generic private preflight for national festival domains absent legacy APPROVED.

National dossiers and their URLs are untrusted RESEARCH leads. Safe DNS-pinned
HTTPS fetch is allowed only for bounded same-source organizer/homepage
observations; a valid date twice on distinct days remains a private claim.
This module NEVER publishes a patch, adds an approved source, or grants proof
of organizer control. The publisher requires a separate independent route.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path
import re
import sys
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit

from dns_pinned_https import safe_public_url, fetch_public_html
from source_qualification import normalized

SCRIPTS = str(Path(__file__).resolve().parents[1] / "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
from grossesondes_institutional_edition import institutional_date
from grossesondes_official_html_edition import (VisibleText, fold, explicit_ranges,
                                               visible_official_edition,
                                               dominant_visible_range)
from grossesondes_structured_edition import no_same_edition_jsonld_contradiction

SCHEMA = "grossesondes.national-generic-domain-dates-private.v1"
QUEUE_SCHEMA = "grossesondes.national-festival-discovery-private.v1"
STATE_KEY = "national_generic_primary_date_observations_private"
TRUSTED_RESEARCH_KINDS = frozenset({
    "CURATED_PRIMARY_CANDIDATE",
    "HISTORICAL_HOMEPAGE_YEAR_HINT",
})
MAX_CHECKS = 4
MAX_DOSSIERS = 200
MAX_SOURCES_PER_DOSSIER = 12
MAX_TITLE = 150
MAX_STATE = 200


def _edition_name(name, year):
    if (not isinstance(name, str) or not 7 <= len(name) <= MAX_TITLE
            or not isinstance(year, int) or isinstance(year, bool)
            or not 2026 <= year <= 2049):
        return None
    years = {int(x) for x in re.findall(r"(?<![0-9])20[2-4][0-9](?![0-9])", name)}
    if years and years != {year}:
        return None
    title = name.strip()
    if not title or len(normalized(title)) < 7:
        return None
    return title if re.search(r"(?<![0-9])20[2-4][0-9]$", title) else title + " " + str(year)


def _published(published, title, year):
    name = normalized(re.sub(r"\s+20[2-4][0-9]$", "", title))
    for row in published["festivals"]:
        if not isinstance(row, dict):
            continue
        published_name = normalized(re.sub(
            r"\s+20[2-4][0-9]$", "", str(row.get("name") or "")))
        try:
            published_year = date.fromisoformat(row["startDate"]).year
        except (TypeError, ValueError, KeyError):
            continue
        if name == published_name and published_year == year:
            return True
    return False


def _eligible(queue, published, today):
    current = date.fromisoformat(today)
    if (not isinstance(queue, dict) or queue.get("schema") != QUEUE_SCHEMA
            or queue.get("as_of") != today
            or queue.get("review_only") is not True
            or queue.get("safe_to_publish") is not False
            or queue.get("publication_authorized") is not False
            or not isinstance(queue.get("dossiers"), list)
            or len(queue["dossiers"]) > MAX_DOSSIERS
            or not isinstance(published, dict)
            or published.get("schema") != 1
            or not isinstance(published.get("festivals"), list)):
        raise ValueError("Unsafe national generic source input")
    result, seen = [], set()
    for dossier in queue["dossiers"]:
        if (not isinstance(dossier, dict)
                or dossier.get("publication_authorized") is not False
                or dossier.get("safe_to_publish") is not False
                or not isinstance(dossier.get("id"), str)
                or not re.fullmatch(r"national-[a-z0-9-]{8,120}", dossier["id"])
                or not isinstance(dossier.get("sources"), list)
                or len(dossier["sources"]) > MAX_SOURCES_PER_DOSSIER):
            continue
        year = dossier.get("edition_year_hint")
        name = _edition_name(dossier.get("name_hint"), year)
        if (name is None or not current.year <= year <= current.year + 3
                or _published(published, name, year)):
            continue
        for source in dossier["sources"]:
            if (not isinstance(source, dict)
                    or source.get("kind") not in TRUSTED_RESEARCH_KINDS
                    or source.get("publication_authorized") is not False):
                continue
            url = source.get("url")
            if (safe_public_url(url) is None
                    or source.get("discovered_via") != url):
                continue
            try:
                first = date.fromisoformat(source["firstSeen"])
                last = date.fromisoformat(source["lastSeen"])
            except (ValueError, TypeError, KeyError):
                continue
            if (not first <= last <= current
                    or (current - last).days > 7
                    or (name, url) in seen):
                continue
            seen.add((name, url))
            result.append({
                "dossier_id": dossier["id"], "url": url,
                "title": name, "year": year,
            })
    return sorted(result, key=lambda x: (x["title"], x["url"]))


def _digest(source, start, end, proof_mode):
    return sha256(json.dumps({
        "title": source["title"], "url": source["url"],
        "year": source["year"], "start": start, "end": end,
        "proof_mode": proof_mode,
    }, sort_keys=True).encode("utf-8")).hexdigest()


def _visible_date_ranges(html, year):
    """Find explicit dates anywhere on a candidate page before a fallback.

    An old/deep page with contradictory *visible* edition-year dates must
    never be overridden by a convenient homepage claim. Hidden scripts do
    not qualify as visible proof.
    """
    parser = VisibleText()
    parser.feed(html)
    parser.close()
    visible = " ".join(fold(" ".join(parser.parts)).split())
    return {(a, b) for _start, _end, a, b in explicit_ranges(visible, year)}


def _private_date_rejection_code(html, title, year):
    """Explain rejection without exporting untrusted HTML or relaxing any gate."""
    parser = VisibleText()
    parser.feed(html)
    parser.close()
    visible = " ".join(fold(" ".join(parser.parts)).split())
    if not visible:
        return "NO_VISIBLE_HTML_TEXT"
    dates = _visible_date_ranges(html, year)
    if not dates:
        return ("CURRENT_EDITION_YEAR_NOT_VISIBLE" if str(year) not in visible
                else "NO_EXPLICIT_VISIBLE_DATE_RANGE")
    dominant = dominant_visible_range(dates)
    if dominant is None:
        return "CONFLICTING_VISIBLE_DATE_RANGES"
    first, last = dominant
    if not visible_official_edition(html, title, first, last):
        return "FESTIVAL_IDENTITY_DATE_PROXIMITY_NOT_PROVEN"
    if not no_same_edition_jsonld_contradiction(html, title, first, last):
        return "SAME_EDITION_STRUCTURED_CONTRADICTION"
    return "STRICT_EDITION_VALIDATION_REJECTED"


def _bounded_same_host_home(source_url):
    """Exactly the homepage of the already-vetted candidate host, never a new host."""
    if safe_public_url(source_url) is None:
        return None
    parts = urlsplit(source_url)
    if parts.path in ("", "/"):
        return None
    home = "https://" + parts.hostname + "/"
    return home if safe_public_url(home) == home else None


def _recheck_current_dates(source, primary_html, fetch):
    """Try one extra same-host homepage only if the detail has NO dates.

    Private research only. Both pages must be non-contradictory; neither
    certifies official site ownership or publisher approval.
    """
    title, year = source["title"], source["year"]
    dates = institutional_date(primary_html, title, year)
    if dates is not None:
        return dates, "SOURCE_PAGE", None, "SOURCE_PAGE"
    primary_code = _private_date_rejection_code(primary_html, title, year)
    home = _bounded_same_host_home(source["url"])
    if home is None or _visible_date_ranges(primary_html, year):
        return None, None, primary_code, "SOURCE_PAGE"
    homepage_html = fetch(home)
    dates = institutional_date(homepage_html, title, year)
    if dates is None:
        return (None, None,
                _private_date_rejection_code(homepage_html, title, year),
                "SAME_HOST_HOME")
    if not no_same_edition_jsonld_contradiction(
            primary_html, title, *dates):
        return None, None, "SOURCE_STRUCTURED_CONTRADICTION", "SOURCE_PAGE"
    return dates, "SAME_HOST_HOME", None, "SAME_HOST_HOME"


def examine(state, queue, published, today, fetch=None):
    current = date.fromisoformat(today)
    if (not isinstance(state, dict)
            or state.get("schema") != "grossesondes.source-watch.v1"):
        raise ValueError("Unsafe national watch state")
    observed = state.setdefault(STATE_KEY, {})
    if not isinstance(observed, dict) or len(observed) > MAX_STATE:
        raise ValueError("Unsafe national generic observation state")
    eligible = _eligible(queue, published, today)
    keys = {x["url"] for x in eligible}
    for key in list(observed):
        if key not in keys:
            del observed[key]
    yesterday = (current - timedelta(days=1)).isoformat()
    # Give first-day reports a chance to get their independent next-day
    # recheck; otherwise rotate candidates in two-day windows.
    pending = [x for x in eligible if isinstance(observed.get(x["url"]), dict)
               and observed[x["url"]].get("lastSeen") == yesterday
               and observed[x["url"]].get("firstSeen") == yesterday]
    other = [x for x in eligible if x not in pending]
    # A second scheduled collection on the same day must probe NEW leads,
    # not waste both slots on leads already read that morning.
    # An unsuccessful source was previously never recorded and could consume
    # both public slots on the same day. Track attempts separately from
    # successful evidence; a failed attempt NEVER carries a proof digest.
    def checked_today(source):
        previous = observed.get(source["url"])
        return (isinstance(previous, dict)
                and previous.get("lastChecked", previous.get("lastSeen")) == today)
    fresh = [x for x in other if not checked_today(x)]
    repeated = [x for x in other if x not in fresh]
    def rotate(rows):
        if not rows:
            return rows
        offset = (current.toordinal() // 2 * MAX_CHECKS) % len(rows)
        return rows[offset:] + rows[:offset]
    selected = (pending + rotate(fresh) + rotate(repeated))[:MAX_CHECKS]
    read = fetch_public_html if fetch is None else fetch
    rows = []
    for source in selected:
        url = source["url"]
        old = observed.pop(url, None)
        row = {
            "dossier_id": source["dossier_id"],
            "status": "GENERIC_PRIMARY_DATE_NOT_RECONFIRMED",
            "review_only": True, "safe_to_publish": False,
            "publication_authorized": False,
            "ownership_proven": False,
            "official_site_authorized": False,
            "publisher_gate_connected": False,
            "two_day_dates": False,
            "start_date_hint": None, "end_date_hint": None,
            "date_source_mode": None,
            "diagnostic_code": None, "diagnostic_surface": None,
            "visible_range_count_review_only": 0,
            "visible_ranges_review_only": [],
        }
        try:
            html = read(url)
            dates, proof_mode, rejection_code, rejection_surface = (
                _recheck_current_dates(source, html, read))
            if dates is None:
                row["status"] = "EXPLICIT_CURRENT_EDITION_DATES_NOT_FOUND"
                row["diagnostic_code"] = rejection_code
                row["diagnostic_surface"] = rejection_surface
            elif (dates[0] < current
                  or dates[0].year != source["year"]
                  or dates[1].year != source["year"]):
                row["status"] = "EXPLICIT_CURRENT_EDITION_DATES_NOT_FOUND"
                row["diagnostic_code"] = "NOT_FUTURE_OR_WRONG_EDITION_YEAR"
                row["diagnostic_surface"] = proof_mode
            elif not no_same_edition_jsonld_contradiction(
                    html, source["title"], *dates):
                row["status"] = "EXPLICIT_CURRENT_EDITION_DATES_NOT_FOUND"
                row["diagnostic_code"] = "SOURCE_STRUCTURED_CONTRADICTION"
                row["diagnostic_surface"] = "SOURCE_PAGE"
            else:
                first, last = (x.isoformat() for x in dates)
                digest = _digest(source, first, last, proof_mode)
                same = (isinstance(old, dict) and old.get("digest") == digest
                        and old.get("lastSeen") in (today, yesterday)
                        and isinstance(old.get("firstSeen"), str))
                try:
                    first_seen = date.fromisoformat(
                        old["firstSeen"]) if same else current
                    continuous = (same and first_seen < current
                                  and old["lastSeen"] == yesterday)
                except (ValueError, TypeError):
                    first_seen, continuous = current, False
                observed[url] = {
                    "digest": digest, "firstSeen": first_seen.isoformat(),
                    "lastSeen": today, "lastChecked": today,
                }
                row["status"] = (
                    "TWO_DAY_GENERIC_PRIMARY_DATES_RECHECKED_PRIVATE"
                    if continuous else "FIRST_DAY_GENERIC_PRIMARY_DATES_REVIEW_ONLY")
                row["two_day_dates"] = continuous
                row["start_date_hint"], row["end_date_hint"] = first, last
                row["date_source_mode"] = proof_mode
            if (row["diagnostic_code"] == "CONFLICTING_VISIBLE_DATE_RANGES"
                    and row["diagnostic_surface"] == "SOURCE_PAGE"):
                # Bounded ISO dates only; never export HTML, URLs or private
                # observations to the public publisher.
                ranges = sorted(_visible_date_ranges(html, source["year"]))
                row["visible_range_count_review_only"] = len(ranges)
                row["visible_ranges_review_only"] = [
                    {"start":a.isoformat(), "end":b.isoformat()}
                    for a, b in ranges[:8]]
        except (OSError, ValueError, UnicodeError, TypeError, KeyError):
            row["status"] = "GENERIC_PRIMARY_HTTPS_UNAVAILABLE"
            row["diagnostic_code"] = "SECURE_FETCH_OR_HTML_PARSE_FAILED"
        # Negative outcomes must advance today's rotation, but can never be
        # re-used as first-day positive evidence on a later collection.
        if url not in observed:
            observed[url] = {"lastChecked": today}
        rows.append(row)
    return {
        "schema": SCHEMA, "as_of": today,
        "review_only": True, "safe_to_publish": False,
        "publication_authorized": False, "ownership_proven": False,
        "official_site_authorized": False, "publications": 0,
        "eligible_source_count": len(eligible),
        "checked_count": len(rows),
        "two_day_dates_count": sum(x["two_day_dates"] for x in rows),
        "rows": rows,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--intake", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    args = parser.parse_args()
    folder = args.intake
    today = datetime.now(ZoneInfo("Europe/Paris")).date().isoformat()
    def read(path):
        return json.loads(path.read_text(encoding="utf-8"))
    state_path = folder / "source-watch-state.json"
    state = read(state_path)
    report = examine(
        state,
        read(folder / "national-festival-discovery-review.json"),
        read(args.catalog), today)
    state_path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (folder / "national-generic-primary-date-review.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print("Generic national first-party date research: eligible="
          + str(report["eligible_source_count"]) + ", checked="
          + str(report["checked_count"]) + ", two-day="
          + str(report["two_day_dates_count"]) + ", publications=0")


if __name__ == "__main__":
    main()
