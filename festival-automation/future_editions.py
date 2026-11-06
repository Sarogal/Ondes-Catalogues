"""Conservative private discovery of the *next* annual festival edition.

A candidate is produced only from registered official schema.org evidence
observed with identical identity and dates on two distinct calendar days.
It stays in the private cumulative patch with safe_to_publish:false.
The PUBLIC synchronizer must independently fetch and validate the official
HTML before publishing anything. Location, tickets and pins are never copied
from a previous edition.
"""
from datetime import date
from hashlib import sha256
import json
import re

from structured_evidence import root_name

PROOF_MODE = "structured-edition.v1"
ORIGIN_URL = "https://grosses-ondes.fr/data/festivals.json"
PATTERN = re.compile(r"^(.+)-(20[2-4][0-9])$")
EMBEDDED_YEAR = re.compile(r"(?<![0-9])20[2-4][0-9](?![0-9])")


def parent_edition(parent, original):
    """Recover the parent year without guessing recurrence or stripping cities.

    Explicit `festival-2027` slugs stay supported. A truly yearless slug may
    use the immutable source's exact start date, but the current published date
    must still agree. Slugs containing a year in the middle (multi-city /
    season variants) are NOT shortened or silently reinterpreted.
    """
    slug = parent.get("slug")
    if not isinstance(slug, str) or not slug or original.get("slug") != slug:
        return None
    if parent.get("officialSite") != original.get("officialSite") or (
            parent.get("name") != original.get("name")):
        return None
    match = PATTERN.fullmatch(slug)
    if match:
        return match.group(1), int(match.group(2))
    if EMBEDDED_YEAR.search(slug):
        return None
    raw = original.get("startDate")
    if not isinstance(raw, str) or parent.get("startDate") != raw:
        return None
    try:
        known = date.fromisoformat(raw)
    except ValueError:
        return None
    # If the parent is named with a year, it must not contradict its date.
    years_in_title = EMBEDDED_YEAR.findall(str(parent.get("name", "")))
    if years_in_title and (len(set(years_in_title)) != 1
                           or years_in_title[0] != str(known.year)):
        return None
    return slug, known.year


def edition_candidate(parent, original, observation, published, today):
    """Construct a private proposal, not an independently verified new row."""
    if not all(isinstance(x, dict) for x in (parent, original, observation, published)):
        return None
    identity = parent_edition(parent, original)
    if identity is None:
        return None
    root_slug, old_year = identity
    slug = parent["slug"]
    new_year = observation.get("hints", {}).get("new_edition_year")
    if type(new_year) is not int or new_year != old_year + 1 or new_year not in (2027, 2028):
        return None
    url = parent.get("officialSite")
    title = observation.get("name_on_source")
    if not (isinstance(url, str) and url.startswith("https://")
            and observation.get("source_url") == url
            and observation.get("slug") == slug
            and observation.get("publication_authorized") is False
            and isinstance(title, str) and len(title) <= 180
            and re.search(r"\b" + str(new_year) + r"\b", title)
            and len(root_name(title)) >= 8
            and root_name(title) == root_name(parent.get("name", ""))):
        return None
    start, end = observation.get("startDate_source"), observation.get("endDate_source")
    try:
        begin = date.fromisoformat(start)
        finish = date.fromisoformat(end)
        observed = date.fromisoformat(today)
    except (ValueError, TypeError):
        return None
    if not (observed <= begin <= finish and
            begin.year == new_year and finish.year == new_year and
            (finish - begin).days <= 7):
        return None
    # Future edition discovery is not permitted to infer lineup, prices,
    # daily sessions, location or anything sensitive from a previous row.
    hints = observation.get("hints")
    if not isinstance(hints, dict) or set(hints) - {
        "new_edition_year", "place_name_unverified"
    }:
        return None
    new_slug = root_slug + "-" + str(new_year)
    if new_slug in published or any(
        isinstance(row, dict) and
        (row.get("name") == title or
         (str(row.get("startDate") or "").startswith(str(new_year))
          and root_name(row.get("name", "")) == root_name(title)))
        for row in published.values()
    ):
        return None
    return {
        "slug": new_slug,
        "name": title.strip(),
        "startDate": start,
        "endDate": end,
        "city": None, "department": None, "region": None, "venue": None,
        "lat": None, "lon": None, "showOnMap": False,
        "dateRangeIsContinuous": False,
        "lineup": [], "bands": 0, "price": None,
        "status": "Annoncé",
        "officialSite": url, "source": url,
        "lastVerified": today,
        "notes": "Édition annoncée dans les données structurées du site officiel ; "
                 "dates de l'événement vérifiables. Lieu, séances, tarifs et "
                 "coordonnées restent à confirmer.",
        "verificationStatus": "Édition et dates à confirmer indépendamment avant publication",
        "sourceConfidence": "Site officiel (JSON-LD privé, preuve publique requise)",
        "proofMode": PROOF_MODE,
        "originSlug": slug,
        "evidence": [url],
        "verified_at": today,
    }


def stable_candidate(state, proposal, today):
    """Two-day equality on the actual structured observation, not page text.

    Visible-text fingerprints exclude JSON-LD, so source-watch-state keeps a
    separate digest per new edition to prevent first-seen script changes from
    being misrepresented as two-day-stable evidence.
    """
    if not isinstance(state, dict) or not isinstance(proposal, dict):
        return False
    records = state.setdefault("future_edition_observations", {})
    if not isinstance(records, dict):
        raise ValueError("état des futures éditions invalide")
    slug = proposal["slug"]
    comparison = {key: proposal[key] for key in
                  ("slug", "name", "startDate", "endDate", "originSlug", "officialSite")}
    digest = sha256(json.dumps(comparison, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    before = records.get(slug)
    try:
        verified_day = date.fromisoformat(today)
        first_seen = date.fromisoformat(before["firstSeen"]) if before else None
    except (ValueError, TypeError, KeyError):
        first_seen = None
    if not before or before.get("digest") != digest or first_seen is None:
        records[slug] = {"digest": digest, "firstSeen": today, "lastSeen": today,
                         "source": proposal["officialSite"]}
        return False
    # A repeated run on the same date is never a second independent day.
    if first_seen > verified_day:
        raise ValueError("observation future datée avant sa première observation")
    if before.get("lastSeen") != today:
        try:
            previous_day = date.fromisoformat(before["lastSeen"])
        except (ValueError, TypeError, KeyError):
            previous_day = None
        if previous_day is None or (verified_day - previous_day).days != 1:
            # A missing or contradictory observation breaks continuity.
            records[slug] = {"digest": digest, "firstSeen": today,
                             "lastSeen": today, "source": proposal["officialSite"]}
            return False
        before["lastSeen"] = today
    return first_seen < verified_day


def merge_edition_candidates(patch, proposals, origin, today):
    """Append-only private accumulation; never replace a pre-existing addition."""
    if not (patch.get("schema") == "grossesondes.patch.v1"
            and patch.get("safe_to_publish") is False
            and isinstance(patch.get("additions"), list)
            and isinstance(origin.get("festivals"), list)):
        raise ValueError("patch privé ou origine incompatible")
    ref = patch.get("source", {}).get("festivals", {})
    if (ref.get("url"), ref.get("generatedAt"), ref.get("count")) != (
            ORIGIN_URL, origin.get("generatedAt"), len(origin["festivals"])):
        raise ValueError("référence de base différente")
    occupied = {entry.get("slug") for entry in patch["additions"]}
    occupied.update(entry["slug"] for entry in origin["festivals"])
    added = 0
    for proposal in proposals:
        if (proposal.get("proofMode") != PROOF_MODE or
                proposal.get("slug") in occupied or len(patch["additions"]) >= 100):
            continue
        patch["additions"].append(proposal)
        occupied.add(proposal["slug"])
        added += 1
    if added:
        patch["generated_at"] = today
    return added
