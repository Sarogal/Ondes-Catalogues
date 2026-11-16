"""Isolated municipal admission gate (NOT installed in the public publisher).

The existing OpenAgenda merge, proof_text and public category policy remain
unaltered. This gate checks an occurrence against first-party municipal HTML,
the reviewed geographic registry and an authenticated private GitHub decision.
It never creates ptitesondes.patch.v1, additions or catalogue writes.
"""
from copy import deepcopy
from datetime import date
import hashlib
import json

from merge_policy import byid, valid
from ptitesondes_nonmusic_release_contract import TYPES, matching_category
from ptitesondes_municipal_preflight import audit_municipal, read_official
from ptitesondes_municipal_human_decision import (
    API, APPROVER, audit_human_decision, github_read, request_digest,
    review_comments,
)
from ptitesondes_municipal_appendonly_dryrun import (
    _event_from_proposal, _overlaps_publication, canonical_sha256,
)
from venue_registry import verified_location

SCHEMA = "ptitesondes.municipal_admission_diagnostic.v1"
# These are the deliberately unimplemented publication barriers in the older
# preflight; no unexpected official-evidence failure can be overlooked.
EXPECTED_PREVIEW_BLOCKERS = frozenset({
    "municipal_public_prevalidator_not_activated",
    "private_manual_approval_not_present",
    "frontend_v172_category_filter_unverified",
    "category_not_accepted_by_current_public_contract",
    "access_information_requires_manual_review",
    "editorial_conditions_required",
    "conditions_explicit_recheck_required",
})


def editorial_decision_line(manifest, verb):
    """Exact private-PR statement for deliberately unknown access details.

    This is not a waiver of a known contradictory price or registration rule.
    It only accepts displaying a source link without making any price claim.
    """
    if verb not in ("SOURCE_ONLY", "REVOKE"):
        raise ValueError("unsupported_editorial_decision")
    return ("PTITESONDES-MUNICIPAL-UNKNOWN-ACCESS-" + verb + "-V1 "
            + manifest["review_id"] + " "
            + request_digest(manifest) + " " + manifest["head_sha"])


def authenticated_source_only_decision(manifest, token, get):
    """Read latest owner decision from the private PR, including revocation.

    Caller must first run audit_human_decision, which validates PR SHA, source
    evidence, permissions and the exact immutable manifest.
    """
    comments = review_comments(manifest, token, get)
    yes = editorial_decision_line(manifest, "SOURCE_ONLY")
    revoke = editorial_decision_line(manifest, "REVOKE")
    decisions = []
    for item in comments:
        if not isinstance(item, dict) or item.get("body") not in (yes, revoke):
            continue
        actor = item.get("user")
        if (not isinstance(actor, dict)
                or actor.get("login") != APPROVER
                or actor.get("type") != "User"
                or item.get("author_association") != "OWNER"
                or type(item.get("id")) is not int):
            continue
        decisions.append(item)
    if not decisions:
        return False
    rights = get(API + "/collaborators/" + APPROVER + "/permission", token)
    if (not isinstance(rights, dict)
            or rights.get("permission") not in ("admin", "maintain")):
        raise ValueError("editorial_actor_permission_not_verified")
    decisions.sort(key=lambda x: x["id"])
    return decisions[-1]["body"] == yes


def explicit_municipal_category_valid(event, catalogue, today):
    """Opt-in structural validation; NEVER changes merge_policy.merge().

    Exactly four reviewed categories, not an allowlist inferred by modifying
    historical records. The real public publisher still rejects these.
    """
    if (not isinstance(event, dict)
            or event.get("category") not in TYPES
            or event.get("category_label") != TYPES[event["category"]]
            or not matching_category(event.get("title"), event["category"])):
        return False, "municipal_category_not_explicitly_reviewed"
    historical = byid(catalogue)
    fields = set().union(*(set(row) for row in historical.values()))
    categories = {row["category"] for row in historical.values()}
    if set(TYPES) & categories:
        # No smuggling extra allowed categories through a forged reference.
        return False, "municipal_category_already_in_historical_reference"
    return valid(event, categories | set(TYPES), fields, today)


def inspect_municipal_admission(catalogue, review, access, manifest, today,
                                token=None, source_get=read_official,
                                github_get=github_read,
                                geo_check=verified_location):
    """Return a private, read-only diagnostic for ONE Gosier occurrence.

    No boolean supplied by a collector is ever considered an approval.
    The only human decision is re-read from the private GitHub PR, bound to
    the current evidence hashes, HTML and immutable catalogue snapshot.
    """
    if type(today) is not date:
        raise ValueError("invalid_admission_day")
    if (not isinstance(review, dict) or not isinstance(access, dict)
            or len(review.get("candidates", [])) != 1
            or len(access.get("reviewed", [])) != 1):
        raise ValueError("single_occurrence_required")
    before = deepcopy(catalogue)
    original_hash = canonical_sha256(catalogue)
    byid(catalogue)
    candidate = review["candidates"][0]
    condition = access["reviewed"][0]
    if not isinstance(candidate, dict) or not isinstance(condition, dict):
        raise ValueError("invalid_private_documents")

    # Cache identical official bytes for the preflight and the private-PR
    # manifest check. The source cannot change between those two checks.
    official = {}
    def read_once(url):
        if url not in official:
            official[url] = source_get(url)
        return official[url]

    preflight = audit_municipal(review, access, catalogue, today, get=read_once)
    rows = preflight["details_private_only"]
    if len(rows) != 1 or rows[0]["review_id"] != candidate["review_id"]:
        raise ValueError("independent_preflight_identity_mismatch")

    blockers = set(rows[0]["reasons"]) - EXPECTED_PREVIEW_BLOCKERS
    # The earlier read-only prevalidator already detects cross-feed
    # semantic/period collisions. Preserve its blocking reason and expose
    # one consistent admission-level duplicate code for downstream review.
    if blockers & {"already_public", "already_public_semantic_or_range"}:
        blockers.add("duplicate_published_across_sources")
    if candidate.get("review_id") != condition.get("review_id"):
        blockers.add("candidate_access_occurrence_mismatch")
    # Unknown prices/registration may never be displayed as "free" or
    # "without registration". The *distinct* SOURCE_ONLY decision below can
    # authorize a neutral link, while leaving actual conditions unknown.
    access_unknown = (condition.get("price_evidence") == "not_stated"
                      or condition.get("registration_evidence") == "not_stated")
    source_only_editorial = False
    approved_by_human = False
    if not blockers:
        try:
            if not token:
                blockers.add("authenticated_private_approval_missing")
            else:
                human = audit_human_decision(
                    manifest, candidate, condition,
                    official[candidate["official_event_url"]],
                    catalogue, token, get=github_get,
                )
                approved_by_human = human["human_approval_evidence"] is True
                if not approved_by_human:
                    blockers.add("authenticated_private_approval_absent_or_revoked")
                elif access_unknown:
                    # No "approved: true" field, title similarity or ordinary
                    # APPROVE comment can stand in for this separate decision.
                    source_only_editorial = authenticated_source_only_decision(
                        manifest, token, github_get
                    )
                    if not source_only_editorial:
                        blockers.add("editorial_unknown_conditions_pending")
        except (KeyError, ValueError, TypeError, OSError):
            blockers.add("private_evidence_or_decision_unverified")

    if not blockers:
        try:
            event = _event_from_proposal(
                candidate, today.isoformat(), today.isoformat()
            )
            if _overlaps_publication(event, catalogue["events"]):
                blockers.add("duplicate_published_across_sources")
            allowed, reason = explicit_municipal_category_valid(
                event, catalogue, today
            )
            if not allowed:
                blockers.add("explicit_municipal_contract_" + reason)
            geo_ok, _ = geo_check(event)
            if geo_ok is not True:
                blockers.add("independent_venue_registry_missing_or_different")
        except (KeyError, ValueError, TypeError, OverflowError):
            blockers.add("invalid_municipal_admission_fields")

    # Even if every prerequisite is satisfied, the production connector and
    # v173 frontend are NOT activated. Release is deliberately impossible here.
    if canonical_sha256(catalogue) != original_hash or catalogue != before:
        raise ValueError("historical_catalogue_mutated")
    return {
        "schema": SCHEMA,
        "mode": "isolated_readonly_never_publish",
        "catalogue_sha256": original_hash,
        "historical_preserved": len(catalogue["events"]),
        "historical_unchanged": True,
        "authenticated_human_evidence": approved_by_human,
        "authenticated_unknown_access_source_only_decision": source_only_editorial,
        "technical_admission_diagnostic_passed": not blockers,
        "blockers": sorted(blockers),
        "production_category_policy_unchanged": True,
        "frontend_v173_not_deployed": True,
        "publication_connector_not_activated": True,
        "publication_ready": False,
        "approval_granted_to_publisher": False,
        "historical_records_modified": 0,
        "historical_records_deleted": 0,
        "public_writes": 0,
    }
