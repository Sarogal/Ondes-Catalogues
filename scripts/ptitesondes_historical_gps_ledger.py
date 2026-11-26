"""Trusted Git ledger for already applied, independently checked GPS repairs.

The original Infomaniak baseline remains unchanged, including patch binding
metadata. A committed ledger can reconcile only exact historical missing-GPS
records; a private intake dossier can never supply or extend this ledger.
"""
from datetime import date
from ptitesondes_catalogue_geo_correction_preview import digest, GEO_FIELDS
from ptitesondes_catalogue_geo_research import point

SCHEMA = "ptitesondes.historical_gps_ledger.v1"


def empty_ledger():
    return {"schema": SCHEMA, "repairs": {}}


def require(ok, reason):
    if not ok:
        raise ValueError("historical_gps_ledger_" + reason)


def index(doc):
    events = doc["events"]
    result = {e["id"]: e for e in events}
    require(len(result) == len(events), "duplicate_id")
    return result


def reconcile(reference, current, ledger):
    """Reconstruct reference records only from exact committed repairs.

    The current catalogue must agree byte-for-byte in canonical JSON with
    each recorded corrected event. Other reference differences remain
    subject to the existing Publisher historical guard.
    """
    require(isinstance(ledger, dict) and set(ledger) == {"schema", "repairs"}
            and ledger["schema"] == SCHEMA and isinstance(ledger["repairs"], dict),
            "invalid_schema")
    ref, public = index(reference), index(current)
    amended = {}
    for uid, row in ledger["repairs"].items():
        require(uid in ref and uid in public and isinstance(row, dict)
                and set(row) == {"before_sha256", "after_sha256", "geo"},
                "unknown_or_invalid_repair")
        old = ref[uid]
        require(row["before_sha256"] == digest(old), "reference_changed")
        require(old.get("lat") is None and old.get("lng") is None, "existing_point")
        geo = row["geo"]
        require(isinstance(geo, dict) and set(geo) == GEO_FIELDS
                and point(geo) is not None and geo["geo_precision"] == "venue",
                "invalid_geo")
        try:
            checked = date.fromisoformat(geo["geo_verified_at"])
            start = date.fromisoformat(old["date_start"])
            end = date.fromisoformat(old["date_end"])
        except (ValueError, TypeError, KeyError):
            raise ValueError("historical_gps_ledger_invalid_date") from None
        require(start <= end and checked <= end, "invalid_date")
        updated = dict(old, **geo)
        require(row["after_sha256"] == digest(updated) and updated == public[uid],
                "current_record_changed")
        amended[uid] = updated
    return dict(reference, events=[amended.get(e["id"], e) for e in reference["events"]])


def record_validated_repairs(reference, current, candidate, ledger, audit, today):
    """Extend only after a freshly generated candidate passes the GPS guard.

    Import the guard lazily so the read/reconcile route remains independent.
    The caller must obtain the audit by running live prepare_corrections, not
    by loading a private proposal. No filesystem writes occur here.
    """
    from ptitesondes_historical_gps_apply_guard import validate_transition
    effective = reconcile(reference, current, ledger)
    count = validate_transition(effective, current, candidate, audit, today)
    out = {"schema": SCHEMA, "repairs": dict(ledger["repairs"])}
    before, after = index(current), index(candidate)
    for p in audit["proposals"]:
        uid = p["id"]
        require(uid not in out["repairs"], "already_recorded")
        out["repairs"][uid] = {
            "before_sha256": digest(before[uid]),
            "after_sha256": digest(after[uid]),
            "geo": {k: after[uid][k] for k in GEO_FIELDS},
        }
    require(len(out["repairs"]) == len(ledger["repairs"]) + count, "count_mismatch")
    reconcile(reference, candidate, out)
    return out
