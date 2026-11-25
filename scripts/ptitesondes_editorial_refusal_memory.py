"""Private, reversible editorial deferral, never a publication permission."""
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re

from ptitesondes_oa_first_party_admission import admit_live_openagenda
from ptitesondes_national_backlog_bridge import _read

SCHEMA = "ptitesondes.private_editorial_refusal_memory.v1"
TTL = timedelta(hours=12)
MAX_ENTRIES = 4000
MAX_QUEUE_RECHECKS = 8
REASONS = frozenset({
    "oa_direct_child_audience_missing",
    "oa_direct_out_of_editorial_scope",
    "oa_direct_primary_activity_outside_scope",
    "oa_direct_evergreen_on_demand_review",
})
HEX = re.compile(r"[0-9a-f]{64}")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True,
        ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def policy_fingerprint():
    # Changes to the admission/classification implementation invalidate the
    # advisory state, even before the normal expiry.
    root = Path(__file__).resolve().parent
    files = ("ptitesondes_oa_first_party_admission.py",
             "ptitesondes_primary_editorial.py",
             "ptitesondes_oa_evergreen_on_demand.py",
             "ptitesondes_candidate_promotion.py",
             "ptitesondes_family_activity_classification.py",
             "ptitesondes_family_national_scope.py",
             "ptitesondes_openagenda_v2_direct_evidence.py",
             "ptitesondes_openagenda_national_event_research.py",
             "merge_policy.py",
             Path(__file__).name)
    return digest([hashlib.sha256((root / name).read_bytes()).hexdigest()
                   for name in files])


def empty_memory():
    return {"schema": SCHEMA, "policy": policy_fingerprint(),
            "cursor": 0, "entries": {}, "attempt_sequence": 0, "attempts": {}}


def checked_time(row):
    try:
        t = datetime.fromisoformat(row["checked_at"])
        if t.tzinfo is not None and t.utcoffset() is not None:
            return t.astimezone(timezone.utc)
    except (KeyError, TypeError, ValueError, OverflowError):
        pass
    return None


def fresh_memory(raw, now):
    result = empty_memory()
    if (type(raw) is not dict or raw.get("schema") != SCHEMA
            or raw.get("policy") != result["policy"]
            or type(raw.get("entries")) is not dict
            or len(raw["entries"]) > MAX_ENTRIES
            or type(raw.get("cursor")) is not int
            or not 0 <= raw["cursor"] < 10**12):
        return result
    result["cursor"] = raw["cursor"]
    sequence, attempts = raw.get("attempt_sequence", 0), raw.get("attempts", {})
    if (type(sequence) is int and 0 <= sequence < 10**12
            and type(attempts) is dict and len(attempts) <= MAX_ENTRIES):
        result["attempt_sequence"] = sequence
        result["attempts"] = {key: value for key, value in attempts.items()
                              if type(key) is str and HEX.fullmatch(key)
                              and type(value) is int and 0 < value <= sequence}
    for k, row in raw["entries"].items():
        if (type(k) is not str or not HEX.fullmatch(k)
                or type(row) is not dict or type(row.get("reason")) is not str
                or row["reason"] not in REASONS
                or not all(type(row.get(field)) is str
                           and HEX.fullmatch(row[field])
                           for field in ("clue_sha256", "source_sha256"))):
            continue
        checked = checked_time(row)
        if checked is not None and timedelta(0) <= now - checked < TTL:
            result["entries"][k] = {field: row[field] for field in (
                "reason", "checked_at", "clue_sha256", "source_sha256")}
    return result


def load_memory(path, now):
    # Broken advisory state may never halt collection or become a denial.
    try:
        raw, _ = _read(path, 2_000_000)
    except (OSError, ValueError, TypeError, UnicodeError):
        raw = None
    return fresh_memory(raw, now)


def identity_key(identity):
    slug, uid, day, _ = identity
    return digest([slug, uid, day])


def attempt_key(identity, clue_sha):
    # A changed clue is a fresh research opportunity, never a permanent denial.
    return digest([identity, clue_sha])


def retain_active_attempts(memory, keys):
    memory["attempts"] = {key: value for key, value in memory["attempts"].items()
                          if key in keys}


def mark_attempt(memory, key):
    if memory["attempt_sequence"] >= 10**12 - 1:
        # Defensive wrap; no opportunity is blocked by counter exhaustion.
        memory["attempt_sequence"] = 0
        memory["attempts"] = {}
    memory["attempt_sequence"] += 1
    if len(memory["attempts"]) < MAX_ENTRIES or key in memory["attempts"]:
        memory["attempts"][key] = memory["attempt_sequence"]


def can_defer(identity, today):
    # Never postpone a session that takes place today or tomorrow.
    return date.fromisoformat(identity[2]) > today + timedelta(days=1)


def deferred(memory, identity, clue_sha, today, now):
    row = memory["entries"].get(identity_key(identity))
    if row is None or not can_defer(identity, today):
        return False
    checked = checked_time(row)
    return (row["reason"] in REASONS and checked is not None
            and timedelta(0) <= now - checked < TTL
            and row["clue_sha256"] == clue_sha)


def remember_refusal(memory, identity, clue_sha, dossier, agenda, event,
                     published, today, now):
    """Only classify an exact live record; never retain positive admissions."""
    k = identity_key(identity)
    memory["entries"].pop(k, None)
    if not can_defer(identity, today):
        return False
    try:
        if (type(event) is dict and "uid" not in event
                and type(event.get("event")) is dict
                and event["event"].get("uid") == identity[1]):
            event = event["event"]
        _, reason = admit_live_openagenda(
            dossier["lead"], dossier["date_start"], agenda, event,
            published, published, today, as_of_utc=now)
        if reason not in REASONS:
            return False
        source = digest(event)
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, OverflowError):
        return False
    if len(memory["entries"]) >= MAX_ENTRIES:
        return False
    memory["entries"][k] = {
        "reason": reason, "checked_at": now.isoformat(),
        "clue_sha256": clue_sha, "source_sha256": source,
    }
    return True
