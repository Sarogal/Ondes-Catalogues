"""Append-only contract for generic corrections of existing venue pins.

A signed row never replaces a venue identity or its original approval.
The Publisher must verify the original against its existing protections,
then replay the evidence on first application. Historical signed results
can be replayed offline after the event page disappears.
"""
from __future__ import annotations

import copy
import datetime as dt
import math
import re

from automation.concerts import existing_venue_geo_evidence as evidence

KEY = "existingVenueGeoCorrections"
PATCH = frozenset({"address", "postalCode", "latitude", "longitude",
                   "geoSource", "geoPrecision"})
PROOF = "existing-venue-official-address-ban-osm-v1"
FIELDS = frozenset({"venueId", "eventId", "eventDate", "officialUrl",
                    "officialVenueSourceUrl", "originalVenue", "venuePatch",
                    "reviewDecision", "reviewedBy", "reviewedAt", "proofType"})
MAX_PENDING = 4


def require(ok, message):
    if not ok:
        raise ValueError("Existing venue geo correction: " + message)


def signed_proposal(proposal, today):
    """Convert a research result into a candidate for Publisher preflight.

    The caller must not persist it until an independent Publisher replay
    accepts the exact delta. This function itself grants no authority.
    """
    require(isinstance(proposal, dict)
            and proposal.get("schema") == evidence.SCHEMA
            and proposal.get("publicationAllowed") is False
            and proposal.get("publisherAuthorityGranted") is False,
            "invalid research proposal")
    return {**{k: copy.deepcopy(proposal[k]) for k in (
        "venueId", "eventId", "eventDate", "officialUrl",
        "officialVenueSourceUrl", "originalVenue", "venuePatch")},
        "reviewDecision": "approved", "reviewedBy": "independent-official-verifier",
        "reviewedAt": today.isoformat(), "proofType": PROOF}


def plan(row, catalogue, today):
    require(isinstance(row, dict) and set(row) == FIELDS
            and row["reviewDecision"] == "approved"
            and row["reviewedBy"] == "independent-official-verifier"
            and row["proofType"] == PROOF, "invalid correction signature")
    try:
        checked = dt.date.fromisoformat(row["reviewedAt"])
        event_day = dt.date.fromisoformat(row["eventDate"])
    except (ValueError, TypeError) as exc:
        raise ValueError("Existing venue geo correction: invalid date") from exc
    require(checked.isoformat() == row["reviewedAt"] and checked <= today
            and event_day.isoformat() == row["eventDate"] and checked <= event_day,
            "invalid correction chronology")
    original, patch = row["originalVenue"], row["venuePatch"]
    require(isinstance(original, dict) and isinstance(patch, dict)
            and set(patch) == PATCH and PATCH <= set(original)
            and isinstance(row["venueId"], str) and row["venueId"]
            and original.get("id") == row["venueId"]
            and evidence.eligible(original), "only an exact coarse original may be patched")
    require(isinstance(patch["address"], str)
            and 6 <= len(patch["address"]) <= 160
            and isinstance(patch["postalCode"], str)
            and re.fullmatch(r"\d{5}", patch["postalCode"])
            and isinstance(patch["geoSource"], str)
            and re.fullmatch(r"https://www\.openstreetmap\.org/(node|way)/[1-9]\d*", patch["geoSource"])
            and patch["geoPrecision"] in {"named-site-point", "named-site-area"}
            and patch["geoPrecision"] == ("named-site-point" if "/node/" in patch["geoSource"]
                                         else "named-site-area")
            and all(type(patch[k]) in (int, float) and math.isfinite(patch[k])
                    for k in ("latitude", "longitude"))
            and -56 <= patch["latitude"] <= 52 and -180 <= patch["longitude"] <= 180,
            "invalid named geographic patch")
    target = dict(original, **patch)
    require(evidence.address_source.eligible_address(target),
            "invalid corrected postal identity")
    a = evidence.intake.valid_https(row["officialUrl"])
    b = evidence.intake.valid_https(row["officialVenueSourceUrl"])
    require(bool(a and b) and a.removeprefix("www.") == b.removeprefix("www."),
            "invalid official source attribution")
    events = [e for e in catalogue["events"] if e.get("id") == row["eventId"]]
    require(len(events) == 1, "published event anchor missing or duplicate")
    event = events[0]
    require(event.get("venueId") == row["venueId"]
            and event.get("date") == row["eventDate"]
            and event.get("officialUrl") == row["officialUrl"]
            and event.get("sourceType") == "salle", "published event anchor differs")
    venues = [v for v in catalogue["venues"] if v.get("id") == row["venueId"]]
    require(len(venues) == 1 and venues[0] in (original, target),
            "published venue is neither signed original nor exact correction")
    return {"original": original, "target": target, "event": event,
            "already": venues[0] == target, "checked": checked,
            "eventDay": event_day}


def prepare(catalogue, approvals, today, *, verify_one=None):
    """Return normalized original view and validated correction plans.

    The original view MUST pass the unchanged Publisher historical checks.
    A pending correction is re-fetched, not trusted from the signed proposal.
    """
    rows = approvals.get(KEY, [])
    require(isinstance(rows, list) and len(rows) <= len(catalogue["venues"]),
            "invalid correction ledger")
    ids = [r.get("venueId") if isinstance(r, dict) else None for r in rows]
    require(all(isinstance(i, str) for i in ids) and len(set(ids)) == len(ids),
            "duplicate or malformed correction venue ID")
    plans = {row["venueId"]: plan(row, catalogue, today) for row in rows}
    require(sum(not p["already"] for p in plans.values()) <= MAX_PENDING,
            "pending corrections exceed review budget")
    verify_one = evidence.verify if verify_one is None else verify_one
    for row in rows:
        p = plans[row["venueId"]]
        if p["already"]:
            continue
        require(p["event"]["status"] == "confirmed" and p["eventDay"] >= today
                and (today - p["checked"]).days <= 7,
                "first application needs fresh confirmed event proof")
        fresh = verify_one(p["event"], p["original"])
        require(signed_proposal(fresh, p["checked"]) == row,
                "fresh independent evidence disagrees with signed correction")
    return restore_originals(catalogue, plans), plans


def restore_originals(catalogue, plans):
    """Normalize only exact signed states; no arbitrary fields are hidden."""
    if not plans:
        return catalogue
    result = copy.deepcopy(catalogue)
    seen = set()
    for i, venue in enumerate(result["venues"]):
        p = plans.get(venue["id"])
        if p is None:
            continue
        require(venue in (p["original"], p["target"]),
                "venue altered outside signed geographic patch")
        result["venues"][i] = copy.deepcopy(p["original"])
        seen.add(venue["id"])
    require(seen == set(plans), "signed venue missing")
    return result


def apply(catalogue, plans):
    """Apply validated plans AFTER original venue history validation."""
    if not plans:
        return 0
    seen = set()
    for i, venue in enumerate(catalogue["venues"]):
        p = plans.get(venue["id"])
        if p is None:
            continue
        require(venue == p["original"],
                "original conflicts with another signed venue change")
        catalogue["venues"][i] = copy.deepcopy(p["target"])
        seen.add(venue["id"])
    require(seen == set(plans), "signed venue missing after original validation")
    return sum(not p["already"] for p in plans.values())
