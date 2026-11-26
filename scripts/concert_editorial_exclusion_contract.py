"""Append-only editorial exclusions; no implicit cancellation or data deletion.

The private ledger retains the exact previously published snapshot. The
public catalogue stores a minimal receipt outside the visible events array.
Restoring a verified receipt to the internal historical view permits the
existing venue/event guards to continue checking their original approvals.
This module is not yet wired into the production Publisher.
"""
from __future__ import annotations

import copy
import datetime as dt

from automation.concerts import editorial_genre_reconciliation as evidence

KEY = "editorialCorrections"
RECEIPTS = "editorialExclusions"
FIELDS = frozenset({"reviewDecision", "reviewedBy", "reviewedAt",
                    "originalEvent", "evidence"})
MAX_PENDING = 4


def require(ok, reason):
    if not ok:
        raise ValueError("Editorial exclusion: " + reason)


def signed_proposal(event, proof):
    require(isinstance(proof, dict) and proof.get("schema") == evidence.SCHEMA
            and proof.get("publicationAllowed") is False
            and proof.get("eventId") == event.get("id"),
            "research proof does not bind original event")
    return {"reviewDecision": "approved",
            "reviewedBy": "independent-official-verifier",
            "reviewedAt": proof["checkedAt"],
            "originalEvent": copy.deepcopy(event),
            "evidence": copy.deepcopy(proof)}


def plan(row, approval, venue, today):
    require(isinstance(row, dict) and set(row) == FIELDS
            and row["reviewDecision"] == "approved"
            and row["reviewedBy"] == "independent-official-verifier",
            "invalid private corrective signature")
    event = row["originalEvent"]
    proof = row["evidence"]
    require(isinstance(event, dict) and isinstance(proof, dict)
            and isinstance(venue, dict), "missing original identity")
    original_proof, _ = evidence.source(approval, event, venue)
    try:
        checked = dt.date.fromisoformat(row["reviewedAt"])
        event_date = dt.date.fromisoformat(event["date"])
    except (ValueError, TypeError, KeyError) as exc:
        raise ValueError("Editorial exclusion: invalid chronology") from exc
    require(checked.isoformat() == row["reviewedAt"]
            and checked <= today and checked <= event_date,
            "future or expired signature")
    require(proof.get("explicitOutsideGenres")
            and all(g in evidence.OUTSIDE for g in
                    evidence._norm_list(proof["explicitOutsideGenres"])),
            "no explicit outside-scope genre evidence")
    expected = {
        "schema": evidence.SCHEMA, "eventId": event["id"],
        "eventDate": event["date"], "venueId": event["venueId"],
        "officialUrl": event["officialUrl"], "checkedAt": row["reviewedAt"],
        "agendaUid": int(original_proof["officialOpenAgendaUid"]),
        "eventUid": int(original_proof["officialOpenAgendaEventUid"]),
        "reason": "venue-name-genre-contamination",
        "oldGenres": event["genres"],
        "explicitOutsideGenres": proof["explicitOutsideGenres"],
        "publicationAllowed": False,
    }
    require(proof == expected, "proof differs from exact approved identity")
    receipt = {"eventId": event["id"], "date": row["reviewedAt"],
               "reason": proof["reason"]}
    return {"event": event, "receipt": receipt, "checked": checked,
            "eventDate": event_date}


def prepare(reference, current, approvals, today, *, fetch):
    """Restore already excluded rows solely for the existing internal guards.

    A pending correction is eligible only after an independent fresh replay.
    A missing public receipt can never legitimize a missing published event.
    Network failures defer only the relevant correction; they are not proofs.
    """
    rows = approvals.get(KEY, [])
    receipts = current.get(RECEIPTS, [])
    require(isinstance(rows, list) and isinstance(receipts, list),
            "invalid correction or receipt ledger")
    original_ids = {e["id"] for e in reference["events"]}
    signed = {a["event"]["id"]: a for a in approvals["approvals"]
              if isinstance(a, dict) and isinstance(a.get("event"), dict)
              and isinstance(a["event"].get("id"), str)}
    public_events = {e["id"]: e for e in current["events"]}
    venues = {v["id"]: v for v in current["venues"]}
    plans = {}
    for row in rows:
        require(isinstance(row, dict) and isinstance(row.get("originalEvent"), dict),
                "missing archived event")
        event = row["originalEvent"]
        eid = event.get("id")
        require(isinstance(eid, str) and eid not in plans
                and eid not in original_ids and eid in signed,
                "duplicate, unsigned or immutable reference target")
        p = plan(row, signed[eid], venues.get(event.get("venueId")), today)
        plans[eid] = p
    receipt_by_id = {}
    for receipt in receipts:
        require(isinstance(receipt, dict), "invalid public receipt")
        eid = receipt.get("eventId")
        require(isinstance(eid, str) and eid in plans and eid not in receipt_by_id
                and receipt == plans[eid]["receipt"] and eid not in public_events,
                "receipt has no exact persistent correction or event still visible")
        receipt_by_id[eid] = receipt
    restored = copy.deepcopy(current)
    restored.pop(RECEIPTS, None)
    pending = []
    for eid, p in plans.items():
        if eid in receipt_by_id:
            p["already"] = True
            restored["events"].append(copy.deepcopy(p["event"]))
        else:
            require(public_events.get(eid) == p["event"],
                    "pending correction requires exact prior public snapshot")
            p["already"] = False
            p["deferred"] = True
            if p["eventDate"] >= today and (today - p["checked"]).days <= 7:
                pending.append(eid)
    # Bounded rotation prevents a failing source from starving the queue.
    offset = (today.toordinal() * MAX_PENDING) % len(pending) if pending else 0
    for eid in (pending[offset:] + pending[:offset])[:MAX_PENDING]:
        p = plans[eid]
        try:
            fresh = evidence.verify(signed[eid], p["event"],
                venues[p["event"]["venueId"]], p["checked"], fetch=fetch)
            require(signed_proposal(p["event"], fresh) ==
                    next(row for row in rows if row["originalEvent"]["id"] == eid),
                    "fresh evidence differs from signature")
        except (ValueError, TypeError, KeyError, OSError, TimeoutError):
            continue
        p["deferred"] = False
    return restored, plans


def apply(catalogue, plans):
    """Remove only the exact, validated event from the visible events array."""
    result = copy.deepcopy(catalogue)
    active = {eid: p for eid, p in plans.items() if not p.get("deferred")}
    public = {e["id"]: e for e in result["events"]}
    require(all(public.get(eid) == p["event"] for eid, p in active.items()),
            "event mutated after internal historical validation")
    result["events"] = [e for e in result["events"] if e["id"] not in active]
    if active:
        result[RECEIPTS] = [copy.deepcopy(p["receipt"]) for p in active.values()]
    return result, sum(not p["already"] for p in active.values())
