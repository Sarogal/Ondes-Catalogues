"""READ-ONLY OA v2 source fallback audit when ODS mirror omits an exact UID.

This is a private, bounded evidence *diagnostic*, NOT a substitute for the
public musical/non-musical publication gates. An ODS timeout or HTTP error is
never mistaken for an absent UID. The trusted configured agenda UID + live OA
agenda slug may route an API read, but self-asserted metadata CANNOT attest
institution ownership, venue GPS, age, family audience, source rights, or
permission to publish.
"""
from collections import Counter
from datetime import date, datetime, timedelta
import hashlib
import json
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from ptitesondes_openagenda_v2_direct_evidence import (
    _source_parts, read_direct_v2, read_direct_agenda_v2,
)
from ptitesondes_generic_schemaorg_event_discovery import SOURCE_TIMEZONES
from ptitesondes_qualification_rootcause import probe_uid_in_index
from proof import norm

SCHEMA = "ptitesondes.oa_direct_mirror_absence_private_audit.v1"
MAX_LEADS = 4000
MAX_AGENDAS = 60
MAX_WORK = 25
MAX_RECORDS = 500
UID = re.compile(r"[0-9]{1,12}\Z")
STATES = frozenset((
    "mirror_absent_direct_day_and_title_confirmed",
    "mirror_absent_direct_mismatch",
    "mirror_absent_direct_unavailable",
))
COUNTS = (
    "input_leads", "eligible_unique_leads", "selected_leads",
    "conflicting_uid_day_sources_held",
    "unregistered_agendas_held", "unregistered_agendas_resolved_for_research",
    "unregistered_agenda_lookups_failed", "non_uid_pinned_links_held",
    "mirror_uid_present_or_nonzero_held",
    "mirror_uid_nonunique_held", "mirror_probe_unavailable_held",
    "mirror_uid_absent", "direct_api_matched_day_and_title",
    "direct_api_mismatch_held", "direct_api_unavailable_held",
    "private_rows_updated", "private_rows_total",
)


def _day(value):
    if type(value) is not str:
        return False
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _safe_row(row):
    if (type(row) is not dict or set(row) != {
            "schema", "audit_id", "event_uid", "agenda_uid", "date_start",
            "state", "first_checked_on", "last_checked_on",
            "organizer_independently_verified", "rights_reviewed",
            "venue_geo_verified", "family_audience_verified",
            "publisher_connected", "publication_ready", "approved",
            "public_writes"}
            or row.get("schema") != SCHEMA
            or row.get("state") not in STATES
            or type(row.get("event_uid")) is not str
            or UID.fullmatch(row["event_uid"]) is None
            or type(row.get("agenda_uid")) is not int
            or not 0 < row["agenda_uid"] < 10**13
            or not all(_day(row.get(x)) for x in (
                "date_start", "first_checked_on", "last_checked_on"))
            or row["first_checked_on"] > row["last_checked_on"]
            or any(row.get(x) is not False for x in (
                "organizer_independently_verified", "rights_reviewed",
                "venue_geo_verified", "family_audience_verified",
                "publisher_connected", "publication_ready", "approved"))
            or type(row.get("public_writes")) is not int
            or row["public_writes"] != 0
            or row.get("audit_id") != _id(
                row["agenda_uid"], row["event_uid"], row["date_start"])):
        raise ValueError("invalid_private_ods_direct_audit_record")


def _id(agenda_uid, event_uid, day):
    data = json.dumps([agenda_uid, event_uid, day], separators=(",", ":"))
    return "oa-direct-audit-" + hashlib.sha256(data.encode()).hexdigest()[:32]


def _source(lead):
    if (type(lead) is not dict
            or lead.get("collector") != "openagenda-v2"
            or type(lead.get("external_id")) is not str
            or UID.fullmatch(lead["external_id"]) is None
            or not _day(lead.get("date_start"))
            or lead.get("date_end") != lead["date_start"]
            or not isinstance(lead.get("title"), str)
            or not lead["title"].strip()
            or len(lead["title"]) > 180
            or any(type(lead.get(k)) is not str
                   or not 1 <= len(lead[k].strip()) <= size
                   or any(c in lead[k] for c in "<>\r\n")
                   for k, size in (("city", 120), ("venue", 180)))):
        return None
    identity = _source_parts(lead.get("source_url"))
    if identity is None or identity[1] != lead["external_id"]:
        return None
    return identity[0], identity[1], lead["date_start"]


def _exact_event_claim(event, event_uid, title, day, city, venue):
    """Check one exact OA API source claim, NOT independent publication proof."""
    if (type(event) is not dict
            or str(event.get("uid")) != event_uid
            or type(event.get("state")) is not int or event["state"] != 2
            or type(event.get("status")) is not int or event["status"] != 1
            or event.get("removed") is True
            or event.get("attendanceMode") not in (1, 3)
            or type(event.get("timezone")) is not str
            or event["timezone"] not in SOURCE_TIMEZONES):
        return False
    name = event.get("title")
    if type(name) is dict:
        name = name.get("fr")
    location = event.get("location")
    if (not isinstance(name, str) or norm(name) != norm(title)
            or type(location) is not dict
            or norm(location.get("adminLevel4")) != norm(city)
            or norm(location.get("name")) != norm(venue)):
        return False
    occurrences = event.get("timings")
    if type(occurrences) is not list or len(occurrences) > 800:
        return False
    zone = ZoneInfo(event["timezone"])
    for slot in occurrences:
        if type(slot) is not dict or type(slot.get("begin")) is not str:
            continue
        try:
            timestamp = datetime.fromisoformat(slot["begin"].replace("Z", "+00:00"))
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                continue
            # API's timezone is only a source claim; real local timing and
            # independent organizer/venue proof must be repeated at admission.
            if timestamp.astimezone(zone).date().isoformat() == day:
                return True
        except (ValueError, OverflowError):
            continue
    return False


def _checked_agendas(configured_uids, public_key, reader, *, allow_empty=False):
    if (type(configured_uids) is not list
            or not (0 if allow_empty else 1) <= len(configured_uids) <= MAX_AGENDAS
            or len(configured_uids) != len(set(configured_uids))
            or any(type(uid) is not int or not 0 < uid < 10**13
                   for uid in configured_uids)):
        raise ValueError("invalid_curated_agenda_uids")
    mapping, bad = {}, 0
    for agenda_uid in configured_uids:
        try:
            record = reader(agenda_uid, public_key)
            if (type(record) is not dict
                    or str(record.get("uid")) != str(agenda_uid)
                    or type(record.get("slug")) is not str
                    or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,100}",
                                        record["slug"])):
                raise ValueError("direct_agenda_identity_invalid")
            slug = record["slug"]
            if slug in mapping:
                raise ValueError("direct_agenda_slug_collision")
            mapping[slug] = agenda_uid
        except (OSError, ValueError, TypeError, KeyError, TimeoutError):
            bad += 1
    return mapping, bad


def audit_missing_ods_direct(
        private_leads, existing, configured_agenda_uids, public_read_key, today,
        *, offset=0, max_work=12,
        ods_probe=probe_uid_in_index,
        agenda_reader=read_direct_agenda_v2,
        event_reader=read_direct_v2,
        agenda_discovery=None):
    if (type(private_leads) is not list or len(private_leads) > MAX_LEADS
            or type(existing) is not list or len(existing) > MAX_RECORDS
            or type(today) is not date or type(offset) is not int or offset < 0
            or type(max_work) is not int or not 1 <= max_work <= MAX_WORK
            or not isinstance(public_read_key, str) or not public_read_key
            or (agenda_discovery is not None and not callable(agenda_discovery))):
        raise ValueError("invalid_ods_audit_arguments")
    stored = {}
    for row in existing:
        _safe_row(row)
        if row["audit_id"] in stored:
            raise ValueError("duplicate_private_ods_audit")
        stored[row["audit_id"]] = dict(row)
    mapping, failed_agendas = _checked_agendas(
        configured_agenda_uids, public_read_key, agenda_reader,
        allow_empty=agenda_discovery is not None)
    # No private UID, URL, title, municipality, address or participant detail
    # in public report. Even a failure exception is reduced to a fixed count.
    counts = dict.fromkeys(COUNTS, 0)
    counts["input_leads"] = len(private_leads)
    grouped = {}
    conflicts = set()
    malformed = 0
    for lead in private_leads:
        key = _source(lead)
        if key is None:
            malformed += 1
            continue
        if not today <= date.fromisoformat(key[2]) <= today + timedelta(days=184):
            continue
        # Exact source UID + local day, but never silently prefer one
        # conflicting syndication, title, venue or city in the private lead.
        identity = (key[0], norm(lead["title"]),
                    norm(lead.get("city")), norm(lead.get("venue")))
        candidate_key = (key[1], key[2])
        prior = grouped.get(candidate_key)
        if prior is not None and prior[2] != identity:
            conflicts.add(candidate_key)
        else:
            grouped.setdefault(candidate_key, (key, lead, identity))
    for candidate_key in conflicts:
        grouped.pop(candidate_key, None)
    counts["conflicting_uid_day_sources_held"] = len(conflicts)
    counts["eligible_unique_leads"] = len(grouped)
    choices = sorted(grouped.items())
    if choices:
        shift = offset % len(choices)
        choices = choices[shift:] + choices[:shift]
    selected = choices[:max_work]
    counts["selected_leads"] = len(selected)
    checked_uid = {}
    checked_event = {}
    # Discovery is optional and PREVIEW-ONLY: no configured agenda list is
    # necessary to *research* a new slug. The OA API owns only the UID/slug
    # association; independent organizer ownership remains unverified.
    new_slugs = {}
    for (_, _), (key, lead, _) in selected:
        slug, event_uid, day = key
        agenda_uid = mapping.get(slug)
        if agenda_uid is None:
            if slug not in new_slugs:
                discovered_uid = None
                if agenda_discovery is not None:
                    try:
                        candidate = agenda_discovery(slug, public_read_key)
                        from ptitesondes_openagenda_slug_discovery import SCHEMA as LOOKUP_SCHEMA
                        if (type(candidate) is dict
                                and candidate.get("schema") == LOOKUP_SCHEMA
                                and candidate.get("slug") == slug
                                and type(candidate.get("uid")) is int
                                and 0 < candidate["uid"] < 10**13
                                and candidate.get("status") ==
                                "public_uid_slug_only_independent_ownership_pending"
                                and all(candidate.get(k) is False for k in (
                                    "independent_ownership_verified", "organizer_verified",
                                    "rights_reviewed", "publication_ready",
                                    "approval_granted", "publisher_connected"))
                                and type(candidate.get("public_writes")) is int
                                and candidate["public_writes"] == 0):
                            # Do not trust the lookup list alone. Re-read the
                            # selected exact UID with the existing bounded API
                            # reader before any event research.
                            confirmation = agenda_reader(candidate["uid"], public_read_key)
                            if (type(confirmation) is dict
                                    and str(confirmation.get("uid")) == str(candidate["uid"])
                                    and confirmation.get("slug") == slug):
                                discovered_uid = candidate["uid"]
                    except (OSError, ValueError, TypeError, KeyError, TimeoutError):
                        pass
                new_slugs[slug] = discovered_uid
                if discovered_uid is None:
                    counts["unregistered_agenda_lookups_failed"] += 1
            agenda_uid = new_slugs[slug]
            if agenda_uid is None:
                counts["unregistered_agendas_held"] += 1
                continue
            counts["unregistered_agendas_resolved_for_research"] += 1
        try:
            state = checked_uid.setdefault(event_uid, None)
            if state is None:
                state = ods_probe(event_uid)
                checked_uid[event_uid] = state
        except (ValueError, OSError, TypeError, KeyError, TimeoutError):
            state = "unexpected_error"
        if state != "uid_absent":
            if state in ("uid_unique", "unexpected_uid"):
                counts["mirror_uid_present_or_nonzero_held"] += 1
            elif state == "uid_nonunique":
                counts["mirror_uid_nonunique_held"] += 1
            else:
                counts["mirror_probe_unavailable_held"] += 1
            continue
        counts["mirror_uid_absent"] += 1
        try:
            ek = (agenda_uid, event_uid)
            if ek not in checked_event:
                checked_event[ek] = event_reader(
                    agenda_uid, event_uid, public_read_key)
            valid = _exact_event_claim(
                checked_event[ek], event_uid, lead["title"], day,
                lead.get("city"), lead.get("venue"))
            newstate = ("mirror_absent_direct_day_and_title_confirmed"
                        if valid else "mirror_absent_direct_mismatch")
        except (ValueError, TypeError, OSError, KeyError, TimeoutError):
            newstate = "mirror_absent_direct_unavailable"
        if newstate == "mirror_absent_direct_day_and_title_confirmed":
            counts["direct_api_matched_day_and_title"] += 1
        elif newstate == "mirror_absent_direct_mismatch":
            counts["direct_api_mismatch_held"] += 1
        else:
            counts["direct_api_unavailable_held"] += 1
        aid = _id(agenda_uid, event_uid, day)
        previous = stored.get(aid)
        row = {
            "schema": SCHEMA, "audit_id": aid, "agenda_uid": agenda_uid,
            "event_uid": event_uid, "date_start": day, "state": newstate,
            "first_checked_on": (previous["first_checked_on"]
                                 if previous else today.isoformat()),
            "last_checked_on": today.isoformat(),
            "organizer_independently_verified": False,
            "rights_reviewed": False, "venue_geo_verified": False,
            "family_audience_verified": False, "publisher_connected": False,
            "publication_ready": False, "approved": False, "public_writes": 0,
        }
        _safe_row(row)
        if len(stored) >= MAX_RECORDS and aid not in stored:
            raise ValueError("private_ods_audit_store_capacity")
        stored[aid] = row
        counts["private_rows_updated"] += 1
    rows = sorted(stored.values(), key=lambda x: x["audit_id"])
    counts["private_rows_total"] = len(rows)
    return {
        "private_rows": rows,
        "report": {
            "schema": SCHEMA,
            **counts,
            "malformed_or_non_uid_pinned_leads_held": malformed,
            "curated_agenda_reads_unavailable": failed_agendas,
            "public_writes": 0, "publisher_connected": False,
            "publication_ready": False, "approved": False,
        },
    }
