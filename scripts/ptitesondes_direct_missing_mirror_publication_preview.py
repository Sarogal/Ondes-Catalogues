#!/usr/bin/env python3
"""Private, non-publishing OA-direct -> existing catalogue schema proposal.

A proven exact-UID ODS absence is a routing condition, NEVER evidence of
publication rights. This adapter composes the existing direct source,
organizer-session, sealed municipality/IGN venue and merge-policy validators.
No GitHub, network writer, scheduler, patch schema or publisher is available.
"""
from datetime import date
from copy import deepcopy

from merge_policy import byid, historical_event_unchanged, valid
from official_organizer_proof import canonical_event_title
from proof import norm
from ptitesondes_candidate_promotion import (
    SCHOOL_ONLY_TIMES, category_for, covered_by_published_range,
)
from ptitesondes_openagenda_v2_direct_evidence import _fr
from ptitesondes_openagenda_v2_preintegration import review_missing_mirror_source
from ptitesondes_shared_venue_location_evidence import location_from_proof

SCHEMA = "ptitesondes.oa2.missing_mirror_private_proposal_preview.v1"


def preview_missing_mirror_proposal(
        lead, curated_agenda, location_proof, today, public_read_key,
        baseline, published, organizer_registry, organizer_page,
        *, institutional_page=None, ods_probe=None, agenda_reader=None,
        event_reader=None):
    """Prepare one schema-valid *unapproved* event from fresh source evidence.

    The venue must be minted in trusted memory, not provided as an intake dict,
    and need not be on the static whitelist. Organizer HTML and agenda registry
    must originate from independently fetched/pinned sources; these are NOT
    accepted from the private backlog. Every candidate goes through the same
    historic and published catalogue constraints as the existing promoter.

    The return value cannot be passed to merge_policy.merge (different schema,
    no 'additions' and no approval). Final rights, age/access, human trust
    policy and independent publisher checks remain separate.
    """
    base = {
        "schema": SCHEMA, "mode": "private_proposal_preview_only",
        "state": "hold", "reason": "invalid_or_unreviewed_inputs",
        "publication_ready": False, "publisher_connected": False,
        "approval_granted": False, "public_writes": 0,
    }
    if (not isinstance(lead, dict) or type(today) is not date
            or not isinstance(baseline, dict)
            or not isinstance(published, dict)
            or not isinstance(baseline.get("events"), list)
            or not isinstance(published.get("events"), list)
            or not isinstance(baseline.get("updated_at"), str)
            or not isinstance(organizer_registry, dict)
            or not isinstance(organizer_page, dict)
            or not isinstance(curated_agenda, dict)):
        return base
    try:
        historic = byid(baseline)
        existing = byid(published)
        if any(k not in existing or
               not historical_event_unchanged(v, existing[k])
               for k, v in historic.items()):
            return dict(base, reason="historical_catalogue_mismatch")
        # A candidate cannot be admitted when metadata fields/categories
        # cannot be derived from the immutable historic catalogue.
        fields = set().union(*(set(ev) for ev in baseline["events"]))
        categories = {ev["category"] for ev in baseline["events"]}
        if not fields or not categories:
            return dict(base, reason="missing_reference_schema")
    except (ValueError, TypeError, KeyError):
        return dict(base, reason="invalid_catalogue_structure")

    # Factory-only, sealed, fresh venue proof. The final source coordinate
    # agreement is independently enforced again by review_direct_v2.
    location = location_from_proof(
        location_proof, lead.get("city"), lead.get("venue"), today)
    if location is None:
        return dict(base, reason="independent_venue_proof_missing_or_stale")

    evidence = {}
    def sink(api_event, direct, organizer, identity):
        # Only the source reader inside review_missing_mirror_source can call
        # this after the exact ODS probe and direct/organizer prevalidation.
        evidence.update({
            "event": deepcopy(api_event), "direct": deepcopy(direct),
            "organizer": deepcopy(organizer), "identity": deepcopy(identity),
        })

    route = review_missing_mirror_source(
        lead, curated_agenda, location, today, public_read_key,
        published["events"], ods_probe=ods_probe,
        agenda_reader=agenda_reader, event_reader=event_reader,
        institutional_page=institutional_page,
        organizer_registry=organizer_registry, organizer_page=organizer_page,
        _source_sink=sink,
    )
    if route.get("route") != "direct_source_candidate_for_remaining_gates":
        return dict(base, reason="direct_source_" +
                    str(route.get("reason", "unverified"))[:100])
    if not evidence:
        return dict(base, reason="direct_source_snapshot_missing")

    source = evidence["event"]
    direct = evidence["direct"]
    organizer = evidence["organizer"]
    if (not isinstance(organizer, dict)
            or organizer.get("official_session_evidence_consistent") is not True
            or organizer.get("organizer_ownership_attested") is not False
            or organizer.get("rights_reviewed") is not False
            or organizer.get("approval_granted") is not False
            or organizer.get("public_writes") != 0
            or evidence["identity"].get("identity_consistent") is not True
            or direct.get("source_evidence_structurally_valid") is not True
            or direct.get("event_kind") != "single_explicit_dated_occurrence"):
        return dict(base, reason="independent_organizer_session_required")

    # Never infer unknown administrative labels from a municipality name, and
    # never copy place coordinates from the untrusted OpenAgenda source.
    place = source.get("location")
    title = _fr(source, "title")
    description = " ".join(_fr(source, key) for key in (
        "description", "longDescription"))
    category = category_for(title, description)
    if not category:
        return dict(base, reason="outside_historic_music_editorial_categories")
    if (not isinstance(place, dict)
            or not all(isinstance(place.get(key), str)
                       and place[key].strip()
                       for key in ("adminLevel1", "adminLevel2", "adminLevel4", "name"))):
        return dict(base, reason="administrative_location_unknown")
    clocks = direct.get("explicit_local_times_for_candidate_day")
    if (not isinstance(clocks, list) or not clocks
            or len(set(clocks)) != len(clocks)
            or not all(isinstance(t, str) and len(t) == 5 and
                       t[:2].isdigit() and t[2] == ":" and t[3:].isdigit()
                       for t in clocks)):
        return dict(base, reason="session_times_missing")
    # Public school-only slots never become family events, even if the
    # organiser page corroborates the public family sessions in the series.
    restricted = SCHOOL_ONLY_TIMES.get(
        (lead["external_id"], lead["date_start"]), frozenset())
    if any(clock in restricted for clock in clocks):
        return dict(base, reason="restricted_school_session_requires_split")

    proposal = {
        "id": "openagenda-" + lead["external_id"] + "-" + lead["date_start"],
        "title": title.strip(),
        "category": category[0], "category_label": category[1],
        "date_start": lead["date_start"], "date_end": lead["date_start"],
        "time": ", ".join(sorted(clocks)),
        "city": place["adminLevel4"], "department": place["adminLevel2"],
        "region": place["adminLevel1"], "venue": place["name"],
        "source_url": lead["source_url"],
        "source_label": curated_agenda["agenda_slug"],
        "verified_at": today.isoformat(),
        "geo_verified_at": today.isoformat(),
        "geo_precision": "venue",
        "lat": location["lat"], "lng": location["lng"],
    }
    signature = (canonical_event_title(proposal), norm(proposal["city"]),
                 norm(proposal["venue"]), proposal["date_start"])
    if (proposal["id"] in existing
            or covered_by_published_range(lead, published["events"])
            or any((canonical_event_title(old), norm(old.get("city")),
                    norm(old.get("venue")), old.get("date_start")) == signature
                   for old in published["events"])
            or any(old.get("source_url") == proposal["source_url"]
                   and old.get("date_start") == proposal["date_start"]
                   for old in published["events"])):
        return dict(base, reason="already_published")
    ok, reason = valid(proposal, categories, fields, today)
    if not ok:
        return dict(base, reason="merge_policy_" + reason[:110])
    return {
        **base, "state": "candidate_requires_final_gates",
        "reason": "source_organizer_geography_and_schema_prevalidated",
        "proposal": proposal,
        "independent_venue_checked": True,
        "independent_organizer_sessions_checked": True,
        "historic_and_published_dedup_checked": True,
        "merge_policy_schema_checked": True,
        "remaining_gates": (
            "independent_rights_and_organizer_ownership",
            "age_price_registration_public_access",
            "separate_final_publisher_proof_and_approval",
        ),
    }
