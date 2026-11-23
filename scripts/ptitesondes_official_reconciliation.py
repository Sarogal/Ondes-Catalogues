#!/usr/bin/env python3
"""Independently recheck and reconcile strictly verified PUBLIC OA event changes.

Separate from the append-only discovery Publisher. A first-party OA UID and
agenda slug must be freshly verified. No cached private approvals, lists of
venues or second websites. Network errors, ambiguous updates, and weak GPS
never remove a published outing. All operations are auditable, ID-scoped.
"""
from collections import Counter
from copy import deepcopy
from datetime import date, datetime, timedelta
import hashlib
import json
import math
from pathlib import Path
import argparse
import os
import tempfile
from zoneinfo import ZoneInfo

from proof import norm, meters
from merge_policy import valid
from ptitesondes_openagenda_reuse_rights import review_event_rights
from ptitesondes_oa_first_party_admission import admit_live_openagenda
from ptitesondes_openagenda_v2_direct_evidence import _french_location, _valid_public_read_key
from ptitesondes_published_oa_drift_watch import (
    index_published, choose_groups, _timings, MAX_SCAN,
)
from ptitesondes_openagenda_backlog_private_dossiers import read_agenda_by_slug
from ptitesondes_openagenda_v2_direct_evidence import read_direct_v2

SCHEMA = "ptitesondes.official_reconciliation.v1"
AUTO_WITHDRAWAL = {
    3: "moved_online_official",
    4: "postponed_official",
    6: "cancelled_official",
}
REASON_CODES = frozenset({
    "official_unavailable", "official_identity_mismatch",
    "official_not_public", "official_removed_ambiguous",
    "official_sold_out_no_change", "official_timings_invalid",
    "official_future_date_missing", "official_no_future_replacement",
    "official_venue_or_title_changed", "official_venue_gps_unconfirmed",
    "official_rights_unconfirmed", "updated_public_schema_invalid",
    "official_unchanged", "official_rescheduled_old_date_removed",
    "official_time_corrected", "official_new_session_admitted",
    "official_new_session_held", "official_new_session_agenda_unavailable",
    *AUTO_WITHDRAWAL.values(),
})


def digest(value):
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _status(source):
    if not isinstance(source, dict):
        return None
    value = source.get("status")
    if isinstance(value, dict):
        value = value.get("id")
    return value if type(value) is int else None


def _unchanged_location(source, old):
    location = source.get("location")
    if not isinstance(location, dict) or not _french_location(location):
        return False
    if (norm(location.get("adminLevel4")) != norm(old.get("city"))
            or norm(location.get("name")) != norm(old.get("venue"))
            or not norm(location.get("name"))):
        return False
    try:
        coords = (float(location["latitude"]), float(location["longitude"]))
        old_coords = (float(old["lat"]), float(old["lng"]))
    except (TypeError, ValueError, KeyError):
        return False
    if (not all(math.isfinite(v) for v in (*coords, *old_coords))
            or not all(-90 <= p[0] <= 90 and -180 <= p[1] <= 180
                       for p in (coords, old_coords))):
        return False
    return meters(coords, old_coords) <= 65


def _identity(source, uid, slug):
    return (type(source) is dict
            and type(source.get("uid")) is int and source["uid"] == uid
            and type(source.get("slug")) is str and source["slug"] == slug)


def reconcile(catalogue, today, slot, *, read_event, limit=MAX_SCAN):
    """Return (new_catalogue, audit, counters); never mutates input.

    Eligible withdrawals: a first-party status explicitly cancelled, moved
    online or postponed; or a rescheduled (status=2) date absent from the
    verified new future timetable. Never remove because of network failure,
    unpublication alone, an invalid clock, or a mere absence of HTML.
    Eligible updates: same-day official time corrections with same title,
    physical venue, city, reliably matching coordinates and reuse licence.
    """
    if (type(catalogue) is not dict or catalogue.get("version") != 3
            or type(catalogue.get("events")) is not list
            or not 1 <= len(catalogue["events"]) <= 100000
            or type(catalogue.get("updated_at")) is not str
            or type(today) is not date or not callable(read_event)):
        raise ValueError("invalid_public_reconciliation_input")
    ids = [e.get("id") for e in catalogue["events"] if type(e) is dict]
    if (len(ids) != len(catalogue["events"])
            or any(type(value) is not str or not value for value in ids)
            or len(set(ids)) != len(ids)):
        raise ValueError("invalid_or_duplicate_public_ids")
    groups = index_published(catalogue, today)
    chosen = choose_groups(groups, today, slot, limit)
    count = Counter()
    planned = {}
    new_rows = []
    evidence = []
    cats = {e.get("category") for e in catalogue["events"]}
    for agenda_slug, uid in chosen:
        group = groups[(agenda_slug, uid)]
        rows = group["published"]
        def hold(reason):
            if reason not in REASON_CODES:
                raise ValueError("invalid_reconciliation_diagnostic")
            count[reason] += 1

        try:
            source = read_event(uid, agenda_slug)
            agenda = None
            if (type(source) is dict and "uid" not in source
                    and type(source.get("event")) is dict):
                agenda = source.get("agenda")
                source = source["event"]
        except (OSError, ValueError, TypeError, TimeoutError, KeyError,
                UnicodeError):
            hold("official_unavailable")
            continue

        if not _identity(source, uid, group["slug"]):
            hold("official_identity_mismatch")
            continue
        if source.get("state") != 2:
            hold("official_not_public")
            continue
        if source.get("removed") is True:
            hold("official_removed_ambiguous")
            continue

        status = _status(source)
        if status in AUTO_WITHDRAWAL:
            reason = AUTO_WITHDRAWAL[status]
            # Only exact existing, still-future ID rows of this verified
            # agenda/UID may be withdrawn. All other records are untouched.
            for old in rows:
                planned[old["id"]] = None
                evidence.append({
                    "id": old["id"], "action": "withdraw", "reason": reason,
                    "source_url": old["source_url"],
                    "expected_event_sha256": digest(old)})
            hold(reason)
            continue
        if status == 5:
            hold("official_sold_out_no_change")
            continue
        if status not in (1, 2):
            hold("official_identity_mismatch")
            continue

        sessions = _timings(source)
        if sessions is None:
            hold("official_timings_invalid")
            continue
        old_days = {e["date_start"] for e in rows}
        missing = [row for row in rows if row["date_start"] not in sessions]
        if missing and status != 2:
            hold("official_future_date_missing")
            continue
        if missing and not any(day >= today.isoformat()
                               for day in sessions):
            hold("official_no_future_replacement")
            continue

        # Check the entire series before changing a single row. Never apply
        # half of a program whose official title/venue or rights are unclear.
        present = [e for e in rows if e["date_start"] in sessions]
        if present:
            raw_title = source.get("title")
            official_title = (raw_title.get("fr") if isinstance(raw_title, dict)
                              else raw_title if isinstance(raw_title, str)
                              else None)
            if (not norm(official_title)
                    or any(norm(e.get("title")) != norm(official_title)
                           for e in present)):
                hold("official_venue_or_title_changed")
                continue
            if not all(_unchanged_location(source, e) for e in present):
                hold("official_venue_gps_unconfirmed")
                continue
            rights = review_event_rights(source, today)
            if not rights.get("licensed_factual_reuse_confirmed"):
                hold("official_rights_unconfirmed")
                continue

        proposal = {}
        invalid = False
        for old in present:
            current_time = " ; ".join(sorted(sessions[old["date_start"]]))
            if current_time == old.get("time"):
                continue
            new = dict(old, time=current_time,
                       verified_at=today.isoformat(),
                       geo_verified_at=today.isoformat())
            if not valid(new, cats, set(old), today)[0]:
                invalid = True
                break
            proposal[old["id"]] = new
        if invalid:
            hold("updated_public_schema_invalid")
            continue

        for old in missing:
            planned[old["id"]] = None
            evidence.append({
                "id": old["id"], "action": "withdraw",
                "reason": "official_rescheduled_old_date_removed",
                "source_url": old["source_url"],
                "expected_event_sha256": digest(old)})
        for old in present:
            if old["id"] not in proposal:
                continue
            new = proposal[old["id"]]
            planned[old["id"]] = new
            evidence.append({
                "id": old["id"], "action": "correct_time",
                "reason": "official_time_corrected",
                "source_url": old["source_url"],
                "expected_event_sha256": digest(old),
                "new_time": new["time"]})
        # New sessions from a series already present on the map follow the
        # SAME first-party admission gate as newly discovered programs.
        # Source, agenda UID, rights, category, age, venue, GPS, timing and
        # duplicate evidence are all rechecked; this is never an implicit
        # approval of every date from an old program.
        existing = {x["date_start"] for x in rows}
        fresh_days = sorted(day for day in sessions
                            if today.isoformat() <= day <=
                               (today + timedelta(days=184)).isoformat()
                            and day not in existing)
        accepted = 0
        if fresh_days:
            if (not isinstance(agenda, dict)
                    or agenda.get("slug") != agenda_slug
                    or type(agenda.get("uid")) is not int
                    or not 0 < agenda["uid"] < 10**12):
                hold("official_new_session_agenda_unavailable")
            else:
                location = source.get("location")
                raw_title = source.get("title")
                title = (raw_title.get("fr") if isinstance(raw_title, dict)
                         else raw_title if isinstance(raw_title, str)
                         else None)
                if (not isinstance(location, dict)
                        or not isinstance(title, str)
                        or not isinstance(source.get("timings"), list)):
                    hold("official_new_session_held")
                else:
                    lead = {
                        "agenda_uid": agenda["uid"],
                        "agenda_slug": agenda_slug, "event_uid": uid,
                        "title": title,
                        "city_unverified": location.get("adminLevel4"),
                        "venue_unverified": location.get("name"),
                        "explicit_source_session_intervals": [
                            {"begin": t["begin"], "end": t["end"]}
                            for t in source["timings"]],
                        "publication_ready": False, "public_writes": 0,
                    }
                    for day in fresh_days:
                        view = dict(catalogue, events=[
                            *catalogue["events"], *new_rows])
                        candidate, reason = admit_live_openagenda(
                            lead, day, agenda, source, catalogue, view, today)
                        if candidate is None:
                            hold("official_new_session_held")
                            continue
                        if candidate["id"] in planned or any(
                                x["id"] == candidate["id"] for x in new_rows):
                            hold("official_new_session_held")
                            continue
                        new_rows.append(candidate)
                        accepted += 1
                        evidence.append({
                            "id": candidate["id"], "action": "add",
                            "reason": "official_new_session_admitted",
                            "source_url": candidate["source_url"],
                            "new_event_sha256": digest(candidate),
                        })
                    if accepted:
                        hold("official_new_session_admitted")
        if missing:
            hold("official_rescheduled_old_date_removed")
        if proposal:
            hold("official_time_corrected")
        if not missing and not proposal and not accepted:
            hold("official_unchanged")

    if len(planned) + len(new_rows) != len(evidence):
        raise ValueError("reconciliation_plan_not_unique")
    result = deepcopy(catalogue)
    if planned or new_rows:
        result["events"] = [
            (planned[e["id"]] if e["id"] in planned else e)
            for e in result["events"]
            if e["id"] not in planned or planned[e["id"]] is not None
        ]
        result["events"].extend(new_rows)
        result["updated_at"] = datetime.now(
            ZoneInfo("Europe/Paris")).isoformat(timespec="seconds")
        expected = [e for e in catalogue["events"] if e["id"] not in planned]
        inserted_ids = {row["id"] for row in new_rows}
        if len(inserted_ids) != len(new_rows) or inserted_ids.intersection(ids):
            raise ValueError("new_session_identity_not_unique")
        actual = [e for e in result["events"] if (
            e["id"] not in planned and e["id"] not in inserted_ids)]
        if expected != actual:
            raise ValueError("unrelated_public_event_mutated")
        if (len(catalogue["events"]) + len(new_rows) - len(result["events"])
                != sum(value is None for value in planned.values())):
            raise ValueError("incorrect_reconciliation_count")
    audit = {
        "schema": SCHEMA, "checked_on": today.isoformat(),
        "slot": slot, "source_series_checked": len(chosen),
        "total_source_series": len(groups),
        "before_count": len(catalogue["events"]),
        "after_count": len(result["events"]),
        "source_summary": dict(sorted(count.items())),
        "catalogue_before_sha256": digest(catalogue),
        "catalogue_after_sha256": digest(result),
        "operations": evidence,
        "unrelated_public_records_preserved": True,
    }
    return result, audit, count


def atomic_json(path, document):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix="reviewed-oa-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as h:
            json.dump(document, h, ensure_ascii=False, indent=2)
            h.write("\n")
            h.flush()
            os.fsync(h.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalogue", type=Path, required=True)
    parser.add_argument("--date", type=date.fromisoformat, required=True)
    parser.add_argument("--slot", type=int, required=True)
    parser.add_argument("--audit-out", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    api_key = os.environ.get("OPENAGENDA_READ_KEY", "")
    if not _valid_public_read_key(api_key):
        raise ValueError("missing_or_invalid_read_only_oa_key")
    raw = args.catalogue.read_bytes()
    if len(raw) > 9_000_000:
        raise ValueError("catalogue_oversized")
    base = json.loads(raw)
    agendas = {}
    def live(uid, slug):
        if slug not in agendas:
            agendas[slug] = read_agenda_by_slug(slug, api_key)
        row = agendas[slug]
        if row.get("slug") != slug or type(row.get("uid")) is not int:
            raise ValueError("official_agenda_identity_changed")
        return {"agenda": row, "event": read_direct_v2(row["uid"], uid, api_key)}
    result, audit, _ = reconcile(
        base, args.date, args.slot, read_event=live)
    changed = bool(audit["operations"])
    if changed and args.apply:
        # Both files are committed to the same Git commit by the workflow.
        atomic_json(args.audit_out, audit)
        atomic_json(args.catalogue, result)
    print("source_series_checked=" + str(audit["source_series_checked"]))
    print("withdrawn=" + str(sum(
        p["action"] == "withdraw" for p in audit["operations"])))
    print("corrected=" + str(sum(
        p["action"] == "correct_time" for p in audit["operations"])))
    print("added=" + str(sum(
        p["action"] == "add" for p in audit["operations"])))
    print("changed=" + str(bool(changed and args.apply)).lower())
    print("reason_counts=" + json.dumps(audit["source_summary"], sort_keys=True))


if __name__ == "__main__":
    main()
