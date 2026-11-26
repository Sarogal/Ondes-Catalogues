"""Retirement of proven erroneous artist identities, not ordinary inactive artists.

Only a completed, independently validated identity repair can authorize this
cleanup. Immutable original event and artist approvals remain in the private
ledger. A public receipt is not an independent source of authority.
Integration with the production Publisher is intentionally separate.
"""
from __future__ import annotations

import copy

from scripts import concert_published_lineup_contract as lineup

KEY = "retiredArtistIds"


def require(ok, reason):
    if not ok:
        raise ValueError("Artist identity retirement: " + reason)


def _archives(approvals):
    archives = {}
    for row in approvals["approvals"]:
        if row.get("reviewDecision") != "approved":
            continue
        for artist in row.get("newArtists", []):
            aid = artist.get("id")
            name = artist.get("name")
            if (isinstance(aid, str) and isinstance(name, str)
                    and not artist.get("aliases")):
                exact = {"id": aid, "name": name, "aliases": []}
                require(aid not in archives or archives[aid] == exact,
                        "conflicting immutable original artist records")
                archives[aid] = exact
    return archives


def candidates(reference, catalogue, approvals, today, *, include_pending=True):
    """Return exact retireable records after validating applied corrections.

    A date having passed is not a deletion criterion. Keep all reference
    artists, every artist still used by any public event, source authority,
    correction target or unpublished signed event.
    """
    protected = {a["id"] for a in reference["artists"]}
    public = {e["id"]: e for e in catalogue["events"]}
    artist_map = {a["id"]: a for a in catalogue["artists"]}
    originals = {a["event"]["id"]: a for a in approvals["approvals"]}
    referenced = {aid for e in public.values() for aid in e["artistIds"]}
    for venue in approvals.get("venueApprovals", []):
        referenced.add(venue.get("eventBinding", {}).get("authorityArtistId"))
    corrections = approvals.get("lineupCorrections", [])
    correction_ids = {r["eventId"] for r in corrections}
    require(len(correction_ids) == len(corrections), "duplicate correction")
    if include_pending:
        excluded = {r.get("eventId") for r in catalogue.get("editorialExclusions", [])}
        for eid, row in originals.items():
            if eid not in public and eid not in excluded:
                referenced.update(row["event"]["artistIds"])
    removed = set()
    for row in corrections:
        referenced.update(row["artistIds"])
        proof = row.get("officialEvidence", [{}])[0].get("proofType")
        if proof not in (lineup.PROMOTIONAL_PROOF, lineup.bill_identity.PROOF):
            continue
        event = public.get(row["eventId"])
        if not event or event["artistIds"] != row["artistIds"] or event["title"] != row["title"]:
            continue  # not yet applied: no retirement permission
        original = originals.get(row["eventId"])
        plan = lineup.plan(row, original, catalogue, today)
        require(event.get("lastVerified") == plan["reviewedAt"]
                and event.get("history")
                and event["history"][-1].get("change") == plan["historyChange"],
                "corrected event lacks exact applied history")
        removed.update(set(row["oldArtistIds"]) - set(row["artistIds"]))
    archives = _archives(approvals)
    result = {}
    for aid in sorted(removed - protected - referenced):
        if aid in archives and artist_map.get(aid) == archives[aid]:
            result[aid] = archives[aid]
    return result


def restore(reference, catalogue, approvals, today):
    """Reconstruct exact retired artist records for internal historical guards.

    Do not accept unknown, duplicate or still-public receipts. The immutable
    private records and the corrected public event must independently prove
    each receipt. An old source can be replayed without any network access.
    """
    ids = catalogue.get(KEY, [])
    require(isinstance(ids, list) and all(isinstance(a, str) and a for a in ids)
            and len(ids) == len(set(ids)), "invalid public receipts")
    if not ids:
        return catalogue, set()
    restored = copy.deepcopy(catalogue)
    restored.pop(KEY, None)
    archives = _archives(approvals)
    current_ids = {a["id"] for a in restored["artists"]}
    require(all(a in archives and a not in current_ids for a in ids),
            "receipt lacks unique immutable private original")
    restored["artists"].extend(copy.deepcopy(archives[a]) for a in ids)
    eligible = candidates(reference, restored, approvals, today, include_pending=False)
    require(set(ids).issubset(eligible), "receipt lacks exact applied identity correction")
    return restored, set(ids)


def retire(reference, catalogue, approvals, today, already=()):
    """Compute the exact public-only retirement delta after Publisher checks.

    A future signed event referencing an already-retired identity must be held
    by the Publisher before this function is called, never silently published.
    """
    eligible = candidates(reference, catalogue, approvals, today)
    historical = candidates(reference, catalogue, approvals, today, include_pending=False)
    require(set(already).issubset(historical),
            "retired artist became referenced or correction history changed")
    retire_ids = set(eligible) | set(already)
    if not retire_ids:
        return catalogue, 0
    result = copy.deepcopy(catalogue)
    result["artists"] = [a for a in result["artists"] if a["id"] not in retire_ids]
    result[KEY] = sorted(retire_ids)
    return result, len(retire_ids - set(already))
