"""Verified open-world research -> legacy append-only Publisher, no allowlists.

An intake dossier is only a RESEARCH REQUEST. This module re-reads the live
OpenAgenda event, DILA municipal authority, exact named venue, independent
BAN/OSM geography and the event organizer's dated municipal programme. It
does not accept caller-supplied boolean approvals, GPS or source authority.

Nothing is written here. run_cloud_sync may pass the returned patch and checker
to merge_policy.merge in the SAME process. A serialized patch alone cannot
replay that checker: production-side verification MUST be rerun.
"""
from copy import deepcopy
from datetime import date
from urllib.parse import urlsplit

from merge_policy import merge, PUBLISHABLE_CHILD_ARTS
from proof import norm
from proof_text import verify_event as legacy_verify_event
from ptitesondes_dila_municipal_domains import (
    approved_municipal_page_host, fetch_dila,
)
from ptitesondes_delegated_source_authority import (
    mint_delegated_venue_source_proof,
)
from ptitesondes_secondary_municipal_site_proof import (
    mint_secondary_municipal_host_proof,
)
from ptitesondes_generic_venue_ign_corroboration import fetch_ign
from ptitesondes_generic_venue_osm_preflight import fetch_overpass
from ptitesondes_open_world_municipal_bootstrap import _safe_research_lead
from ptitesondes_open_world_release_rehearsal import (
    rehearse_open_world_municipal_event,
)
from ptitesondes_openagenda_v2_direct_evidence import (
    read_direct_agenda_v2, read_direct_v2, _valid_public_read_key,
)
from ptitesondes_shared_venue_location_evidence import (
    _coordinates, mint_private_location_proof,
)
from ptitesondes_unnumbered_official_geo_proof import (
    mint_private_unnumbered_location_proof,
)
from ptitesondes_municipal_event_venue_ban import (
    mint_municipal_event_location_proof,
)
from ptitesondes_unlisted_source_safe_recheck import read_unknown_https

MAX_DOSSIERS = 30
DOSSIER_KEYS = frozenset({
    "lead", "date_start", "official_event_url", "official_venue_url",
})
SOURCE_REFERENCE_FIELD = "municipal_source_reference_url"


def _safe_dossier(dossier, today):
    if (type(dossier) is not dict
            or set(dossier) not in (DOSSIER_KEYS,
                                   DOSSIER_KEYS | {SOURCE_REFERENCE_FIELD})
            or not _safe_research_lead(dossier["lead"], today)
            or not isinstance(dossier["date_start"], str)):
        return False
    try:
        day = date.fromisoformat(dossier["date_start"])
    except ValueError:
        return False
    if not today <= day <= today.fromordinal(today.toordinal() + 184):
        return False
    for field in ("official_event_url", "official_venue_url",
                  SOURCE_REFERENCE_FIELD):
        if field not in dossier:
            continue
        value = dossier[field]
        if not isinstance(value, str) or len(value) > 1800:
            return False
        try:
            url = urlsplit(value)
        except ValueError:
            return False
        if (url.scheme != "https" or not url.hostname or url.username
                or url.password or url.fragment or url.port not in (None, 443)
                or url.path in ("", "/")):
            return False
    return True


def prepare_open_world_patch(
        reference, published, private_patch, today, public_key, *,
        agenda_reader=read_direct_agenda_v2,
        event_reader=read_direct_v2,
        directory_reader=fetch_dila,
        official_reader=read_unknown_https,
        ign_reader=fetch_ign,
        osm_reader=fetch_overpass,
        legacy_checker=legacy_verify_event):
    """Return an expanded private patch plus its *ephemeral* live checker.

    This can be passed directly to the existing append-only merge() but must
    never be persisted with a forged 'verified' flag. Every admitted event is
    tied to the exact candidate reconstructed in this invocation.
    """
    if type(today) is not date or not isinstance(private_patch, dict):
        raise ValueError("invalid_open_world_publisher_inputs")
    research = private_patch.get("open_world_research", [])
    if not isinstance(research, list) or len(research) > MAX_DOSSIERS:
        raise ValueError("invalid_or_unpartitioned_open_world_queue")
    if any(not _safe_dossier(row, today) for row in research):
        raise ValueError("invalid_private_open_world_dossier")
    for reader in (agenda_reader, event_reader, directory_reader,
                   official_reader, ign_reader, osm_reader, legacy_checker):
        if not callable(reader):
            raise ValueError("missing_independent_source_reader")
    if not isinstance(private_patch.get("additions"), list):
        raise ValueError("private_patch_additions_missing")
    output = deepcopy(private_patch)
    # Never serialize untrusted research URLs into a public catalogue or log.
    output.pop("open_world_research", None)
    checked = {}
    report = {
        "dossiers": len(research), "admitted_to_merge": 0,
        "held": 0, "held_reason_counts": {},
        "publication_complete": False,
    }

    def held(reason):
        report["held"] += 1
        report["held_reason_counts"][reason] = (
            report["held_reason_counts"].get(reason, 0) + 1)

    # The normal legacy patch is valid without an OA secret. A queue is not:
    # no incomplete proof may advance on an unset or non-public API key.
    if research and not _valid_public_read_key(public_key):
        for _ in research:
            held("openagenda_public_read_key_unavailable")
        return output, legacy_checker, report

    reserved_ids = {x.get("id") for x in output["additions"]
                    if isinstance(x, dict)}
    for dossier in research:
        lead = dossier["lead"]
        city, venue = lead.get("city_unverified"), lead.get("venue_unverified")
        if not isinstance(city, str) or not isinstance(venue, str):
            held("venue_research_identity_missing")
            continue
        event_url = dossier["official_event_url"]
        venue_url = dossier["official_venue_url"]
        try:
            # Authenticated municipal origin BEFORE reading unknown HTML.
            directory = directory_reader(city)
            if approved_municipal_page_host(
                    venue_url, city, directory) is None:
                held("independent_municipal_domain_unverified")
                continue
            source_proof = None
            if approved_municipal_page_host(
                    event_url, city, directory) is None:
                reference_url = dossier.get(SOURCE_REFERENCE_FIELD)
                if (reference_url is None
                        or approved_municipal_page_host(
                            reference_url, city, directory) is None):
                    held("independent_municipal_source_delegation_missing")
                    continue
                reference_html = official_reader(reference_url)
                source_proof = mint_delegated_venue_source_proof(
                    city, venue, event_url, directory,
                    reference_url, reference_html, today)
                if source_proof is None:
                    # Municipality-run secondary sites (e.g. culture calendars)
                    # need a DILA-site link PLUS their own legal declaration.
                    # A mere backlink or self-declared organizer is not enough.
                    source_proof = mint_secondary_municipal_host_proof(
                        city, event_url, directory,
                        reference_url, reference_html, today,
                        reader=official_reader)
                if source_proof is None:
                    held("independent_municipal_source_delegation_unconfirmed")
                    continue
            api_event = event_reader(
                lead["agenda_uid"], lead["event_uid"], public_key)
            loc = api_event.get("location") if isinstance(api_event, dict) else None
            source_point = (
                (loc.get("latitude"), loc.get("longitude"))
                if isinstance(loc, dict) else None)
            # Missing OA coordinates are not a reason to reject an exact
            # municipality-address + independent BAN venue proof. Partially
            # specified or malformed coordinates remain invalid.
            if _coordinates(source_point) is None:
                if source_point != (None, None):
                    held("live_oa_gps_invalid_or_partial")
                    continue
                source_point = None
            group = {"city": city, "venue": venue,
                     "key": [norm(city), norm(venue)],
                     "uids": [str(lead["event_uid"])]}
            official_venue_html = official_reader(venue_url)
            proof = mint_private_location_proof(
                group, directory, venue_url, official_venue_html,
                ign_reader, today, source_center=source_point)
            if proof is None:
                # Municipality may list the *event* and a named venue under
                # "Adresse — 1 esplanade ..." without JSON-LD or postcode.
                # BAN must return an exact numbered building point that
                # agrees independently with OA, never a town centroid.
                proof = mint_municipal_event_location_proof(
                    group, directory, venue_url, official_venue_html,
                    ign_reader, today, source_point)
            if proof is None:
                # An unnumbered public square/building can have a precise
                # official point or named-address/OSM proof. No center guess.
                proof = mint_private_unnumbered_location_proof(
                    group, directory, venue_url, official_venue_html,
                    osm_reader(source_point), source_point, today)
            if proof is None:
                held("fresh_independent_venue_proof_missing")
                continue
            validation = rehearse_open_world_municipal_event(
                lead, dossier["date_start"], event_url, proof,
                reference, published, today, public_key,
                agenda_reader=agenda_reader,
                event_reader=event_reader,
                directory_reader=directory_reader,
                municipal_reader=official_reader,
                source_host_proof=source_proof,
            )
        except (OSError, TimeoutError, ValueError, TypeError, KeyError,
                OverflowError, UnicodeError):
            held("source_provider_unavailable_or_invalid")
            continue
        if (validation.get("private_rehearsal_positive") is not True
                or validation.get("publisher_policy_rehearsal_accepted") is not True
                or validation.get("preview_additions") != 1
                or not isinstance(validation.get("candidate"), dict)):
            held("live_publisher_evidence_not_confirmed")
            continue
        candidate = validation["candidate"]
        if candidate.get("id") in checked or candidate.get("id") in reserved_ids:
            held("duplicate_private_open_world_id")
            continue
        checked[candidate["id"]] = candidate
        output["additions"].append(candidate)
        report["admitted_to_merge"] += 1

    def checked_by_live_evidence(candidate, originals):
        if (not isinstance(candidate, dict)
                or not isinstance(candidate.get("id"), str)):
            return False, "invalid_publisher_candidate"
        expected = checked.get(candidate["id"])
        if expected is not None:
            if candidate == expected:
                return True, "fully_rechecked_open_world_source_and_geo"
            return False, "open_world_event_differed_from_live_evidence"
        return legacy_checker(candidate, originals)

    # This unforgeable-in-the-private-patch, in-memory connection is
    # derived only from exact live candidates, never from a caller-provided
    # "approved" flag. The legacy checker cannot add categories.
    checked_by_live_evidence._verified_child_ids = frozenset(
        uid for uid, item in checked.items()
        if item.get("category") in PUBLISHABLE_CHILD_ARTS)
    return output, checked_by_live_evidence, report


def merge_verified_open_world(
        reference, published, private_patch, today, public_key, **readers):
    """One connected in-memory Publisher transaction; no filesystem writes."""
    patched, checker, report = prepare_open_world_patch(
        reference, published, private_patch, today, public_key, **readers)
    # Scope comes only from candidates reconstructed by the same live
    # verifier invocation. Neither the private patch nor a category claim
    # from OpenAgenda can authorize this extension.
    child_scopes = frozenset(
        candidate["category"] for candidate in patched["additions"]
        if (isinstance(candidate, dict)
            and candidate.get("id") in getattr(checker, "_verified_child_ids", ())
            and candidate.get("category") in PUBLISHABLE_CHILD_ARTS))
    result, audit = merge(
        reference, published, patched, today, checker=checker,
        verified_child_arts=child_scopes)
    # Even in a green workflow this does NOT claim Pages was deployed.
    report["publisher_accepted_new"] = audit["ajoutes"]
    report["publisher_deferred_new"] = len(audit["attente"])
    report["publication_complete"] = False
    return result, audit, report
