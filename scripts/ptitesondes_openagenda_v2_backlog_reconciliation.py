"""Conservative, read-only OpenAgenda v2 backlog funnel census.

This is a diagnostic integrated into the existing private preview report,
NOT the ODS fallback publisher. It emits fixed-schema counts only, never
UIDs, URLs, cities, titles, full errors, patches, or private candidate data.
It reuses the EXISTING venue preflight and historical published-range check.
"""
from collections import Counter, defaultdict
from datetime import date, timedelta
import re

from ptitesondes_candidate_promotion import (
    admission_failure_group, covered_by_published_range,
    openagenda_path_parts, permitted,
)
from merge_policy import byid
from proof import norm

SCHEMA = "ptitesondes.oa2.backlog_readonly_funnel.v1"
UID = re.compile(r"[0-9]{1,12}\Z")
ALLOWED_REASONS = frozenset({
    "eligible", "collector", "uid", "source_url", "session_date",
    "missing_identity", "missing_venue", "venue_gps_unverified",
    "invalid_metadata",
})
MAX_ROWS = 4000
MAX_CATALOGUE = 12000


def _safe_day(row):
    raw = row.get("date_start") if isinstance(row, dict) else None
    if not isinstance(raw, str):
        return None
    try:
        day = date.fromisoformat(raw)
        return day if day.isoformat() == raw else None
    except ValueError:
        return None


def _source_identity(row):
    """Only immutable UID + strict OA URL path, not a fuzzy title match."""
    uid = row.get("external_id") if isinstance(row, dict) else None
    if not isinstance(uid, str) or UID.fullmatch(uid) is None:
        return None
    pair = openagenda_path_parts(row.get("source_url"))
    if pair is None:
        return None
    # Legacy mirrored URLs can use the bare slug, not a UID prefix. This is
    # a diagnostic, not direct proof that the page represents this UID.
    return uid, pair[0]


def reconcile_backlog(leads, published, today, *, eligible_fn=permitted,
                      reason_fn=admission_failure_group):
    """Reconcile private backlog by UID before asking for any more API reads.

    Neither the sample nor the result contains an admission/approval decision.
    The eligible function only checks pre-existing venue/date/intake gates;
    OpenAgenda API, organizer, rights, exact audience and sessions are pending.
    """
    if (type(today) is not date or not isinstance(leads, list)
            or len(leads) > MAX_ROWS or not isinstance(published, dict)
            or not isinstance(published.get("events"), list)
            or len(published["events"]) > MAX_CATALOGUE
            or not callable(eligible_fn) or not callable(reason_fn)):
        raise ValueError("invalid_reconciliation_inputs")
    existing = byid(published)
    events = published["events"]
    counts = Counter()
    reasons = Counter()
    future_by_uid_day = defaultdict(list)
    all_days_by_uid = defaultdict(set)
    future_uids = set()
    known_slugs_by_uid = defaultdict(set)
    # A source conflict among mirrors must not select an arbitrary winner.
    for lead in leads:
        counts["raw_leads"] += 1
        day = _safe_day(lead)
        identity = _source_identity(lead)
        if day is not None and identity is not None:
            all_days_by_uid[identity[0]].add(day.isoformat())
        if day is None or day < today:
            continue
        counts["future_leads"] += 1
        if identity is not None:
            uid, slug = identity
            future_uids.add(uid)
            known_slugs_by_uid[uid].add(slug)
            future_by_uid_day[(uid, day.isoformat())].append(lead)
        try:
            reason = reason_fn(lead, today)
        except (ValueError, KeyError, TypeError):
            reason = "invalid_metadata"
        reasons[reason if reason in ALLOWED_REASONS else "invalid_metadata"] += 1

    counts["future_valid_url_uid_day_groups"] = len(future_by_uid_day)
    counts["future_distinct_uids"] = len(future_uids)
    counts["future_cross_agenda_uid_groups"] = sum(
        len(slugs) > 1 for slugs in known_slugs_by_uid.values())
    multi = {uid for uid in future_uids if len(all_days_by_uid[uid]) > 1}
    counts["future_multi_day_uid_groups"] = len(multi)
    counts["future_multi_day_leads"] = sum(
        len(rows) for (uid, _), rows in future_by_uid_day.items() if uid in multi)
    counts["future_uid_day_duplicate_leads"] = sum(
        max(0, len(rows) - 1) for rows in future_by_uid_day.values())

    # A true source conflict must be resolved with original proof. Two aliases
    # of one immutable UID do NOT by themselves imply independent organizer
    # corroboration or two distinct events.
    for (uid, day), group in future_by_uid_day.items():
        eligible_rows = []
        for lead in group:
            try:
                if eligible_fn(lead, today):
                    eligible_rows.append(lead)
            except (ValueError, KeyError, TypeError):
                pass
        if not eligible_rows:
            counts["uid_day_no_reviewed_venue_or_intake"] += 1
            continue
        identities = {
            (norm(x.get("title")), norm(x.get("city")),
             norm(x.get("venue")), x.get("date_end"))
            for x in eligible_rows
        }
        by_collector = defaultdict(set)
        for x in eligible_rows:
            by_collector[x.get("collector")].add(x.get("source_url"))
        if len(identities) != 1 or any(len(urls) != 1 for urls in by_collector.values()):
            counts["uid_day_mirror_identity_conflicts"] += 1
            continue
        counts["uid_day_existing_intake_gates_pass"] += 1
        if uid in multi:
            counts["uid_day_held_multi_day_grouping"] += 1
            continue
        representative = eligible_rows[0]
        identity_id = "openagenda-" + uid + "-" + day
        if (identity_id in existing
                or covered_by_published_range(representative, events)):
            counts["uid_day_already_published"] += 1
            continue
        # This means ONLY worth checking with ODS / the API and remaining
        # independent organizer, rights, category, access and history gates.
        counts["single_day_uid_day_for_source_review"] += 1

    return {
        "schema": SCHEMA,
        "mode": "offline_private_preview_count_only_not_admission",
        "counts": dict(sorted(counts.items())),
        "existing_intake_block_reasons": dict(sorted(reasons.items())),
        "checked_against_public_catalogue_count": len(events),
        "requires_authenticated_api_reads": True,
        "organizer_independently_attested": False,
        "rights_reviewed": False,
        "category_expansion_approved": False,
        "publisher_connected": False,
        "approval_granted": False,
        "public_writes": 0,
    }
