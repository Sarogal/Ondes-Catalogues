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
from urllib.parse import unquote, urljoin, urlsplit

from dns_pinned_https import safe_public_url, fetch_public_html
from source_qualification import Anchors, normalized

SCRIPTS = str(Path(__file__).resolve().parents[1] / "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
from grossesondes_institutional_edition import institutional_date
from grossesondes_official_html_edition import (VisibleText, VisibleParagraphs,
                                               fold, explicit_ranges,
                                               visible_official_edition,
                                               dominant_visible_range, CANCEL)
from grossesondes_structured_edition import no_same_edition_jsonld_contradiction
from grossesondes_archived_html_intake import latest_patch, atomic_json
from grossesondes_generic_directory_edition import (
    private_proposal as directory_private_proposal,
    discover_directory_website, directory_url, verify_official_site_pages,
    visible_adjacent_edition_dates, unique_current_edition_visible_dates,
)
from grossesondes_institutional_edition import conflicts_with_signed_catalogue
from grossesondes_venue_reciprocal_edition import (
    verified_venue_reciprocity,
    private_proposal as venue_private_proposal,
    validate_private_proposal as validate_venue_private_proposal,
    safe_root as safe_venue_root, first_party_hero_hint,
)
from grossesondes_first_party_direct_edition import (
    verify_first_party_claims,
    private_proposal as direct_private_proposal,
    validate_private_proposal as validate_direct_private_proposal,
)

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
                "title": name, "year": year, "kind": source["kind"],
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


MAX_LINKED_EDITION_READS = 3


def _safe_same_host_edition_links(
        html, home, year, *, allow_index=True, today=None):
    """Only visible links from a fetched first-party page; no closed URL list.

    Names/year select RESEARCH surfaces, never authorize publisher traffic.
    The DNS-pinned client independently validates every requested hostname.
    """
    if (safe_public_url(home) != home or not isinstance(html, str)
            or not 0 < len(html) <= 650_000 or type(year) is not int):
        return []
    parser = Anchors()
    try:
        parser.feed(html)
        parser.close()
    except (TypeError, ValueError, UnicodeError):
        return []
    host = urlsplit(home).hostname
    selected = {}
    for href, label, _prefix in parser.anchors[:250]:
        if not isinstance(href, str) or not 0 < len(href) <= 900:
            continue
        try:
            raw = urljoin(home, href)
            parts = urlsplit(raw)
            path = unquote(parts.path)
            if (parts.scheme != "https" or parts.hostname != host
                    or parts.query or parts.fragment or parts.port
                    or parts.username or parts.password
                    or path in ("", "/")
                    or any(p in (".", "..") for p in path.split("/"))
                    or re.search(r"%(?:2e|2f|5c|00)", parts.path, re.I)
                    or safe_public_url(raw) != raw):
                continue
            label_text = normalized(str(label))
            destination = normalized(path.replace("-", " ").replace("_", " "))
            markers = re.findall(r"(?<![0-9])20[2-4][0-9](?![0-9])",
                                 label_text + " " + destination)
            if markers and set(markers) != {str(year)}:
                continue
            year_link = str(year) in markers
            news_index = bool(re.search(
                r"(?:/|^)(?:actualites?|actu|news|articles?|nouvelles?)(?:/|$)",
                path.casefold()))
            if not year_link and (not allow_index or not news_index):
                continue
            # Explicit edition year first; retain one index for dated news
            # when an organizer homepage is only a marketing landing page.
            selected[raw] = 0 if year_link else 1
        except (TypeError, ValueError, UnicodeError):
            continue
    ranked = sorted(selected, key=lambda url: (selected[url], len(url), url))
    years = [url for url in ranked if selected[url] == 0]
    indexes = [url for url in ranked if selected[url] == 1]
    # A fixed first-two-page rule would create another CLOSED inventory:
    # rotate every week so any number of year-specific links can be checked
    # over successive runs while the selection stays stable long enough
    # for the mandatory next-day recheck.
    if len(years) > 2 and today is not None:
        week = date.fromisoformat(today).toordinal() // 7
        offset = (week * 2) % len(years)
        years = years[offset:] + years[:offset]
    return years[:2] + (indexes[:1] if allow_index else [])




def _named_weekend_statement(html, title, year, target):
    """Exact festival-name/weekend in one visible block, with no other named day.

    This is a narrowly scoped same-domain corroboration for sites carrying
    unrelated calendar dates elsewhere. It cannot infer a date from metadata
    or one separated title/date block, and cannot override a contradiction
    explicitly associated with the named edition.
    """
    parser = VisibleParagraphs()
    parser.feed(html)
    parser.close()
    tokens = re.findall(
        r"[a-z0-9]+", re.sub(r"\b20[2-4][0-9]\b", "", fold(title)))
    if not tokens:
        return False
    exact = re.compile(
        r"(?<![a-z0-9])" + r"[\W_]+".join(map(re.escape, tokens)) +
        r"(?![a-z0-9])")
    proven = False
    for raw in " ".join(parser.parts).split(VisibleParagraphs.SEP):
        block = " ".join(fold(raw).split())
        if (not 0 < len(block) <= 1600 or not exact.search(block)
                or str(year) not in block):
            continue
        if CANCEL.search(block):
            return False
        dates = {(first, last) for _a, _b, first, last
                 in explicit_ranges(block, year)}
        if any((interval != target and not
                (interval[0] == interval[1] and
                 target[0] <= interval[0] <= target[1]))
               for interval in dates):
            return False
        if target in dates:
            proven = True
    return proven



def _recover_official_weekend_amid_isolated_days(source, primary_html,
                                                  fetch, today):
    """Distinguish an actual weekend from isolated dates on the SAME site.

    This is NOT a second-source requirement. It applies only when a deep
    official page has one uniquely visible multi-day weekend plus unrelated
    single-day mentions, and the SAME official host's homepage explicitly
    announces that exact weekend. Two disjoint multi-day windows, a canceled
    announcement, any different official homepage date or same-edition
    contradictory JSON-LD remain strict vetoes.
    """
    home = _bounded_same_host_home(source["url"])
    if home is None or CANCEL.search(_normalized_visible(primary_html)):
        return None
    title, year = source["title"], source["year"]
    ranges = _visible_date_ranges(primary_html, year)
    multi = {(first, last) for first, last in ranges if first < last}
    if len(multi) != 1 or len(ranges) < 2:
        return None
    target = next(iter(multi))
    if any((first, last) != target and first != last
           for first, last in ranges):
        return None
    if not no_same_edition_jsonld_contradiction(
            primary_html, title, *target):
        return None
    # A day named as *this festival's* official date is a contradiction,
    # even if another first-party page also mentions the weekend.
    p = VisibleParagraphs()
    p.feed(primary_html)
    p.close()
    tokens = re.findall(
        r"[a-z0-9]+", re.sub(r"\b20[2-4][0-9]\b", "",
                              fold(title)))
    exact = (re.compile(r"(?<![a-z0-9])" +
                        r"[\W_]+".join(map(re.escape, tokens)) +
                        r"(?![a-z0-9])")
             if tokens else None)
    for raw in " ".join(p.parts).split(VisibleParagraphs.SEP):
        block = " ".join(fold(raw).split())
        if CANCEL.search(block):
            return None
        if (exact is None or not exact.search(block)
                or str(year) not in block):
            continue
        for _a, _b, first, last in explicit_ranges(block, year):
            if first == last and not target[0] <= first <= target[1]:
                return None
    # This is a DNS-pinned, SAME-host recheck, not a lookup of an
    # organizer/venue/annuaire. Never follow another host here.
    homepage = fetch(home)
    if CANCEL.search(_normalized_visible(homepage)):
        return None
    from grossesondes_generic_directory_edition import (
        unique_current_edition_visible_dates, visible_adjacent_edition_dates,
    )
    homepage_dates = institutional_date(homepage, title, year)
    if homepage_dates is None:
        homepage_dates = unique_current_edition_visible_dates(
            homepage, title, year, today)
    if homepage_dates is None:
        homepage_dates = visible_adjacent_edition_dates(
            homepage, title, year, today)
    if homepage_dates is None:
        from grossesondes_first_party_direct_edition import first_party_hero_hint
        homepage_dates = first_party_hero_hint(homepage, title, today)
        if homepage_dates is not None:
            homepage_dates = tuple(date.fromisoformat(x)
                                   for x in homepage_dates)
    # A homepage may also mention an unrelated SINGLE calendar date.
    # Accept the exact current weekend only when one visible paragraph
    # explicitly names this festival and dates, and no same-name paragraph
    # contains a different edition date. No external source is involved.
    named_statement = _named_weekend_statement(
        homepage, title, year, target)
    if homepage_dates is None and named_statement:
        homepage_dates = target
    if (homepage_dates != target
            or not no_same_edition_jsonld_contradiction(
                homepage, title, *target)
            or not (visible_official_edition(
                    homepage, title, *target) or named_statement)):
        return None
    return target


def _normalized_visible(html):
    parser = VisibleText()
    parser.feed(html)
    parser.close()
    return " ".join(fold(" ".join(parser.parts)).split())


def _recheck_current_dates(source, primary_html, fetch, today):
    """Bounded same-host edition research when source page lacks explicit dates.

    No private candidate URL other than its already DNS-pinned same host is
    promoted. Missing/contradictory visible year dates forbid any fallback.
    A changed article path creates a NEW proof digest and resets J+1 evidence.
    """
    title, year = source["title"], source["year"]
    dates = institutional_date(primary_html, title, year)
    if dates is None:
        dates = unique_current_edition_visible_dates(
            primary_html, title, year, today)
    if dates is not None:
        return dates, "SOURCE_PAGE", None, "SOURCE_PAGE"
    weak_hero_dates = first_party_hero_hint(primary_html, title, today)
    if weak_hero_dates is not None:
        # Observation ONLY: J+1 itself cannot promote this unadjacent hero.
        # Only an independently verified external venue site with an exact
        # dated concert page and a backlink may eventually authorize it.
        return tuple(date.fromisoformat(x) for x in weak_hero_dates), (
            "SOURCE_HERO_REQUIRES_VENUE_BACKLINK"), None, "SOURCE_PAGE"
    primary_code = _private_date_rejection_code(primary_html, title, year)
    primary_ranges = _visible_date_ranges(primary_html, year)
    if primary_ranges:
        # Generic pages can mention an official festival weekend AND a
        # lone unrelated calendar day. Never discard a clear FIRST-PARTY
        # weekend solely because of such ancillary dates, but require the
        # same festival's own homepage to announce that exact interval.
        # Two distinct festival weekends still fail without extra fetching.
        if (primary_code == "CONFLICTING_VISIBLE_DATE_RANGES"
                and _bounded_same_host_home(source["url"]) is not None
                and len({d for d in primary_ranges if d[0] < d[1]}) == 1):
            restored = _recover_official_weekend_amid_isolated_days(
                source, primary_html, fetch, today)
            if restored is not None:
                return restored, "SAME_HOST_WEEKEND_RECONCILED", None, (
                    "SAME_HOST_HOME")
        return None, None, primary_code, "SOURCE_PAGE"
    from urllib.parse import urlsplit
    origin = source["url"]
    parts = urlsplit(origin)
    home = "https://" + parts.hostname + "/"
    if safe_public_url(home) != home:
        return None, None, primary_code, "SOURCE_PAGE"
    if parts.path in ("", "/"):
        homepage_html = primary_html
    else:
        homepage_html = fetch(home)
    homepage_dates = institutional_date(homepage_html, title, year)
    if homepage_dates is None:
        homepage_dates = unique_current_edition_visible_dates(
            homepage_html, title, year, today)
    if homepage_dates is None:
        homepage_dates = visible_adjacent_edition_dates(
            homepage_html, title, year, today)
    if homepage_dates is None:
        weak_hero_dates = first_party_hero_hint(
            homepage_html, title, today)
        if weak_hero_dates is not None:
            homepage_dates = tuple(
                date.fromisoformat(x) for x in weak_hero_dates)
    if homepage_dates is not None:
        if not no_same_edition_jsonld_contradiction(
                primary_html, title, *homepage_dates):
            return None, None, "SOURCE_STRUCTURED_CONTRADICTION", "SOURCE_PAGE"
        return homepage_dates, "SAME_HOST_HOME", None, "SAME_HOST_HOME"
    home_code = _private_date_rejection_code(homepage_html, title, year)
    if _visible_date_ranges(homepage_html, year):
        return None, None, home_code, "SAME_HOST_HOME"
    # Read no more than three additional same-domain links, with ONE
    # possible second-level news article. All candidate URLs are rederived
    # from fetched first-party anchors and independently DNS-pinned.
    selected = _safe_same_host_edition_links(
        homepage_html, home, year, allow_index=True, today=today)
    remaining = MAX_LINKED_EDITION_READS
    accepted = []
    visited = {origin, home}
    pending = selected[:]
    while pending and remaining:
        link = pending.pop(0)
        if link in visited:
            continue
        visited.add(link)
        remaining -= 1
        page = fetch(link)
        interval = institutional_date(page, title, year)
        if interval is None:
            interval = unique_current_edition_visible_dates(
                page, title, year, today)
        if interval is None:
            interval = visible_adjacent_edition_dates(page, title, year, today)
        if interval is not None:
            if (not no_same_edition_jsonld_contradiction(
                    primary_html, title, *interval)
                    or not no_same_edition_jsonld_contradiction(
                        homepage_html, title, *interval)):
                return None, None, "SOURCE_STRUCTURED_CONTRADICTION", "SOURCE_PAGE"
            accepted.append((interval, link))
        elif _visible_date_ranges(page, year):
            # An explicit contradictory date in visited first-party material
            # cannot be silently replaced by a convenient later article.
            return (None, None,
                    _private_date_rejection_code(page, title, year),
                    "SAME_HOST_EDITION_ARTICLE")
        else:
            # The top-level news index can introduce a dated 2027 article,
            # without a hardcoded article path or organizer list.
            if remaining and not re.search(r"(?<![0-9])" + str(year) +
                                           r"(?![0-9])", link):
                pending.extend(
                    u for u in _safe_same_host_edition_links(
                        page, home, year, allow_index=False, today=today)
                    if u not in visited and u not in pending)
    unique = {tuple(d) for d, _url in accepted}
    if len(unique) != 1:
        return None, None, home_code, "SAME_HOST_HOME"
    dates = next(iter(unique))
    chosen_url = next(u for d, u in accepted if tuple(d) == dates)
    # A stable digest must bind the exact independently fetched path,
    # so a different article cannot borrow a previous day's observation.
    mode = "SAME_HOST_EDITION_ARTICLE:" + sha256(
        chosen_url.encode("utf-8")).hexdigest()[:16]
    return dates, mode, None, "SAME_HOST_EDITION_ARTICLE"


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
                _recheck_current_dates(source, html, read, today))
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
                    prior_first = date.fromisoformat(
                        old["firstSeen"]) if same else current
                    if prior_first >= current:
                        continuous = False
                    elif old.get("lastSeen") == yesterday:
                        # Two consecutive civil days are compulsory. A J1
                        # observation separated by a missed day is not J+1.
                        continuous = (old.get("firstSeen") == yesterday
                                      or old.get("stable") is True)
                    else:
                        # Repeated same-day runs preserve a certified J+1.
                        # Migration: pre-#551 records carried firstSeen and
                        # lastSeen but lacked the new 'stable' field. The
                        # exact consecutive-day pair (yesterday, today)
                        # already proves both distinct civil observations.
                        # Explicit stable=False always remains a veto.
                        continuous = (
                            old.get("stable") is True
                            or (old.get("stable") is None
                                and old.get("firstSeen") == yesterday)
                        )
                    first_seen = prior_first if continuous else current
                except (ValueError, TypeError):
                    first_seen, continuous = current, False
                observed[url] = {
                    "digest": digest, "firstSeen": first_seen.isoformat(),
                    "lastSeen": today, "lastChecked": today,
                    "stable": continuous,
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



def stable_directory_proposals(state, queue, catalog, report, today,
                               directory_fetch=fetch_public_html,
                               organizer_fetch=fetch_public_html):
    """Require J+1 genuine private evidence AND a fresh independent directory.

    This is NOT an approval. The public publisher must re-fetch the independent
    directory and re-check exact official dates, genre and collisions itself.
    """
    if (not isinstance(report, dict) or report.get("schema") != SCHEMA
            or report.get("as_of") != today
            or report.get("review_only") is not True
            or report.get("safe_to_publish") is not False
            or report.get("publication_authorized") is not False
            or report.get("publications") != 0
            or not isinstance(report.get("rows"), list)
            or len(report["rows"]) > MAX_CHECKS):
        raise ValueError("Untrusted generic first-party report")
    records = state.get(STATE_KEY, {})
    if not isinstance(records, dict):
        raise ValueError("Missing private date observations")
    sources = _eligible(queue, catalog, today)
    proposals = []
    seen = set()
    for row in report["rows"]:
        if (not isinstance(row, dict)
                or row.get("status") !=
                        "TWO_DAY_GENERIC_PRIMARY_DATES_RECHECKED_PRIVATE"
                or row.get("two_day_dates") is not True
                or row.get("publication_authorized") is not False
                or row.get("ownership_proven") is not False):
            continue
        dates = row.get("start_date_hint"), row.get("end_date_hint")
        candidates = []
        for source in sources:
            if (source["dossier_id"] != row.get("dossier_id")
                    # Both kinds have already passed _eligible's strict
                    # origin and HTTPS checks. Historical homepages are ONLY
                    # observations; the independent directory, dates and
                    # Publisher recheck still decide any authority.
                    or source.get("kind") not in TRUSTED_RESEARCH_KINDS
                    or directory_url(source["title"]) is None):
                continue
            old = records.get(source["url"])
            if (not isinstance(old, dict)
                    or old.get("stable") is not True
                    or old.get("lastSeen") != today
                    or old.get("digest") != _digest(
                        source, *dates, row.get("date_source_mode"))):
                continue
            try:
                if not date.fromisoformat(old["firstSeen"]) < date.fromisoformat(today):
                    continue
            except (TypeError, ValueError, KeyError):
                continue
            # The observed proof may live at /programmation/ or an article.
            # The independently reviewed directory identifies a SITE, not
            # that untrusted research path. Reconstruct only its HTTPS root;
            # never pass the deep private URL as publication authority.
            host = urlsplit(source["url"]).hostname
            site_root = "https://" + host + "/" if host else ""
            if (safe_public_url(site_root) != site_root
                    or site_root in seen):
                continue
            proposed = directory_private_proposal(
                source["title"], site_root, dates, today)
            if proposed is not None:
                candidates.append(proposed)
        if len(candidates) != 1:
            continue
        proposal = candidates[0]
        # Neither the private candidate URL nor its proposed domain can
        # choose the directory destination. Two bounded NAME-derived path
        # shapes are supported, including common hyphenated aliases.
        directory_ref, site = discover_directory_website(
            proposal["name"], directory_fetch)
        if site != proposal["officialSite"]:
            continue
        # A deep-page date alone cannot pass the root-only Publisher proof.
        # Check the independently derived homepage NOW as well; the cloud
        # Publisher will re-fetch this site independently before publication.
        try:
            homepage = organizer_fetch(site)
            if verify_official_site_pages(
                    site, homepage, proposal["name"],
                    int(proposal["name"].rsplit(" ", 1)[-1]), today,
                    fetch=organizer_fetch) != dates:
                continue
        except (OSError, ValueError, TypeError, UnicodeError, KeyError):
            continue
        # Carry exactly the independently rederived directory origin so that
        # the Publisher checks the same page again on its own runner.
        proven = directory_private_proposal(
            proposal["name"], proposal["officialSite"],
            (proposal["startDate"], proposal["endDate"]), today,
            directory_ref=directory_ref)
        if proven is None:
            continue
        proposals.append(proven)
        seen.add(proven["officialSite"])
    return proposals


def append_directory_proposals(folder, catalog, history, state, queue,
                               report, today, directory_fetch=fetch_public_html):
    if (not isinstance(history, dict) or history.get("schema") != 2
            or not isinstance(history.get("knownFestivals"), list)):
        raise ValueError("Unsafe festival history")
    proposals = stable_directory_proposals(
        state, queue, catalog, report, today, directory_fetch=directory_fetch)
    if not proposals:
        return 0
    patch = latest_patch(folder, date.fromisoformat(today))
    occupied = {row.get("slug") for row in patch["additions"]
                if isinstance(row, dict)}
    added = 0
    for row in proposals:
        if (len(patch["additions"]) >= 100 or row["slug"] in occupied
                or conflicts_with_signed_catalogue(
                    row, catalog["festivals"], history["knownFestivals"])):
            continue
        patch["additions"].append(row)
        occupied.add(row["slug"])
        added += 1
    if added:
        patch["generated_at"] = today
        atomic_json(folder / ("patch-" + today + ".json"), patch)
    return added




def stable_first_party_direct_proposals(state, queue, catalog, report, today,
                                         fetch=fetch_public_html, limit=2):
    """Direct pathway: re-fetch the official site, not a second date source.

    J/J+1 is a PRIVATE stability observation of the SAME first-party website,
    not third-party confirmation. The Publisher independently re-downloads
    and compares current-edition dates before any append-only publication.
    """
    if (not isinstance(report, dict) or report.get("schema") != SCHEMA
            or report.get("as_of") != today
            or report.get("review_only") is not True
            or report.get("safe_to_publish") is not False
            or report.get("publication_authorized") is not False
            or report.get("publications") != 0
            or not isinstance(report.get("rows"), list)
            or len(report["rows"]) > MAX_CHECKS
            or type(limit) is not int or not 0 <= limit <= 2):
        raise ValueError("Unsafe primary-only proposal research")
    records = state.get(STATE_KEY, {})
    if not isinstance(records, dict):
        raise ValueError("Untrusted primary proof registry")
    options = _eligible(queue, catalog, today)
    proposals, seen, checked = [], set(), 0
    for row in report["rows"]:
        if checked >= limit:
            break
        if (not isinstance(row, dict)
                or row.get("status") !=
                    "TWO_DAY_GENERIC_PRIMARY_DATES_RECHECKED_PRIVATE"
                or row.get("two_day_dates") is not True
                or row.get("publication_authorized") is not False
                or row.get("ownership_proven") is not False):
            continue
        dates = row.get("start_date_hint"), row.get("end_date_hint")
        for source in options:
            if source["dossier_id"] != row.get("dossier_id"):
                continue
            old = records.get(source["url"])
            if (not isinstance(old, dict) or old.get("stable") is not True
                    or old.get("lastSeen") != today
                    or old.get("digest") != _digest(
                        source, *dates, row.get("date_source_mode"))):
                continue
            try:
                if not date.fromisoformat(old["firstSeen"]) < date.fromisoformat(today):
                    continue
            except (ValueError, TypeError, KeyError):
                continue
            host = urlsplit(source["url"]).hostname
            site = "https://" + host + "/" if host else None
            if site is None or safe_venue_root(site) is None or site in seen:
                continue
            checked += 1
            try:
                primary_claim = verify_first_party_claims(
                    site, source["title"], today, fetch=fetch)
                if primary_claim is None or primary_claim[0] != tuple(dates):
                    continue
                # A city on the official current-edition date block is
                # sufficient editorial evidence; map coordinates are not
                # invented. No second date or place source is required.
                proposal = direct_private_proposal(
                    source["title"], site, dates, today,
                    city=primary_claim[1])
                if (proposal is None
                        or validate_direct_private_proposal(
                            proposal, today) is None):
                    continue
                proposals.append(proposal)
                seen.add(site)
            except (OSError, ValueError, TypeError, UnicodeError, KeyError):
                continue
            break
    return proposals


def append_direct_first_party_proposals(
        folder, catalog, history, state, queue, report, today,
        fetch=fetch_public_html):
    if (not isinstance(history, dict) or history.get("schema") != 2
            or not isinstance(history.get("knownFestivals"), list)):
        raise ValueError("Unsafe historical reference")
    additions = stable_first_party_direct_proposals(
        state, queue, catalog, report, today, fetch=fetch)
    if not additions:
        return 0
    patch = latest_patch(folder, date.fromisoformat(today))
    used = {row.get("slug") for row in patch["additions"]
            if isinstance(row, dict)}
    n = 0
    for row in additions:
        if (len(patch["additions"]) >= 100 or row["slug"] in used
                or conflicts_with_signed_catalogue(
                    row, catalog["festivals"], history["knownFestivals"])):
            continue
        patch["additions"].append(row)
        used.add(row["slug"])
        n += 1
    if n:
        patch["generated_at"] = today
        atomic_json(folder / ("patch-" + today + ".json"), patch)
    return n



def stable_reciprocal_venue_proposals(state, queue, catalog, report, today,
                                       fetch=fetch_public_html, limit=2):
    """Rescue primary editions whose first-party domain lacks a directory.

    The J+1 national primary observation is only eligibility, not authority.
    We independently fetch the official site AND an unregistered venue
    website (discovered only from official practical info), verify a dated
    venue event with an actual backlink to the festival, and emit PRIVATE
    additions. The Publisher repeats every remote proof on its own runner.
    """
    if (not isinstance(report, dict) or report.get("schema") != SCHEMA
            or report.get("as_of") != today
            or report.get("review_only") is not True
            or report.get("safe_to_publish") is not False
            or report.get("publication_authorized") is not False
            or report.get("publications") != 0
            or not isinstance(report.get("rows"), list)
            or len(report["rows"]) > MAX_CHECKS
            or type(limit) is not int or not 0 <= limit <= 2):
        raise ValueError("Unsafe generic venue proposal research")
    records = state.get(STATE_KEY, {})
    if not isinstance(records, dict):
        raise ValueError("Untrusted date observation state")
    options = _eligible(queue, catalog, today)
    proposals, seen, consumed = [], set(), 0
    for row in report["rows"]:
        if consumed >= limit:
            break
        if (not isinstance(row, dict)
                or row.get("status") !=
                    "TWO_DAY_GENERIC_PRIMARY_DATES_RECHECKED_PRIVATE"
                or row.get("two_day_dates") is not True
                or row.get("publication_authorized") is not False
                or row.get("ownership_proven") is not False):
            continue
        dates = row.get("start_date_hint"), row.get("end_date_hint")
        for source in options:
            if source["dossier_id"] != row.get("dossier_id"):
                continue
            old = records.get(source["url"])
            if (not isinstance(old, dict)
                    or old.get("stable") is not True
                    or old.get("lastSeen") != today
                    or old.get("digest") != _digest(
                        source, *dates, row.get("date_source_mode"))):
                continue
            try:
                if not date.fromisoformat(old["firstSeen"]) < date.fromisoformat(today):
                    continue
            except (ValueError, TypeError, KeyError):
                continue
            host = urlsplit(source["url"]).hostname
            site = "https://" + host + "/" if host else None
            if site is None or safe_venue_root(site) is None or site in seen:
                continue
            consumed += 1
            try:
                venue = verified_venue_reciprocity(
                    site, source["title"], dates, today, fetch=fetch)
                if venue is None:
                    continue
                proposal = venue_private_proposal(
                    source["title"], site, dates, today, venue_root=venue)
                if (proposal is None or
                        validate_venue_private_proposal(proposal, today) is None):
                    continue
                proposals.append(proposal)
                seen.add(site)
            except (OSError, ValueError, TypeError, UnicodeError, KeyError):
                continue
            break
    return proposals


def append_venue_proposals(folder, catalog, history, state, queue,
                            report, today, fetch=fetch_public_html):
    if (not isinstance(history, dict) or history.get("schema") != 2
            or not isinstance(history.get("knownFestivals"), list)):
        raise ValueError("Unsafe historical reference")
    additions = stable_reciprocal_venue_proposals(
        state, queue, catalog, report, today, fetch=fetch)
    if not additions:
        return 0
    patch = latest_patch(folder, date.fromisoformat(today))
    used = {row.get("slug") for row in patch["additions"]
            if isinstance(row, dict)}
    n = 0
    for row in additions:
        if (len(patch["additions"]) >= 100 or row["slug"] in used
                or conflicts_with_signed_catalogue(
                    row, catalog["festivals"], history["knownFestivals"])):
            continue
        patch["additions"].append(row)
        used.add(row["slug"])
        n += 1
    if n:
        patch["generated_at"] = today
        atomic_json(folder / ("patch-" + today + ".json"), patch)
    return n


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
    queue = read(folder / "national-festival-discovery-review.json")
    catalog = read(args.catalog)
    report = examine(state, queue, catalog, today)
    history = (read(folder / "festival-history.json")
               if (folder / "festival-history.json").exists()
               else read(args.catalog.parent / "festival-history.json"))
    added = append_directory_proposals(
        folder, catalog, history, state, queue, report, today)
    direct_added = append_direct_first_party_proposals(
        folder, catalog, history, state, queue, report, today)
    venue_added = append_venue_proposals(
        folder, catalog, history, state, queue, report, today)
    state_path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (folder / "national-generic-primary-date-review.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print("Generic national first-party date research: eligible="
          + str(report["eligible_source_count"]) + ", checked="
          + str(report["checked_count"]) + ", two-day="
          + str(report["two_day_dates_count"]) + ", directory_private_additions=" + str(added)
          + ", direct_first_party_private_additions=" + str(direct_added)
          + ", venue_reciprocal_private_additions=" + str(venue_added)
          + ", publications=0")


if __name__ == "__main__":
    main()
