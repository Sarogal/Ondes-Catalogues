"""Read-only private owner ATTESTATION of source/calendar + independent GPS registry.

This is *not* a digital signature, a publisher or a license to release.
A SHA-256 receipt binds exactly the evidence seen; GitHub's authenticated
private PR owner comment supplies both human authorship and server timestamp.
The official page/calendar are re-read, not accepted from a collector.

The registry is reviewed source metadata: this module does NOT remotely
re-verify the geographic provider (e.g., OSM). That remains an independent
pre-publication requirement. Neither collector timestamps nor a SHA digest
alone are treated as proof of review or source freshness.
"""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import math
import re
from urllib.parse import urlsplit

from proof import meters, norm
from ptitesondes_municipal_admission import (
    inspect_municipal_admission, read_official, github_read,
)
from ptitesondes_municipal_appendonly_dryrun import (
    _event_from_proposal, canonical_sha256,
)
from ptitesondes_municipal_human_decision import (
    API, APPROVER, canonical_digest, html_digest, request_digest,
    review_comments, validate_pr,
)
from ptitesondes_municipal_preflight import municipal_calendar_url
from venue_registry import VENUES, verified_location

SCHEMA = "ptitesondes.municipal_source_geo_attestation_check.v1"
RECEIPT_SCHEMA = "ptitesondes.municipal_source_geo_receipt.v1"
MAX_COMMENT_AGE_DAYS = 14
SHA256 = re.compile(r"[a-f0-9]{64}\Z")
ISO_UTC = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")
RECEIPT_FIELDS = frozenset({
    "schema", "mode", "review_id", "pr_number", "head_sha",
    "manifest_sha256", "candidate_sha256", "access_sha256",
    "catalogue_sha256", "event_html_sha256", "calendar_html_sha256",
    "calendar_url", "venue_registry_sha256",
    "venue_official_url", "venue_geo_url",
})


def attestation_comment_line(receipt, verb):
    """Exact GitHub owner decision; the comment is separate from APPROVE."""
    if verb not in ("ATTEST", "REVOKE"):
        raise ValueError("invalid_attestation_decision")
    if not isinstance(receipt, dict) or not isinstance(
        receipt.get("review_id"), str
    ) or not isinstance(receipt.get("head_sha"), str):
        raise ValueError("invalid_attestation_receipt")
    return (
        "PTITESONDES-MUNICIPAL-SOURCE-GEO-" + verb + "-V1 "
        + receipt["review_id"] + " " + canonical_digest(receipt)
        + " " + receipt["head_sha"]
    )


def _trusted_https(url):
    if not isinstance(url, str):
        return None
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or not parsed.hostname
                or parsed.username or parsed.password
                or parsed.port not in (None, 443)
                or parsed.fragment):
            return None
    except ValueError:
        return None
    return parsed.hostname


def _registry_entry(candidate, registry):
    """Exactly one immutable static record with two distinct provenance hosts.

    The real runtime uses the versioned public registry. Tests may inject
    synthetic records; that must never be mistaken for live GPS proof.
    """
    if not isinstance(registry, (list, tuple)):
        return None
    matches = []
    for record in registry:
        if not isinstance(record, dict):
            continue
        if norm(record.get("city")) != norm(candidate.get("city")):
            continue
        aliases = record.get("aliases")
        if (not isinstance(aliases, list) or not aliases
                or norm(candidate.get("venue")) not in {
                    norm(v) for v in aliases if isinstance(v, str)
                }):
            continue
        matches.append(record)
    if len(matches) != 1:
        return None
    record = matches[0]
    first = _trusted_https(record.get("official"))
    second = _trusted_https(record.get("geo_source"))
    if not first or not second or first == second:
        return None
    try:
        original_point = (float(candidate["lat"]), float(candidate["lng"]))
        registry_point = (float(record["lat"]), float(record["lng"]))
        if not all(math.isfinite(x) for x in original_point + registry_point):
            return None
        if meters(original_point, registry_point) > 65:
            return None
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    return record


def _receipt_matches(receipt, manifest, candidate, access, catalogue,
                     event_html, calendar_html, record):
    if (not isinstance(receipt, dict) or set(receipt) != RECEIPT_FIELDS
            or receipt.get("schema") != RECEIPT_SCHEMA
            or receipt.get("mode") != "request_private_source_geo_attestation"
            or not isinstance(record, dict)):
        return False
    try:
        date_value = date.fromisoformat(candidate["date_start"])
        calendar_url = municipal_calendar_url(date_value)
        expected = {
            "review_id": candidate["review_id"],
            "pr_number": manifest["pr_number"],
            "head_sha": manifest["head_sha"],
            "manifest_sha256": request_digest(manifest),
            "candidate_sha256": canonical_digest(candidate),
            "access_sha256": canonical_digest(access),
            "catalogue_sha256": canonical_digest(catalogue),
            "event_html_sha256": html_digest(event_html),
            "calendar_html_sha256": html_digest(calendar_html),
            "calendar_url": calendar_url,
            "venue_registry_sha256": canonical_digest(record),
            "venue_official_url": record["official"],
            "venue_geo_url": record["geo_source"],
        }
    except (KeyError, ValueError, TypeError, OverflowError):
        return False
    return (receipt["calendar_url"] == candidate.get("calendar_url")
            and all(receipt.get(k) == v for k, v in expected.items())
            and all(
                isinstance(receipt.get(k), str) and
                SHA256.fullmatch(receipt[k]) is not None
                for k in (
                    "manifest_sha256", "candidate_sha256", "access_sha256",
                    "catalogue_sha256", "event_html_sha256",
                    "calendar_html_sha256", "venue_registry_sha256",
                )
            ))


def _last_owner_attestation(receipt, manifest, token, github_get, now):
    """Verify private PR metadata, owner identity, rights and GitHub time."""
    if not token:
        return False, "authenticated_private_token_missing"
    pr = github_get(API + f"/pulls/{manifest['pr_number']}", token)
    validate_pr(pr, manifest)
    decisions = []
    approve = attestation_comment_line(receipt, "ATTEST")
    revoke = attestation_comment_line(receipt, "REVOKE")
    for item in review_comments(manifest, token, github_get):
        if (not isinstance(item, dict)
                or item.get("body") not in (approve, revoke)
                or type(item.get("id")) is not int
                or item["id"] <= 0):
            continue
        user = item.get("user")
        if (not isinstance(user, dict)
                or user.get("login") != APPROVER
                or user.get("type") != "User"
                or item.get("author_association") != "OWNER"):
            continue
        decisions.append(item)
    if not decisions:
        return False, "private_owner_source_geo_attestation_absent"
    rights = github_get(API + "/collaborators/" + APPROVER + "/permission", token)
    if (not isinstance(rights, dict)
            or rights.get("permission") not in ("admin", "maintain")):
        return False, "private_owner_permission_unverified"
    last = max(decisions, key=lambda c: c["id"])
    if last["body"] == revoke:
        return False, "private_owner_source_geo_attestation_revoked"
    created_at = last.get("created_at")
    if not isinstance(created_at, str) or not ISO_UTC.fullmatch(created_at):
        return False, "github_attestation_timestamp_missing"
    try:
        timestamp = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        return False, "invalid_github_attestation_timestamp"
    if not timedelta(0) <= now - timestamp <= timedelta(days=MAX_COMMENT_AGE_DAYS):
        return False, "github_attestation_stale_or_future"
    return True, None


def inspect_source_geo_attestation(
    catalogue, review, access, manifest, receipt, today, *,
    token=None, source_get=read_official, github_get=github_read,
    geo_check=verified_location, registry=None, now=None,
):
    """An additional PRIVATE release prerequisite; never a public grant.

    The source evidence is re-read exactly once per URL, including the dated
    municipal calendar. The existing #332 gate must pass first, with an
    authenticated event approval and a separate access decision if needed.
    """
    if type(today) is not date:
        raise ValueError("invalid_attestation_day")
    if now is None:
        now = datetime.now(timezone.utc)
    if (type(now) is not datetime or now.tzinfo is None
            or now.utcoffset() is None):
        raise ValueError("invalid_authenticated_clock")
    if (not isinstance(review, dict)
            or not isinstance(review.get("candidates"), list)
            or len(review["candidates"]) != 1
            or not isinstance(access, dict)
            or not isinstance(access.get("reviewed"), list)
            or len(access["reviewed"]) != 1
            or not isinstance(manifest, dict)):
        raise ValueError("invalid_private_attestation_bundle")
    candidate = review["candidates"][0]
    condition = access["reviewed"][0]
    if not isinstance(candidate, dict) or not isinstance(condition, dict):
        raise ValueError("invalid_private_occurrence")
    old = deepcopy(catalogue)
    expected_hash = canonical_sha256(catalogue)
    blocked = set()
    live_bytes = {}
    chosen_registry = VENUES if registry is None else registry

    def read_once(url):
        if url not in live_bytes:
            live_bytes[url] = source_get(url)
        return live_bytes[url]

    try:
        # Verifies official event + calendar, age, dates, approvals and GPS.
        admission = inspect_municipal_admission(
            catalogue, review, access, manifest, today,
            token=token, source_get=read_once,
            github_get=github_get, geo_check=geo_check,
        )
        if (admission.get("technical_admission_diagnostic_passed") is not True
                or admission.get("publication_ready") is not False
                or admission.get("public_writes") != 0):
            blocked.add("prior_private_admission_not_verified")
        if admission.get("catalogue_sha256") != expected_hash:
            blocked.add("catalogue_not_bound_to_admission")

        record = _registry_entry(candidate, chosen_registry)
        if record is None:
            blocked.add("independent_static_registry_missing_or_inconsistent")
        else:
            day = date.fromisoformat(candidate["date_start"])
            calendar_url = municipal_calendar_url(day)
            if not _receipt_matches(
                    receipt, manifest, candidate, condition, catalogue,
                    read_once(candidate["official_event_url"]),
                    read_once(calendar_url), record):
                blocked.add("source_calendar_or_registry_receipt_mismatch")
        if not blocked:
            authenticated, why = _last_owner_attestation(
                receipt, manifest, token, github_get, now,
            )
            if not authenticated:
                blocked.add(why)
    except (KeyError, TypeError, ValueError, OSError, UnicodeError):
        blocked.add("source_or_private_attestation_unverifiable")

    if catalogue != old or canonical_sha256(catalogue) != expected_hash:
        raise ValueError("catalogue_mutated_during_source_geo_attestation")
    return {
        "schema": SCHEMA,
        "mode": "private_source_geo_evidence_diagnostic_only",
        "official_event_and_calendar_rechecked": (
            candidate.get("official_event_url") in live_bytes
            and candidate.get("calendar_url") in live_bytes
        ),
        "registry_checked_against_versioned_static_entry": (
            "independent_static_registry_missing_or_inconsistent" not in blocked
        ),
        "authenticated_private_attestation_passed": not blocked,
        "github_comment_timestamp_required": True,
        "maximum_attestation_age_days": MAX_COMMENT_AGE_DAYS,
        "attestation_is_not_digital_signature": True,
        "geo_provider_not_refetched": True,
        "blockers": sorted(blocked),
        "production_publisher_not_connected": True,
        "publication_ready": False,
        "approval_granted_to_publisher": False,
        "historical_records_modified": 0,
        "historical_records_deleted": 0,
        "public_writes": 0,
    }
