"""Private typed proposals for category-level ticket availability only.

Two-day evidence is not publication permission. The public synchronizer
must independently fetch the immutable registered officialSite and recheck.
"""
from datetime import date

from structured_evidence import normalize

PROOF_MODE = "structured-tickets.v1"
ORIGIN_URL = "https://grosses-ondes.fr/data/festivals.json"
STATES = {"sold_out", "in_stock", "limited_availability", "preorder"}


def ticket_proposal(original, published, observation, today):
    if not all(isinstance(x, dict) for x in (original, published, observation)):
        return None
    same = ("slug", "name", "startDate", "endDate", "officialSite")
    if any(original.get(k) != published.get(k) for k in same):
        return None
    url = original.get("officialSite")
    if (not isinstance(url, str) or not url.startswith("https://")
            or observation.get("slug") != original.get("slug")
            or observation.get("source") != url
            or observation.get("publication_authorized") is not False
            or observation.get("sensitive_event_status") is not None
            or observation.get("startDate") != original.get("startDate")
            or observation.get("endDate") != original.get("endDate")):
        return None
    try:
        day = date.fromisoformat(today)
        start = date.fromisoformat(original["startDate"])
    except (TypeError, KeyError, ValueError):
        return None
    if start < day:
        return None
    categories = observation.get("ticket_categories")
    if not isinstance(categories, list) or not 1 <= len(categories) <= 12:
        return None
    found = set()
    formatted = []
    for row in categories:
        if not isinstance(row, dict) or set(row) != {"category", "availability"}:
            return None
        name, status = row["category"], row["availability"]
        if (not isinstance(name, str) or not isinstance(status, str)
                or status not in STATES or not 3 <= len(name) <= 120):
            return None
        key = "".join(normalize(name).split())
        if not 3 <= len(key) <= 90 or key in found:
            return None
        found.add(key)
        formatted.append({"name": name, "status": status})
    formatted.sort(key=lambda item: "".join(normalize(item["name"]).split()))
    return {
        "slug": original["slug"], "proofMode": PROOF_MODE,
        "changes": [{
            "field": "ticketAvailability",
            "before": original.get("ticketAvailability"),
            "after": {
                "source": url, "verifiedAt": today, "scope": "per_category_only",
                "categories": formatted,
            }
        }],
        "evidence": [url], "verified_at": today,
    }


def merge_ticket_proposals(patch, proposals, origin, today):
    """Replace only earlier automated ticket proposals, never a manual update.

    Preserve all unrelated patches and the immutable historic baseline.
    The public re-fetch, date freshness and anti-regression are independent.
    """
    if (patch.get("schema") != "grossesondes.patch.v1"
            or patch.get("safe_to_publish") is not False
            or not isinstance(patch.get("updates"), list)
            or not isinstance(origin.get("festivals"), list)):
        raise ValueError("patch ou référence invalide")
    ref = patch.get("source", {}).get("festivals", {})
    if (ref.get("url"), ref.get("generatedAt"), ref.get("count")) != (
            ORIGIN_URL, origin.get("generatedAt"), len(origin["festivals"])):
        raise ValueError("catalogue privé différent de la production")
    originals = {row["slug"]: row for row in origin["festivals"]}
    edited = 0
    for proposed in proposals:
        slug = proposed.get("slug")
        if slug not in originals:
            continue
        changes = proposed.get("changes", [])
        if (proposed.get("proofMode") != PROOF_MODE or len(changes) != 1
                or changes[0].get("field") != "ticketAvailability"
                or originals[slug].get("ticketAvailability") != changes[0].get("before")):
            continue
        positions = [i for i, row in enumerate(patch["updates"])
                     if row.get("slug") == slug]
        if positions:
            if len(positions) != 1:
                continue
            index = positions[0]
            existing = patch["updates"][index]
            if existing.get("proofMode") != PROOF_MODE:
                continue
            if existing.get("verified_at", "") >= proposed["verified_at"]:
                continue
            patch["updates"][index] = proposed
        else:
            if len(patch["updates"]) >= 200:
                continue
            patch["updates"].append(proposed)
        edited += 1
    if edited:
        patch["generated_at"] = today
    return edited


def withdraw_contradicted_ticket_proposals(patch, conflicted_slugs):
    """Withdraw only automated ticket candidates contradicted by vendor review.

    This never touches manual updates, programming, dates, or history. A veto
    does not publish a vendor finding or certify any ticket state.
    """
    if (patch.get("schema") != "grossesondes.patch.v1"
            or patch.get("safe_to_publish") is not False
            or not isinstance(patch.get("updates"), list)
            or not isinstance(conflicted_slugs, set)):
        raise ValueError("retrait billetterie invalide")
    kept, removed = [], 0
    for row in patch["updates"]:
        changes = row.get("changes") if isinstance(row, dict) else None
        automated_ticket = (
            isinstance(row, dict) and row.get("slug") in conflicted_slugs
            and row.get("proofMode") == PROOF_MODE
            and isinstance(changes, list) and len(changes) == 1
            and isinstance(changes[0], dict)
            and changes[0].get("field") == "ticketAvailability"
        )
        if automated_ticket:
            removed += 1
        else:
            kept.append(row)
    if removed:
        patch["updates"] = kept
    return removed
