"""Bounded first-party archived-edition proposals, strictly PRIVATE only.

Two frozen organizer sites are inspected on the existing PUBLIC festival runner.
A proposal requires the same visible first-party identity/date on two consecutive
local calendar days. It is re-proved by the real cloud publisher before publication.
No archival GPS, city, venue, tickets, artist or lineup are inherited.
"""
from __future__ import annotations

import argparse
import copy
from datetime import date, datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
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
STATE_KEY = "archived_html_edition_observations"
SOURCE_MARKER = "grossesondes.patch.v1"
ORIGIN_URL = "https://grosses-ondes.fr/data/festivals.json"


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
    for slug, source in PINNED_ARCHIVED_HTML_SOURCES.items():
        parent = archive.get(slug)
        if not isinstance(parent, dict) or parent.get("officialSite") != source["officialSite"]:
            continue
        new_slug = slug + "-" + str(source["year"])
        if new_slug in published or new_slug in archive_slugs or new_slug in occupied:
            continue
        try:
            html = fetcher(source["proofUrl"], registered=True, raw=True)
            proposed = candidate(parent, source, html, today)
        except (OSError, ValueError, TypeError, UnicodeError):
            proposed = None
        if proposed is None:
            continue
        candidates += 1
        if not stability(state, proposed, source["proofUrl"], today):
            continue
        if len(patch["additions"]) >= 100:
            continue
        patch["additions"].append(proposed)
        occupied.add(proposed["slug"])
        successes += 1
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
