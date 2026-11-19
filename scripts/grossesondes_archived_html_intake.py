"""Bounded first-party archived-edition proposals, strictly PRIVATE only.

Two frozen organizer sites are inspected on the existing PUBLIC festival runner.
A proposal requires the same visible first-party identity/date on two consecutive
local calendar days. It is re-proved by the real cloud publisher before publication.
No archival GPS, city, venue, tickets, artist or lineup are inherited.
"""
from __future__ import annotations

import argparse
import copy
from datetime import date, datetime, timedelta
from hashlib import sha256
import json
import os
import re
from pathlib import Path
import tempfile
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from grossesondes_official_html_edition import (
    VisibleText, CANCEL, fold, explicit_ranges, visible_official_edition,
)
from grossesondes_stage import official_text
from grossesondes_structured_roster import (
    JsonLD, walk, iso_day, edition_name, ALLOWED_EVENT_TYPES,
    SENSITIVE_STATUSES,
)
from grossesondes_structured_edition import (
    ARCHIVED_PROOF_MODE, ARCHIVED_HTML_PROOF_MODE,
    ARCHIVED_BROWSER_PROOF_MODE,
    PRIVATE_CONFIDENCE, PRIVATE_NOTES, PRIVATE_STATUS,
    pinned_parent_identity, validate_archived_structured_edition,
    conflicts_with_existing,
)

# Never derive a destination from private candidates, discovered links or a
# previous year's arbitrary site. Both first-party locations have been checked.
PINNED_ARCHIVED_HTML_SOURCES = {
    "mozhell-open-air": {
        "officialSite": "https://www.mozhell.fr/fr/",
        "proofUrl": "https://www.mozhell.fr/fr/le-mozhell-est-de-retour-pour-une-nouvelle-edition-en-2027",
        "year": 2027,
    },
    "festival-666": {
        "officialSite": "https://www.festival666.com/",
        "proofUrl": "https://www.festival666.com/",
        "year": 2027,
    },
}
# Generalize next-edition discovery to independently signed historic organizer
# sites. Only the IMMUTABLE public festival-history is used as a source list.
# Named ticket platforms, social networks and aggregators are NOT organizers.
GENERIC_ROTATION_KEY = "archived_html_organizer_rotation_cursor"
GENERIC_MAX_PER_RUN = 10
# Review hints cannot consume all slots or starve the unbiased rotation.
GENERIC_NATIONAL_PRIORITY_MAX_PER_RUN = 3
NATIONAL_REVIEW_SCHEMA = "grossesondes.national-festival-discovery-private.v1"
GENERIC_DENY_HOSTS = frozenset({
    "facebook.com", "instagram.com", "x.com", "twitter.com",
    "linktr.ee", "helloasso.com", "billetweb.fr", "shotgun.live",
    "eventbrite.com", "bandsintown.com", "songkick.com",
    "ticketmaster.fr", "fnacspectacles.com", "weezevent.com",
})


def organizer_homepage(url):
    """Only original HTTPS organizer-owned pages from the signed archive."""
    if not isinstance(url, str) or len(url) > 600:
        return False
    if not pinned_first_party(url, url):
        return False
    try:
        u = urlsplit(url)
        host = u.hostname
        if not host or host.endswith((".local", ".internal", ".localhost")):
            return False
        labels = host.split(".")
        if (len(labels) < 2 or any(
                not label or not label.isascii() or not label[0].isalnum()
                or not label[-1].isalnum()
                or not label.replace("-", "").isalnum()
                for label in labels)
                or all(part.isdigit() for part in labels)):
            return False
        if any(host == domain or host.endswith("." + domain)
               for domain in GENERIC_DENY_HOSTS):
            return False
        return True
    except (ValueError, AttributeError):
        return False


def already_published_next_edition(parent, year, published_rows):
    """Reuse the publisher's signed-catalog identity/year overlap gate.

    The date is only a local year marker for matching, never a proposed date
    or evidence. This prevents yearless published slugs from re-entering the
    private admission queue under their derived -2027 identifiers.
    """
    if not published_rows:
        return False
    identity = pinned_parent_identity(parent)
    if identity is None:
        return False
    return conflicts_with_existing({
        "slug": identity[0] + "-" + str(year),
        "name": str(parent.get("name") or "").strip() + " " + str(year),
        "startDate": str(year) + "-01-01",
    }, published_rows, [])


def _hint_identity(value):
    """Comparison only; no dossier text or URL becomes official evidence."""
    return " ".join(re.findall(r"[a-z0-9]+", fold(value)))


def national_archived_priority(folder, archive, today):
    """A review-only lead may prioritize an ALREADY SIGNED archive source.

    Private hint URLs are never read or fetched. Even a forged lead cannot
    authorize an origin absent from the historical source catalogue.
    Invalid/missing/stale optional review data simply yields no priorities.
    """
    path = folder / "national-festival-discovery-review.json"
    try:
        review = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(review, dict)
                or review.get("schema") != NATIONAL_REVIEW_SCHEMA
                or review.get("review_only") is not True
                or review.get("safe_to_publish") is not False
                or review.get("publication_authorized") is not False):
            return frozenset()
        reviewed = date.fromisoformat(review.get("as_of", ""))
        if not timedelta(0) <= today - reviewed <= timedelta(days=2):
            return frozenset()
        dossiers = review.get("dossiers")
        if not isinstance(dossiers, list) or len(dossiers) > 200:
            return frozenset()
    except (OSError, ValueError, TypeError, UnicodeError):
        return frozenset()
    trusted = set()
    for row in dossiers:
        if (not isinstance(row, dict)
                or row.get("status") != "DISCOVERED_REVIEW_REQUIRED"
                or row.get("publication_authorized") is not False
                or row.get("safe_to_publish") is not False):
            continue
        slug = row.get("archive_slug_hint")
        parent = archive.get(slug) if isinstance(slug, str) else None
        if not isinstance(parent, dict):
            continue
        ident = pinned_parent_identity(parent)
        if (ident is None or parent.get("lastKnownYear") != ident[1]
                or type(row.get("edition_year_hint")) is not int
                or row["edition_year_hint"] != max(today.year + 1, ident[1] + 1)
                or row["edition_year_hint"] not in (2027, 2028)
                or _hint_identity(row.get("name_hint")) !=
                   _hint_identity(parent.get("name"))
                or _hint_identity(row.get("region_hint")) !=
                   _hint_identity(parent.get("region"))):
            continue
        trusted.add(slug)
    return frozenset(trusted)


def private_date_rejection_reason(html, parent, year):
    """Safe bounded enum, not raw content or untrusted exception text."""
    if not isinstance(html, str) or not 0 < len(html) <= 1_400_000:
        return "official_html_invalid_or_oversized"
    parser = VisibleText()
    parser.feed(html)
    parser.close()
    content = " ".join(fold(" ".join(parser.parts)).split())
    ranges = {(first, last) for _a, _b, first, last
              in explicit_ranges(content, year)}
    if not ranges:
        # Diagnostic only: a raw-markup year is not itself proof of an event.
        # Never persist page text, URLs, dates or parser exceptions.
        year_token = re.compile(r"(?<![0-9])" + str(year) + r"(?![0-9])")
        if year_token.search(content):
            return "official_visible_year_without_parseable_range"
        if year_token.search(html):
            return "official_markup_year_without_visible_year"
        return "official_html_no_explicit_visible_future_range"
    if len(ranges) > 1:
        return "official_html_conflicting_future_ranges"
    return "official_html_range_identity_or_context_rejected"


def generic_rotating_sources(archive, published, occupied, state, today,
                             limit=GENERIC_MAX_PER_RUN, published_rows=(),
                             priority_slugs=()):
    """Pick bounded, diverse first-party homepages without any event hardcode.

    Follow up yesterday's observed exact edition before rotating new archives:
    two consecutive days are essential; five runs on the same day are not.
    Returns only source specs from a signed historical catalogue. A source
    alone never approves an event, and the real publisher re-fetches it.
    """
    if not isinstance(archive, dict) or not isinstance(state, dict):
        raise ValueError("Untrusted archived source list")
    limit = max(1, min(GENERIC_MAX_PER_RUN, int(limit)))
    current = state.get(STATE_KEY) or {}
    if not isinstance(current, dict):
        raise ValueError("Untrusted archive observation state")
    candidates = {}
    for slug, parent in sorted(archive.items()):
        if slug in PINNED_ARCHIVED_HTML_SOURCES or not isinstance(parent, dict):
            continue
        identity = pinned_parent_identity(parent)
        if identity is None or parent.get("lastKnownYear") != identity[1]:
            continue
        # An archive can be older than the previous calendar year. The
        # FIRST upcoming target is 2027/2028; it must be printed on the
        # organizer's present-day page, never inferred from the old record.
        year = max(today.year + 1, identity[1] + 1)
        if year not in (2027, 2028):
            continue
        if not isinstance(parent.get("name"), str) or not 8 <= len(parent["name"]) <= 180:
            continue
        # Archive headings with embedded old edition years cannot be reused
        # literally as the current title without a validated rename.
        if re.search(r"(?<![0-9])20[2-4][0-9](?![0-9])", parent["name"]):
            continue
        new_slug = identity[0] + "-" + str(year)
        if new_slug in published or new_slug in occupied:
            continue
        if already_published_next_edition(parent, year, published_rows):
            continue
        site = parent.get("officialSite")
        if not organizer_homepage(site):
            continue
        candidates[slug] = {
            "officialSite": site, "proofUrl": site, "year": year,
        }
    yesterday = today - timedelta(days=1)
    carry = []
    fresh = []
    for slug, spec in candidates.items():
        parent = archive[slug]
        identity = pinned_parent_identity(parent)
        record = current.get(identity[0] + "-" + str(spec["year"]))
        if (isinstance(record, dict)
                and record.get("lastSeen") == yesterday.isoformat()):
            carry.append((slug, spec))
        else:
            fresh.append((slug, spec))
    cursor = state.get(GENERIC_ROTATION_KEY, 0)
    if type(cursor) is not int or cursor < 0:
        raise ValueError("Invalid archived organizer rotation cursor")
    selected = carry[:limit]
    available = max(0, limit - len(selected))
    # At most three verified-archive identity matches may influence order.
    # They do NOT extend the ten-source budget or certify dates.
    priority = set(priority_slugs)
    prioritized = [pair for pair in fresh if pair[0] in priority][
        :min(available, GENERIC_NATIONAL_PRIORITY_MAX_PER_RUN)]
    selected.extend(prioritized)
    if prioritized:
        selected_slugs = {slug for slug, _ in prioritized}
        fresh = [pair for pair in fresh if pair[0] not in selected_slugs]
    available = max(0, limit - len(selected))
    if fresh and available:
        index = cursor % len(fresh)
        picked = min(available, len(fresh))
        selected += [fresh[(index + i) % len(fresh)]
                     for i in range(picked)]
        state[GENERIC_ROTATION_KEY] = (index + picked) % len(fresh)
    return dict(selected)


STATE_KEY = "archived_html_edition_observations"
SOURCE_MARKER = "grossesondes.patch.v1"
ORIGIN_URL = "https://grosses-ondes.fr/data/festivals.json"


def pinned_first_party(site, proof):
    """Only same-origin HTTPS documents at/below a reviewed parent path."""
    if not isinstance(site, str) or not isinstance(proof, str):
        return False
    try:
        origin, target = urlsplit(site), urlsplit(proof)
        if (origin.scheme != "https" or target.scheme != "https"
                or origin.hostname != target.hostname
                or not origin.hostname or origin.port is not None
                or target.port is not None
                or any((origin.username, origin.password, target.username,
                        target.password, origin.query, origin.fragment,
                        target.query, target.fragment))):
            return False
        base = origin.path if origin.path.endswith("/") else origin.path + "/"
        return (target.path == origin.path
                or target.path.startswith(base)) and (
                    ".." not in target.path and "%" not in target.path
                    and "\\\\" not in target.path)
    except ValueError:
        return False


def official_date(html, parent, year):
    if not isinstance(html, str) or not 0 < len(html) <= 1_400_000:
        return None
    parser = VisibleText()
    parser.feed(html)
    parser.close()
    content = " ".join(fold(" ".join(parser.parts)).split())
    title = str(parent.get("name") or "").strip() + " " + str(year)
    unique = {(first, last) for _a, _b, first, last
              in explicit_ranges(content, year)}
    # Do not guess between conflicting date ranges or choose a single day
    # from ambiguous text. The full visible-edition gate must also pass.
    if len(unique) != 1:
        return None
    first, last = next(iter(unique))
    if not visible_official_edition(html, title, first, last):
        return None
    return first, last


def matching_official_jsonld_present(html, parent, year):
    """Detect a same-edition JSON-LD claim before choosing the proof mode.

    If an official page contradicts itself, we must not quietly switch to the
    representation with favorable dates and ignore the other one.
    """
    if not isinstance(html, str) or not 0 < len(html) <= 1_400_000:
        return False
    title = str(parent.get("name") or "").strip() + " " + str(year)
    parser = JsonLD()
    parser.feed(html)
    parser.close()
    for document in parser.documents[:30]:
        for event in walk(document):
            types = event.get("@type")
            if not isinstance(types, list):
                types = [types]
            if (isinstance(event.get("name"), str)
                    and event["name"].strip() == title
                    and {str(t).rsplit("/", 1)[-1].casefold() for t in types}
                       .intersection(ALLOWED_EVENT_TYPES)):
                return True
    return False


def official_structured_date(html, parent, year):
    """Exact current-edition JSON-LD alternative to visible HTML evidence.

    Untrusted page data supplies no destination, signed parent, publisher
    approval, location, line-up or inherited artist. The real publisher still
    independently validates the SAME event on the frozen organizer homepage.
    A contrary visible current-edition range or cancellation blocks admission.
    """
    if not isinstance(html, str) or not 0 < len(html) <= 1_400_000:
        return None
    title = str(parent.get("name") or "").strip() + " " + str(year)
    if not 8 <= len(title) <= 180:
        return None
    parser = JsonLD()
    parser.feed(html)
    parser.close()
    matches = set()
    matching_events = 0
    for document in parser.documents[:30]:
        for event in walk(document):
            types = event.get("@type")
            if not isinstance(types, list):
                types = [types]
            allowed = {str(t).rsplit("/", 1)[-1].casefold() for t in types}
            if not allowed.intersection(ALLOWED_EVENT_TYPES):
                continue
            name = event.get("name")
            if (not isinstance(name, str) or name.strip() != title
                    or edition_name(name) != edition_name(title)
                    or str(year) not in
                       re.findall(r"\b20[2-4][0-9]\b", name)):
                continue
            matching_events += 1
            first = iso_day(event.get("startDate"))
            last = iso_day(event.get("endDate"))
            status = str(event.get("eventStatus", "")).rsplit("/", 1)[-1].casefold()
            if (not first or not last or first.year != year
                    or last.year != year or not first <= last
                    or (last - first).days > 7
                    or status in SENSITIVE_STATUSES):
                return None
            matches.add((first, last))
    if matching_events < 1 or len(matches) != 1:
        return None
    visible = VisibleText()
    visible.feed(html)
    visible.close()
    content = " ".join(fold(" ".join(visible.parts)).split())
    if CANCEL.search(content):
        return None
    visible_ranges = {(first, last) for _a, _b, first, last
                      in explicit_ranges(content, year)}
    if visible_ranges and visible_ranges != matches:
        return None
    return next(iter(matches))


def candidate(parent, source, html, today):
    ident = pinned_parent_identity(parent)
    if (ident is None or parent.get("officialSite") != source["officialSite"]
            or parent.get("lastKnownYear") != ident[1]
            or source["year"] not in (2027, 2028)
            or source["year"] <= ident[1]):
        return None
    visible_observed = official_date(html, parent, source["year"])
    structured_observed = official_structured_date(
        html, parent, source["year"])
    has_jsonld_claim = matching_official_jsonld_present(
        html, parent, source["year"])
    # When both representations claim this same edition, a contradiction or
    # invalid JSON-LD MUST refuse admission in both proof modes.
    if visible_observed is not None and has_jsonld_claim:
        if structured_observed != visible_observed:
            return None
    observed = visible_observed if visible_observed is not None else structured_observed
    mode = (ARCHIVED_HTML_PROOF_MODE
            if visible_observed is not None else ARCHIVED_PROOF_MODE)
    if observed is None:
        return None
    start, end = observed
    if not today <= start:
        return None
    proposal = {
        "slug": ident[0] + "-" + str(source["year"]),
        "name": str(parent["name"]).strip() + " " + str(source["year"]),
        "startDate": start.isoformat(), "endDate": end.isoformat(),
        "city": None, "department": None, "region": None,
        "venue": None, "lat": None, "lon": None,
        "showOnMap": False, "dateRangeIsContinuous": False,
        "lineup": [], "bands": 0, "price": None,
        "status": "Annoncé",
        "officialSite": source["officialSite"], "source": source["officialSite"],
        "lastVerified": today.isoformat(), "notes": PRIVATE_NOTES,
        "verificationStatus": PRIVATE_STATUS,
        "sourceConfidence": PRIVATE_CONFIDENCE,
        "proofMode": mode,
        "originSlug": parent["slug"],
        "evidence": [source["officialSite"]],
        "verified_at": today.isoformat(),
    }
    # Reuse the EXACT publisher validator in the intake. This is still not an
    # approval, as the publisher independently re-downloads on another run.
    if validate_archived_structured_edition(
            proposal, parent, html, today.isoformat(),
            proof_mode=mode) is None:
        return None
    return proposal


def stability(state, proposal, proof_url, today):
    records = state.setdefault(STATE_KEY, {})
    if not isinstance(records, dict):
        raise ValueError("Invalid prior official-edition observation registry")
    slug = proposal["slug"]
    stable = {
        field: proposal[field] for field in
        ("slug", "name", "originSlug", "startDate", "endDate",
         "officialSite", "proofMode")
    }
    stable["pinnedProofUrl"] = proof_url
    digest = sha256(json.dumps(stable, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    before = records.get(slug)
    if isinstance(before, dict) and before.get("digest") == digest:
        try:
            previous = date.fromisoformat(before["lastSeen"])
            first = date.fromisoformat(before["firstSeen"])
        except (ValueError, KeyError, TypeError):
            previous, first = None, None
        if previous == today and first is not None and first < today:
            return True
        if previous is not None and first is not None and previous < today:
            if (today - previous).days == 1 and first < today:
                before["lastSeen"] = today.isoformat()
                return True
            if (today - previous).days == 1 and first == previous:
                before["lastSeen"] = today.isoformat()
                return True
    records[slug] = {
        "digest": digest, "firstSeen": today.isoformat(),
        "lastSeen": today.isoformat(),
    }
    return False


def latest_patch(folder, today):
    options = []
    for f in folder.glob("patch-????-??-??.json"):
        try:
            day = date.fromisoformat(f.stem[6:])
            if day <= today:
                options.append((day, f))
        except ValueError:
            pass
    if not options:
        raise ValueError("No existing private reference patch")
    day, source = max(options)
    patch = json.loads(source.read_text(encoding="utf-8"))
    if (patch.get("schema") != SOURCE_MARKER
            or patch.get("safe_to_publish") is not False
            or patch.get("generated_at") != day.isoformat()
            or patch.get("source", {}).get("festivals", {}).get("url") != ORIGIN_URL
            or not isinstance(patch.get("additions"), list)
            or not isinstance(patch.get("updates"), list)
            or not isinstance(patch.get("deferred"), list)
            or patch.get("history_additions") != []
            or patch.get("history_updates") != []):
        raise ValueError("Private reference patch invalid")
    return patch


def atomic_json(path, value):
    descriptor, temp = tempfile.mkstemp(prefix=".archive-edition-", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as out:
            json.dump(value, out, indent=2, ensure_ascii=False)
            out.write("\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def run(folder, calendar, history, today, fetcher=official_text,
        browser_fetcher=None):
    if not isinstance(today, date):
        raise TypeError("today must be a date")
    statefile = folder / "source-watch-state.json"
    state = json.loads(statefile.read_text(encoding="utf-8"))
    if not isinstance(state, dict) or state.get("schema") != "grossesondes.source-watch.v1":
        raise ValueError("Source watch state mismatch")
    archive = {row["slug"]: row for row in history["knownFestivals"]}
    published = {row["slug"] for row in calendar["festivals"]}
    archive_slugs = set(archive)
    patch = latest_patch(folder, today)
    original_patch = copy.deepcopy(patch)
    successes, candidates = 0, 0
    browser_attempts = 0  # At most two JS renders per public runner execution.
    occupied = {row.get("slug") for row in patch["additions"]}
    # Long-lived PRIVATE aggregate coverage, distinct from the rolling 40
    # diagnostic reasons. Only an archived slug and attempted date are kept.
    checked_sources = state.setdefault("archived_html_source_attempted_private", {})
    if not isinstance(checked_sources, dict):
        raise ValueError("Invalid archived source coverage state")
    for checked_slug, checked_day in checked_sources.items():
        if checked_slug not in archive or not isinstance(checked_day, str):
            raise ValueError("Invalid archived source coverage record")
        try:
            parsed_checked_day = date.fromisoformat(checked_day)
        except ValueError as exc:
            raise ValueError("Invalid archived source coverage date") from exc
        if parsed_checked_day > today:
            raise ValueError("Archived source coverage date lies in future")
    tracking_started = state.setdefault("archived_html_tracking_started_private",
                                        today.isoformat())
    try:
        if (not isinstance(tracking_started, str)
                or date.fromisoformat(tracking_started) > today):
            raise ValueError("Invalid archive coverage tracking start")
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid archive coverage tracking start") from exc
    # Diagnostics are strictly private (source-watch-state.json); no raw HTML,
    # URLs, exception messages, public artifacts, or publish permissions.
    history_status = state.setdefault("archived_html_proof_last_result_private", {})
    if not isinstance(history_status, dict):
        raise ValueError("Invalid private archive diagnostics state")
    def record(slug, reason):
        history_status[slug] = {"checked_on": today.isoformat(),
                                "result": reason}
    # Keep the two source-specific approved paths unchanged, then scan
    # a bounded rotating set of signed archived organizer homepages.
    watched = dict(PINNED_ARCHIVED_HTML_SOURCES)
    watched.update(generic_rotating_sources(
        archive, published, occupied, state, today,
        published_rows=calendar["festivals"],
        priority_slugs=national_archived_priority(folder, archive, today)))
    for slug, source in watched.items():
        parent = archive.get(slug)
        if (not isinstance(parent, dict)
                or parent.get("officialSite") != source["officialSite"]
                or not pinned_first_party(source["officialSite"],
                                          source["proofUrl"])):
            record(slug, "registered_origin_or_path_mismatch")
            continue
        identity = pinned_parent_identity(parent)
        if (identity is None or parent.get("lastKnownYear") != identity[1]
                or source["year"] not in (2027, 2028)
                or source["year"] <= identity[1]):
            record(slug, "historical_identity_or_year_mismatch")
            continue
        new_slug = identity[0] + "-" + str(source["year"])
        if already_published_next_edition(parent, source["year"],
                                          calendar["festivals"]):
            record(slug, "already_published_or_historical")
            continue
        if new_slug in published or new_slug in archive_slugs:
            record(slug, "already_published_or_historical")
            continue
        if new_slug in occupied:
            record(slug, "already_in_private_patch")
            continue
        # "Attempted" counts both successful requests and fetch failures.
        # The raw URL, response, exception and HTML are NEVER persisted here.
        checked_sources[slug] = today.isoformat()
        try:
            html = fetcher(source["proofUrl"], registered=True, raw=True)
        except (OSError, ValueError, TypeError, UnicodeError):
            record(slug, "official_page_fetch_failed")
            continue
        try:
            proposed = candidate(parent, source, html, today)
            if proposed is None:
                reason = (private_date_rejection_reason(
                    html, parent, source["year"])
                    if official_date(html, parent, source["year"]) is None
                    else "exact_edition_or_publisher_proof_rejected")
                # A code-reviewed ARCHIVED organizer can show its date only
                # after JavaScript runs. Browser output is not proof by itself:
                # the exact publisher validator is applied to the rendered
                # DOM here, again on the next calendar day, AND on an
                # independent browser fetch by the public publisher.
                if (browser_fetcher is not None and browser_attempts < 2
                        and reason in (
                            "official_markup_year_without_visible_year",
                            "official_visible_year_without_parseable_range")
                        and source["proofUrl"] == source["officialSite"]
                        and organizer_homepage(source["officialSite"])):
                    browser_attempts += 1
                    try:
                        rendered = browser_fetcher(source["officialSite"])
                        proposed = candidate(parent, source, rendered, today)
                        if (proposed is not None
                                and proposed["proofMode"] == ARCHIVED_HTML_PROOF_MODE
                                and official_date(rendered, parent, source["year"])
                                    is not None):
                            proposed["proofMode"] = ARCHIVED_BROWSER_PROOF_MODE
                            if validate_archived_structured_edition(
                                    proposed, parent, rendered,
                                    today.isoformat(), proof_mode=ARCHIVED_BROWSER_PROOF_MODE
                                    ) is None:
                                proposed = None
                        else:
                            proposed = None
                    except Exception:
                        proposed = None
                        reason = "official_browser_render_unavailable"
                if proposed is None:
                    record(slug, reason)
                    continue
        except (ValueError, TypeError, UnicodeError):
            record(slug, "official_page_unparseable")
            continue
        candidates += 1
        if not stability(state, proposed, source["proofUrl"], today):
            record(slug, "second_independent_day_pending")
            continue
        if len(patch["additions"]) >= 100:
            record(slug, "private_append_limit")
            continue
        patch["additions"].append(proposed)
        occupied.add(proposed["slug"])
        successes += 1
        record(slug, "added_to_private_patch")
    # Retain only recent statuses and avoid a continually growing private state.
    # Do not include original page, title, hostname, response body or errors.
    if len(history_status) > 40:
        keep = sorted(history_status, key=lambda key: (
            history_status[key].get("checked_on", ""), key), reverse=True)[:40]
        state["archived_html_proof_last_result_private"] = {
            key: history_status[key] for key in keep
        }
    trusted_first_party = {
        slug for slug, parent in archive.items()
        if isinstance(parent, dict)
        and organizer_homepage(parent.get("officialSite"))
    }
    attempted = trusted_first_party.intersection(checked_sources)
    recently_attempted = sum(
        0 <= (today - date.fromisoformat(checked_sources[slug])).days < 7
        for slug in attempted
    )
    state["archived_html_source_coverage_private"] = {
        "as_of": today.isoformat(),
        "tracking_started_on": tracking_started,
        "historical_records": len(archive),
        "first_party_https_sources": len(trusted_first_party),
        "untrusted_or_missing_origin_sources": len(archive) - len(trusted_first_party),
        "sources_attempted_since_tracking": len(attempted),
        "sources_attempted_past_7_days": recently_attempted,
        "sources_unattempted_since_tracking": len(trusted_first_party) - len(attempted),
    }
    if patch != original_patch:
        patch["generated_at"] = today.isoformat()
        atomic_json(folder / ("patch-" + today.isoformat() + ".json"), patch)
    atomic_json(statefile, state)
    # Deliberately do not expose the private proposed rows in stdout.
    return {"officialProofsEligible": candidates,
            "privateCandidatesAdded": successes, "publicWrites": 0}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--intake", type=Path, required=True)
    ap.add_argument("--catalog", type=Path, required=True)
    ap.add_argument("--history", type=Path, required=True)
    args = ap.parse_args()
    today = datetime.now(ZoneInfo("Europe/Paris")).date()
    calendar = json.loads(args.catalog.read_text(encoding="utf-8"))
    history = json.loads(args.history.read_text(encoding="utf-8"))
    # No browser is imported or executed without the explicit, trusted
    # public-runner switch. Unit tests inject their own deterministic renderer.
    browser_fetcher = None
    if os.environ.get("GROSSES_ONDES_BROWSER_INTAKE") == "enabled":
        from grossesondes_official_browser_probe import rendered_html
        browser_fetcher = rendered_html
    result = run(args.intake, calendar, history, today,
                 browser_fetcher=browser_fetcher)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
