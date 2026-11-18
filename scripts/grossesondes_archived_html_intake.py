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

from grossesondes_official_html_edition import VisibleText, fold, explicit_ranges, visible_official_edition
from grossesondes_stage import official_text
from grossesondes_structured_edition import (
    ARCHIVED_HTML_PROOF_MODE, PRIVATE_CONFIDENCE, PRIVATE_NOTES,
    PRIVATE_STATUS, pinned_parent_identity, validate_archived_structured_edition,
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


def generic_rotating_sources(archive, published, occupied, state, today,
                             limit=GENERIC_MAX_PER_RUN):
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
        year = identity[1] + 1
        if year not in (2027, 2028) or year <= today.year:
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
    if fresh and available:
        index = cursor % len(fresh)
        selected += [fresh[(index + i) % len(fresh)]
                     for i in range(min(available, len(fresh)))]
        state[GENERIC_ROTATION_KEY] = (index + min(available, len(fresh))) % len(fresh)
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


def candidate(parent, source, html, today):
    ident = pinned_parent_identity(parent)
    if (ident is None or parent.get("officialSite") != source["officialSite"]
            or parent.get("lastKnownYear") != ident[1]
            or source["year"] != ident[1] + 1):
        return None
    observed = official_date(html, parent, source["year"])
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
        "proofMode": ARCHIVED_HTML_PROOF_MODE,
        "originSlug": parent["slug"],
        "evidence": [source["officialSite"]],
        "verified_at": today.isoformat(),
    }
    # Reuse the EXACT publisher validator in the intake. This is still not an
    # approval, as the publisher independently re-downloads on another run.
    if validate_archived_structured_edition(
            proposal, parent, html, today.isoformat(),
            proof_mode=ARCHIVED_HTML_PROOF_MODE) is None:
        return None
    return proposal


def stability(state, proposal, proof_url, today):
    records = state.setdefault(STATE_KEY, {})
    if not isinstance(records, dict):
        raise ValueError("Invalid prior official-edition observation registry")
    slug = proposal["slug"]
    stable = {
        field: proposal[field] for field in
        ("slug", "name", "originSlug", "startDate", "endDate", "officialSite")
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


def run(folder, calendar, history, today, fetcher=official_text):
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
    occupied = {row.get("slug") for row in patch["additions"]}
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
        archive, published, occupied, state, today))
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
                or source["year"] != identity[1] + 1):
            record(slug, "historical_identity_or_year_mismatch")
            continue
        new_slug = identity[0] + "-" + str(source["year"])
        if new_slug in published or new_slug in archive_slugs:
            record(slug, "already_published_or_historical")
            continue
        if new_slug in occupied:
            record(slug, "already_in_private_patch")
            continue
        try:
            html = fetcher(source["proofUrl"], registered=True, raw=True)
        except (OSError, ValueError, TypeError, UnicodeError):
            record(slug, "official_page_fetch_failed")
            continue
        try:
            proposed = candidate(parent, source, html, today)
            if proposed is None:
                reason = ("visible_dates_absent_or_ambiguous"
                          if official_date(html, parent, source["year"]) is None
                          else "exact_edition_or_publisher_proof_rejected")
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
    result = run(args.intake, calendar, history, today)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
