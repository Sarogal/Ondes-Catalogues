"""In-memory publication REHEARSAL for a wholly unknown municipal event.

Uses no historical agenda/organizer/venue/domain/city allowlist. Every
candidate must be re-read from OA public API and a DILA-authenticated
municipal page fetched through the pinned-HTTPS reader; coordinates come
ONLY from a separately factory-minted BAN/OSM location proof.

This is a bounded, private rehearsal; no automatic publisher entry point,
patch file, public write, image or copied event description. No input-provided
status flag may confer authority.
"""
from datetime import date, datetime, timedelta
import re
from urllib.parse import urlsplit

from merge_policy import ORIGIN, byid, valid, historical_event_unchanged, merge
from official_organizer_proof import canonical_event_title
from proof import norm, meters
from ptitesondes_candidate_promotion import category_for
from ptitesondes_dila_municipal_domains import (
    approved_municipal_page_host, fetch_dila,
)
from ptitesondes_openagenda_national_event_research import _french_text
from ptitesondes_openagenda_reuse_rights import review_event_rights
from ptitesondes_openagenda_v2_direct_evidence import (
    review_direct_v2, read_direct_v2, read_direct_agenda_v2,
    _valid_public_read_key,
)
from ptitesondes_open_world_municipal_bootstrap import _safe_research_lead
from ptitesondes_shared_venue_location_evidence import location_from_proof
from ptitesondes_unlisted_source_safe_recheck import read_unknown_https
from ptitesondes_unlisted_visible_session_research import visible_unlisted_sessions

SCHEMA = "ptitesondes.open_world_release_rehearsal.v1"
MAX_SESSIONS = 800
PRIVATE_ONLY = {"publication_ready": False, "publisher_connected": False,
                "public_writes": 0}
NOT_PUBLIC_ACCESS = re.compile(
    r"\b(?:scolair(?:e|es|s)? uniquement|reserve aux scolaires|"
    r"sur invitation uniquement|evenement prive|"
    r"reserve aux membres|interdit aux enfants)\b"
)


def _blank(reason):
    return {"schema": SCHEMA, "status": reason, "candidate": None,
            "open_license_credit_present": False,
            "independent_venue_correlated": False,
            "municipal_program_exact_sessions": 0,
            "published_duplicate_checked": False,
            "private_rehearsal_positive": False,
            "publisher_policy_rehearsal_accepted": False,
            "preview_additions": 0, **PRIVATE_ONLY}


def _sessions_for_day(lead, day):
    rows = lead.get("explicit_source_session_intervals")
    if (not isinstance(rows, list) or not 1 <= len(rows) <= MAX_SESSIONS):
        return None
    selected = []
    for slot in rows:
        if type(slot) is not dict or set(slot) != {"begin", "end"}:
            return None
        try:
            start = datetime.fromisoformat(slot["begin"])
            end = datetime.fromisoformat(slot["end"])
        except (ValueError, TypeError, KeyError):
            return None
        if (start.tzinfo is None or end.tzinfo is None or
                start.utcoffset() is None or end.utcoffset() is None or
                not start < end or end - start > timedelta(days=1)):
            return None
        if start.date() == day:
            selected.append(slot)
    return selected if selected else None


def rehearse_open_world_municipal_event(
        lead, date_start, official_url, venue_proof, baseline, published,
        today, public_key, *, agenda_reader=read_direct_agenda_v2,
        event_reader=read_direct_v2, directory_reader=fetch_dila,
        municipal_reader=read_unknown_https):
    """Read everything live, validate, return a *non-publishable* mock card.

    Passing a trusted geo object to this function never overrides a
    conflicting registered place nor certifies an organizer website. The
    municipal event listing is first-party *only because DILA has certified
    that municipality's domain independently from the OA event*.
    """
    if (type(today) is not date or not _valid_public_read_key(public_key)
            or not _safe_research_lead(lead, today)
            or not isinstance(date_start, str)
            or not isinstance(official_url, str)
            or not all(callable(x) for x in (agenda_reader, event_reader,
                                           directory_reader, municipal_reader))):
        return _blank("invalid_or_untrusted_research_input")
    try:
        day = date.fromisoformat(date_start)
    except ValueError:
        return _blank("invalid_session_day")
    if not today <= day <= today + timedelta(days=184):
        return _blank("out_of_future_window")
    selected = _sessions_for_day(lead, day)
    if selected is None:
        return _blank("no_immutable_exact_session_on_day")
    # Never change a published or historical event in this path.
    try:
        originals, current = byid(baseline), byid(published)
        if any(key not in current or not historical_event_unchanged(value, current[key])
               for key, value in originals.items()):
            return _blank("historical_catalogue_changed")
    except (KeyError, ValueError, TypeError):
        return _blank("invalid_catalogue_snapshot")
    try:
        agenda = agenda_reader(lead["agenda_uid"], public_key)
        live = event_reader(lead["agenda_uid"], lead["event_uid"], public_key)
    except (OSError, TimeoutError, ValueError, TypeError, KeyError):
        return _blank("live_oa_unavailable")
    if (not isinstance(agenda, dict)
            or str(agenda.get("uid")) != str(lead["agenda_uid"])
            or agenda.get("slug") != lead["agenda_slug"]
            or not isinstance(live, dict)
            or type(live.get("uid")) is not int
            or live["uid"] != lead["event_uid"]):
        return _blank("live_oa_agenda_or_event_identity_changed")
    loc = live.get("location")
    if not isinstance(loc, dict):
        return _blank("live_oa_location_missing")
    source_point = (loc.get("latitude"), loc.get("longitude"))
    location = location_from_proof(
        venue_proof, lead.get("city_unverified"),
        lead.get("venue_unverified"), today, source_point)
    if location is None:
        return _blank("independent_venue_evidence_missing_or_changed")
    rights = review_event_rights(live, today)
    if not rights["licensed_factual_reuse_confirmed"]:
        return _blank("factual_reuse_license_or_attribution_missing")
    slug = live.get("slug")
    if (not isinstance(slug, str)
            or not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,139}", slug)):
        return _blank("untrusted_canonical_openagenda_slug")
    oa_link = (
        "https://openagenda.com/" + lead["agenda_slug"] +
        "/events/" + str(lead["event_uid"]) + "_" + slug
    )
    oa_lead = {
        "source_url": oa_link, "external_id": str(lead["event_uid"]),
        "date_start": date_start, "date_end": date_start,
        "title": lead["title"], "city": lead["city_unverified"],
        "venue": lead["venue_unverified"],
    }
    direct = review_direct_v2(
        oa_lead, live,
        {"agenda_uid": lead["agenda_uid"], "agenda_slug": lead["agenda_slug"],
         "timezone": live.get("timezone")},
        location, today,
    )
    if (not direct["source_evidence_structurally_valid"]
            or direct["event_kind"] != "single_explicit_dated_occurrence"):
        return _blank("live_oa_occurrence_or_geometry_not_confirmed")
    # All observed sessions for this ONE date must agree with today's
    # authenticated OA API response. Never infer unspecified times.
    intervals = [x for x in live.get("timings", []) if (
        isinstance(x, dict)
        and isinstance(x.get("begin"), str)
        and x["begin"][:10] == date_start)]
    if (len(intervals) != len(selected)
            or {(x["begin"], x["end"]) for x in intervals}
            != {(x["begin"], x["end"]) for x in selected}
            or len(direct["explicit_local_times_for_candidate_day"])
               != len(selected)):
        return _blank("source_exact_sessions_changed")
    city = lead["city_unverified"]
    try:
        directory = directory_reader(city)
    except (OSError, TimeoutError, ValueError, TypeError, KeyError):
        return _blank("dila_municipality_unavailable")
    if approved_municipal_page_host(official_url, city, directory) is None:
        return _blank("unknown_municipal_official_source")
    # Official source is authenticated BEFORE reading content; never
    # trust an arbitrary OA or organizer URL to mint a host authority.
    try:
        html = municipal_reader(official_url)
    except (OSError, TimeoutError, ValueError, TypeError, KeyError):
        return _blank("first_party_municipal_page_unavailable")
    if not isinstance(html, str):
        return _blank("first_party_municipal_page_unavailable")
    visible = visible_unlisted_sessions(html, lead, selected)
    if visible["exact_visible_session_claims_unverified"] != len(selected):
        return _blank("municipal_exact_session_title_venue_or_family_unproved")
    # Family access must not be contradicted by school-only or private
    # eligibility. Public attendanceMode is also checked by OA adapter.
    if NOT_PUBLIC_ACCESS.search(norm(html)) or not visible["family_audience_visible"]:
        return _blank("not_confirmed_public_family_access")
    title = _french_text(live, "title")
    desc = _french_text(live, "description") + " " + _french_text(live, "longDescription")
    category = category_for(title, desc)
    if category is None:
        return _blank("musical_editorial_scope_not_confirmed")
    department, region = loc.get("adminLevel2"), loc.get("adminLevel1")
    if not all(type(x) is str and x.strip() for x in (department, region)):
        return _blank("missing_live_admin_boundaries")
    # All public fields are factual and sanitized. No copied copy or image.
    event = {
        "id": "openagenda-" + str(lead["event_uid"]) + "-" + date_start,
        "title": title,
        "category": category[0], "category_label": category[1],
        "date_start": date_start, "date_end": date_start,
        "time": " ; ".join(direct["explicit_local_times_for_candidate_day"]),
        "city": city, "department": department, "region": region,
        "venue": lead["venue_unverified"],
        "source_url": official_url,
        "source_label": rights["attribution_display"],
        "verified_at": today.isoformat(), "geo_verified_at": today.isoformat(),
        "geo_precision": "venue",
        "lat": location["lat"], "lng": location["lng"],
    }
    fields = set().union(*(set(x) for x in baseline["events"]))
    cats = {x["category"] for x in baseline["events"]}
    structural, _ = valid(event, cats, fields, today)
    if not structural:
        return _blank("legacy_public_contract_rejected_candidate")
    key = event["id"]
    signature = (canonical_event_title(event), norm(event["city"]),
                 norm(event["venue"]))
    # A published multi-day card blocks any extracted duplicate day.
    if key in current:
        return _blank("already_published_event_uid_day")
    for existing in published["events"]:
        if not isinstance(existing, dict):
            return _blank("invalid_catalogue_record")
        same = (canonical_event_title(existing), norm(existing.get("city")),
                norm(existing.get("venue"))) == signature
        if not same:
            continue
        try:
            if (date.fromisoformat(existing["date_start"]) <= day <=
                    date.fromisoformat(existing["date_end"])):
                return _blank("published_semantic_or_date_range_duplicate")
        except (KeyError, ValueError, TypeError):
            return _blank("published_date_range_invalid")
    # Rehearse the *actual existing* append-only merge in memory, with a
    # checker tied to this very invocation's fresh independent evidence.
    # A serialized candidate or a user-provided boolean can NEVER supply
    # this transient verification closure. No patch is persisted.
    patch = {
        "schema": "ptitesondes.patch.v1", "generated_at": today.isoformat(),
        "safe_to_publish": False,
        "source": {"url": ORIGIN, "version": 3,
                   "updated_at": baseline["updated_at"],
                   "events_count": len(baseline["events"])},
        "checks": {"ids_unique": True,
                   "official_sources_verified": True,
                   "no_production_changes": True},
        "additions": [event], "updates": [], "deferred": [],
    }
    def witness_checked(candidate, originals):
        from ptitesondes_shared_venue_location_evidence import (
            location_from_proof,
        )
        exact_location = location_from_proof(
            venue_proof, candidate.get("city"), candidate.get("venue"),
            today, (candidate.get("lat"), candidate.get("lng")))
        ok = candidate == event and exact_location is not None
        return ok, ("source municipale DILA + séances exactes + GPS "
                    "indépendant + licence Etalab vérifiés en mémoire"
                    if ok else "candidate différent des preuves indépendantes")
    try:
        merged, audit = merge(
            baseline, published, patch, today, checker=witness_checked)
    except (ValueError, KeyError, TypeError):
        return _blank("existing_append_only_publisher_policy_rejected")
    if (audit.get("ajoutes") != 1
            or len(merged["events"]) != len(published["events"]) + 1
            or merged["events"][-1]["id"] != event["id"]):
        return _blank("existing_publisher_rehearsal_not_single_append")
    # Never return or write the merged public catalogue.
    return {
        **_blank("full_openworld_municipal_rehearsal_only"),
        "candidate": event,
        "open_license_credit_present": True,
        "independent_venue_correlated": True,
        "municipal_program_exact_sessions": len(selected),
        "published_duplicate_checked": True,
        "private_rehearsal_positive": True,
        "publisher_policy_rehearsal_accepted": True,
        "preview_additions": 1,
    }
