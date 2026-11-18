"""Anonymous private backlog versus approved venue registry: preflight ONLY.

One event UID can have many date leads. Registry name/city matching is not
an attestation of the GPS point in an OpenAgenda record, an event's audience,
an organizer, rights, or an exact event session. No API call or publisher.

Intended to be run by a separately trusted operator on private backlog JSON,
not in pull request CI with secrets.
"""
from collections import Counter, defaultdict
from datetime import date, timedelta
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from proof import norm
from ptitesondes_candidate_promotion import registry_location

SCHEMA = "ptitesondes.oa2.private_geo_backlog_coverage.v1"
MAX_ROWS = 4000
UID = re.compile(r"[0-9]{1,12}\Z")
KNOWN_COLLECTORS = frozenset(("openagenda-v2", "opendatasoft-index"))


def _valid_date(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = date.fromisoformat(value)
        return parsed if parsed.isoformat() == value else None
    except ValueError:
        return None


def _event_identity(row):
    if not isinstance(row, dict):
        return None
    raw = row.get("external_id")
    if not isinstance(raw, str) or not UID.fullmatch(raw):
        return None
    return raw


def _venue_key(row):
    city, name = row.get("city"), row.get("venue")
    if (not isinstance(city, str) or not isinstance(name, str)
            or not norm(city) or not norm(name)):
        return None
    return norm(city), norm(name)


def audit_backlog_geo_coverage(
        leads, today, *, location_lookup=registry_location):
    """Read-only exact-name census. False matches never become approvals."""
    if (not isinstance(leads, list) or len(leads) > MAX_ROWS
            or type(today) is not date or not callable(location_lookup)):
        raise ValueError("invalid_private_backlog_census")
    cutoff = today + timedelta(days=184)
    counts = Counter()
    by_source = Counter()
    venues = set()
    unmatched_venues = set()
    uids = defaultdict(set)
    uid_days = defaultdict(set)
    uid_matched = defaultdict(set)
    uid_invalid = set()
    for row in leads:
        counts["raw_leads"] += 1
        if not isinstance(row, dict):
            counts["malformed_rows"] += 1
            continue
        day = _valid_date(row.get("date_start"))
        if day is None:
            counts["missing_or_invalid_day"] += 1
            continue
        if day < today:
            counts["expired_leads"] += 1
            continue
        counts["future_leads_any_horizon"] += 1
        if day > cutoff:
            counts["outside_184_day_active_window"] += 1
            continue
        counts["future_leads_in_active_window"] += 1
        source = row.get("collector")
        source = (source if isinstance(source, str) and source in KNOWN_COLLECTORS
                  else "unrecognized_or_legacy")
        by_source[source] += 1
        key = _venue_key(row)
        if key is None:
            counts["missing_city_or_venue"] += 1
        else:
            venues.add(key)
        uid = _event_identity(row)
        if uid is None:
            counts["missing_or_invalid_uid"] += 1
        else:
            uid_days[uid].add(day.isoformat())
            uids[uid].add(key)
        if source not in KNOWN_COLLECTORS:
            counts["collector_not_admissible"] += 1
        if key is None:
            counts["venue_identity_unavailable"] += 1
            if uid is not None:
                uid_invalid.add(uid)
            continue
        try:
            known = location_lookup(row)
        except (ValueError, TypeError, KeyError, OverflowError, OSError):
            known = None
        if not isinstance(known, dict):
            unmatched_venues.add(key)
            counts["leads_without_exact_existing_registry_identity"] += 1
        else:
            counts["leads_with_exact_existing_registry_identity"] += 1
            # A matching local registry point is NOT GPS corroboration of
            # the coordinates actually supplied in the OpenAgenda API.
            if uid is not None:
                uid_matched[uid].add(key)
    multi = {uid for uid, days in uid_days.items() if len(days) > 1}
    all_uids = set(uid_days)
    full_uid_matches = {
        uid for uid in all_uids
        if uid not in uid_invalid and uids[uid]
        and None not in uids[uid] and uid_matched[uid] == uids[uid]
    }
    counts["active_future_unique_uids"] = len(all_uids)
    counts["active_future_unique_uid_days"] = sum(
        len(days) for days in uid_days.values())
    counts["active_future_multi_day_uid_groups"] = len(multi)
    counts["active_future_multi_day_uid_days"] = sum(
        len(uid_days[uid]) for uid in multi)
    counts["active_future_venue_city_pairs"] = len(venues)
    counts["unmatched_future_venue_city_pairs"] = len(unmatched_venues)
    counts["uids_all_venues_exactly_in_existing_registry"] = len(full_uid_matches)
    counts["uids_with_any_venue_missing_or_ambiguous"] = (
        len(all_uids) - len(full_uid_matches))
    return {
        "schema": SCHEMA, "mode": "read_only_counts_not_location_or_event_approval",
        "counts": dict(sorted(counts.items())),
        "collector_counts": {
            key: by_source.get(key, 0)
            for key in ("openagenda-v2", "opendatasoft-index",
                        "unrecognized_or_legacy")
        },
        "venue_identity_match_proves_actual_openagenda_gps": False,
        "independent_organizer_or_event_session_attested": False,
        "publisher_connected": False, "approval_granted": False,
        "public_writes": 0, "contains_candidate_identifiers": False,
    }


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--private-backlog", required=True)
    parser.add_argument("--today", required=True)
    args = parser.parse_args()
    day = _valid_date(args.today)
    if day is None:
        raise SystemExit("invalid_today")
    path = Path(args.private_backlog)
    if not path.is_file() or path.stat().st_size > 2_000_000:
        raise SystemExit("invalid_private_backlog_file")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        report = audit_backlog_geo_coverage(data, day)
    except (OSError, ValueError, TypeError, UnicodeDecodeError):
        raise SystemExit("private_backlog_audit_not_available") from None
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
