"""Deterministic, conservative promotion from monitored JSON-LD to patch proposals.

This runs only in the PRIVATE intake. Its output remains safe_to_publish:false.
The public synchronizer MUST independently re-download the edition's registered
officialSite and validate the proposed lineup fields before any publication.
"""
from datetime import date
import re

from structured_evidence import artist_key, root_name

PROOF_MODE = "structured-roster.v1"
ORIGIN_URL = "https://grosses-ondes.fr/data/festivals.json"


def roster_proposal(original, published, observations, previous, digest, today):
    """Propose additive lineup only after unchanged evidence across calendar days.

    Return None for any ambiguous, stale, changed-date, cancelled, alias,
    differently published, or otherwise not fully supported observation.
    """
    if not (isinstance(original, dict) and isinstance(published, dict)
            and isinstance(previous, dict) and isinstance(observations, list)
            and len(observations) == 1):
        return None
    try:
        today_day = date.fromisoformat(today)
        prior_day = date.fromisoformat(previous["lastChanged"])
        verified_before = date.fromisoformat(original["lastVerified"])
    except (ValueError, KeyError, TypeError):
        return None
    if not (prior_day < today_day and verified_before <= today_day
            and previous.get("sha256") == digest):
        return None
    protected = ("slug", "name", "startDate", "endDate",
                 "lineup", "bands", "lastVerified", "officialSite")
    if any(original.get(key) != published.get(key) for key in protected):
        return None
    source_url = original.get("officialSite")
    start_date = original.get("startDate")
    end_date = original.get("endDate")
    if not (isinstance(source_url, str) and source_url.startswith("https://")
            and isinstance(start_date, str) and isinstance(end_date, str)):
        return None
    obs = observations[0]
    if (obs.get("slug") != original.get("slug")
            or obs.get("source_url") != source_url
            or obs.get("startDate_source") != start_date
            or obs.get("endDate_source") != end_date
            or obs.get("publication_authorized") is not False):
        return None
    title = obs.get("name_on_source")
    if not isinstance(title, str) or root_name(title) != root_name(original.get("name", "")):
        return None
    year = start_date[:4]
    if not re.search(r"\b" + re.escape(year) + r"\b", title):
        return None
    hints = obs.get("hints")
    if not isinstance(hints, dict) or not hints or not set(hints) <= {
        "new_performers", "place_name_unverified"
    }:
        return None
    added = hints.get("new_performers")
    old = original.get("lineup")
    if not (isinstance(added, list) and 1 <= len(added) <= 12
            and isinstance(old, list) and len(old) > 0
            and type(original.get("bands")) is int and original["bands"] == len(old)
            and all(isinstance(name, str) and 3 <= len(artist_key(name)) <= 90 for name in added)):
        return None
    merged = old + added
    keys = [artist_key(name) for name in merged]
    if len(set(keys)) != len(keys):
        return None
    return {
        "slug": original["slug"],
        "proofMode": PROOF_MODE,
        "changes": [
            {"field": "lineup", "before": old, "after": merged},
            {"field": "bands", "before": len(old), "after": len(merged)},
            {"field": "lastVerified", "before": original["lastVerified"], "after": today},
        ],
        "evidence": [source_url],
        "verified_at": today,
    }


def merge_proposals(patch, proposals, origin, today):
    """Append only nonconflicting, baseline-anchored proposals.

    Never replace a manual proposal, and never overwrite evidence already
    collected across multiple days. Caller persists only on real changes.
    """
    if patch.get("schema") != "grossesondes.patch.v1" or patch.get("safe_to_publish") is not False:
        raise ValueError("schéma de patch privé ou garde de publication invalide")
    if not isinstance(patch.get("updates"), list) or not isinstance(origin.get("festivals"), list):
        raise ValueError("propositions ou catalogue d'origine invalides")
    ref = patch.get("source", {}).get("festivals", {})
    if (ref.get("url"), ref.get("generatedAt"), ref.get("count")) != (
            ORIGIN_URL, origin.get("generatedAt"), len(origin["festivals"])):
        raise ValueError("référence du patch différente de la production figée")
    original = {e["slug"]: e for e in origin["festivals"]}
    touched = {e.get("slug") for e in patch["updates"]}
    count = 0
    for proposed in proposals:
        slug = proposed.get("slug")
        if slug in touched or slug not in original or len(patch["updates"]) >= 200:
            continue
        before = {c.get("field"): c.get("before") for c in proposed.get("changes", [])}
        if any(original[slug].get(field) != value for field, value in before.items()):
            continue
        patch["updates"].append(proposed)
        touched.add(slug)
        count += 1
    if count:
        patch["generated_at"] = today
    return count
