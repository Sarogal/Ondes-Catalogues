"""Isolated historical GPS application boundary.

Only a new, independent rehearsal may produce the candidate. Neither an
intake patch nor a persisted proposal is authority. No disk/network writes
occur here; deployment belongs to the existing serialized Publisher.
"""
from datetime import date
from ptitesondes_catalogue_geo_correction_preview import (
    preview, digest, GEO_FIELDS, MAX_EVENTS,
)
from ptitesondes_catalogue_geo_research import point


def _require(ok, reason):
    if not ok:
        raise ValueError("historical_gps_" + reason)


def _index(doc):
    _require(isinstance(doc, dict) and isinstance(doc.get("events"), list),
             "invalid_catalogue")
    rows = doc["events"]
    _require(all(isinstance(e, dict) and isinstance(e.get("id"), str)
                 and e["id"] for e in rows), "invalid_id")
    index = {e["id"]: e for e in rows}
    _require(len(index) == len(rows), "duplicate_id")
    return index


def validate_transition(reference, current, candidate, audit, today):
    """Defence in depth, not proof: validate a fresh rehearsal's exact diff.

    A complete historical record must match the trusted reference before
    changing it. Reference disagreement, non-null partial points, expired
    events, unknown proposal IDs and non-geographic changes fail closed.
    """
    ref, before, after = map(_index, (reference, current, candidate))
    _require(list(before) == list(after), "ids_or_order_changed")
    _require({k:v for k,v in current.items() if k != "events"} ==
             {k:v for k,v in candidate.items() if k != "events"},
             "metadata_changed")
    _require(isinstance(audit, dict)
             and audit.get("schema") == "ptitesondes.historical_gps_correction_preview.v1"
             and audit.get("day") == today.isoformat()
             and audit.get("publication_ready") is False
             and type(audit.get("public_writes")) is int
             and audit["public_writes"] == 0
             and audit.get("before_sha256") == digest(current)
             and audit.get("after_sha256") == digest(candidate),
             "invalid_audit")
    proposals = audit.get("proposals")
    _require(isinstance(proposals, list) and len(proposals) <= MAX_EVENTS
             and type(audit.get("proposed_count")) is int
             and audit["proposed_count"] == len(proposals)
             and all(isinstance(p, dict) and isinstance(p.get("id"), str)
                     for p in proposals), "invalid_proposals")
    indexed = {p["id"]:p for p in proposals}
    changed = {key for key in before if before[key] != after[key]}
    _require(len(indexed) == len(proposals) and set(indexed) == changed,
             "proposal_diff_mismatch")
    for key in changed:
        old, new, p = before[key], after[key], indexed[key]
        _require(ref.get(key) == old, "reference_disagreement")
        _require(old.get("lat") is None and old.get("lng") is None,
                 "existing_or_partial_point")
        try:
            start = date.fromisoformat(old["date_start"])
            end = date.fromisoformat(old["date_end"])
        except (TypeError, KeyError, ValueError):
            raise ValueError("historical_gps_invalid_date") from None
        _require(start <= end and end >= today, "expired_or_invalid_date")
        _require({k:v for k,v in old.items() if k not in GEO_FIELDS} ==
                 {k:v for k,v in new.items() if k not in GEO_FIELDS},
                 "non_geo_change")
        _require(point(new) is not None
                 and new.get("geo_precision") == "venue"
                 and new.get("geo_verified_at") == today.isoformat(),
                 "invalid_new_point")
        _require(p.get("before_sha256") == digest(old)
                 and p.get("after_sha256") == digest(new)
                 and p.get("event_source") == old.get("source_url")
                 and (p.get("lat"), p.get("lng")) == point(new)
                 and isinstance(p.get("official"), str)
                 and bool(p.get("official"))
                 and isinstance(p.get("geo_source"), str)
                 and bool(p.get("geo_source")), "proposal_mismatch")
    return len(changed)


def prepare_corrections(reference, current, today, checkpoint, **live_research):
    """Recompute independent proofs now and return a validated candidate.

    The checkpoint is a queue hint. No prior proposal or coordinates can be
    supplied as proof. Callers must use the production readers in deployment.
    """
    candidate, audit = preview(current, today, checkpoint, **live_research)
    count = validate_transition(reference, current, candidate, audit, today)
    return candidate, audit, count
