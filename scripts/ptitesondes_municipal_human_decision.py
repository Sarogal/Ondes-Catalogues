"""Read-only verification of an explicit HUMAN decision for a municipal outing.

WARNING: this checker NEVER approves publication, creates a patch or writes to
GitHub. The actual private-PR metadata, comments and permissions must be read
from the authenticated GitHub API; collector-provided approved flags are never
trusted. A human decision is only one prerequisite for a future release gate.
"""
import argparse
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, HTTPRedirectHandler, build_opener

SCHEMA = "ptitesondes.municipal_private_human_approval_check.v1"
MANIFEST_SCHEMA = "ptitesondes.municipal_private_approval_request.v1"
REPOSITORY = "Sarogal/PtitesOndes"
APPROVER = "Sarogal"
API = "https://api.github.com/repos/" + REPOSITORY
H = re.compile(r"[a-f0-9]{64}\Z")
GIT_SHA = re.compile(r"[a-f0-9]{40}\Z")
REVIEW_ID = re.compile(r"municipal-gosier-[1-9]\d{0,11}-\d{4}-\d{2}-\d{2}\Z")
FIELDS = frozenset((
    "schema", "mode", "review_id", "pr_number", "head_sha",
    "candidate_sha256", "access_sha256", "event_html_sha256",
    "catalogue_sha256", "date_start", "official_event_url",
))
MAX_PAGE = 100
MAX_BYTES = 500_000


def canonical_digest(document):
    return hashlib.sha256(json.dumps(
        document, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False
    ).encode("utf-8")).hexdigest()


def html_digest(html):
    if not isinstance(html, str):
        raise ValueError("invalid_verified_source")
    return hashlib.sha256(html.encode("utf-8")).hexdigest()


def request_digest(manifest):
    # Include exact evidence blob hashes, private PR head and occurrence.
    return canonical_digest(manifest)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def github_read(url, token):
    if not token:
        raise ValueError("missing_private_read_token")
    # Hard-coded exact private repository: never fetch an input-supplied URL.
    if not isinstance(url, str) or not url.startswith(API + "/"):
        raise ValueError("github_api_endpoint_not_allowed")
    req = Request(url, headers={
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "PtitesOndesMunicipalPrivateApprovalReadOnly/1.0",
    }, method="GET")
    with build_opener(NoRedirect).open(req, timeout=15) as resp:
        if resp.geturl() != url:
            raise ValueError("github_redirect_not_allowed")
        if "json" not in resp.headers.get("Content-Type", "").lower():
            raise ValueError("github_content_type_not_json")
        body = resp.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValueError("github_reply_too_large")
    return json.loads(body.decode("utf-8"))


def validated_manifest(manifest, candidate, access, event_html, catalogue):
    if (not isinstance(manifest, dict) or set(manifest) != FIELDS
            or manifest.get("schema") != MANIFEST_SCHEMA
            or manifest.get("mode") != "request_human_review_no_publication"):
        raise ValueError("invalid_private_review_manifest")
    rid = manifest.get("review_id")
    pr = manifest.get("pr_number")
    sha = manifest.get("head_sha")
    if (not isinstance(rid, str) or not REVIEW_ID.fullmatch(rid)
            or type(pr) is not int or not 1 <= pr <= 1_000_000
            or not isinstance(sha, str) or not GIT_SHA.fullmatch(sha)):
        raise ValueError("invalid_private_review_identity")
    for key in (
        "candidate_sha256", "access_sha256", "event_html_sha256",
        "catalogue_sha256",
    ):
        if not isinstance(manifest.get(key), str) or not H.fullmatch(manifest[key]):
            raise ValueError("missing_private_evidence_digest")
    if not isinstance(candidate, dict) or not isinstance(access, dict):
        raise ValueError("missing_private_evidence")
    if (candidate.get("review_id") != rid or access.get("review_id") != rid
            or candidate.get("date_start") != manifest["date_start"]
            or candidate.get("official_event_url") != manifest["official_event_url"]
            or access.get("official_event_url") != manifest["official_event_url"]
            or access.get("date_start") != manifest["date_start"]):
        raise ValueError("unbound_private_occurrence")
    try:
        if date.fromisoformat(manifest["date_start"]).isoformat() != manifest["date_start"]:
            raise ValueError("invalid_iso_date")
    except (ValueError, TypeError):
        raise ValueError("invalid_private_occurrence_date")
    if (candidate.get("approved") is not False
            or candidate.get("safe_to_publish") is not False
            or access.get("approved") is not False
            or access.get("safe_to_publish") is not False):
        raise ValueError("source_cannot_self_approve")
    observed = {
        "candidate_sha256": canonical_digest(candidate),
        "access_sha256": canonical_digest(access),
        "event_html_sha256": html_digest(event_html),
        "catalogue_sha256": canonical_digest(catalogue),
    }
    for field, value in observed.items():
        if manifest[field] != value:
            raise ValueError("private_evidence_changed_" + field)
    return rid


def validate_pr(pr, manifest):
    if not isinstance(pr, dict):
        raise ValueError("invalid_github_pr")
    try:
        allowed = (
            pr.get("number") == manifest["pr_number"]
            and pr.get("state") == "open"
            and pr.get("merged_at") is None
            and pr["head"]["sha"] == manifest["head_sha"]
            and pr["head"]["repo"]["full_name"] == REPOSITORY
            and pr["base"]["repo"]["full_name"] == REPOSITORY
            and pr["base"]["ref"] == "main"
        )
    except (KeyError, TypeError):
        allowed = False
    if not allowed:
        raise ValueError("github_private_pr_head_or_repository_changed")


def decision_line(manifest, verb):
    if verb not in ("APPROVE", "REVOKE"):
        raise ValueError("unsupported_decision")
    return ("PTITESONDES-MUNICIPAL-" + verb + "-V1 "
            + manifest["review_id"] + " "
            + request_digest(manifest) + " "
            + manifest["head_sha"])


def review_comments(manifest, token, get):
    pr_number = manifest["pr_number"]
    all_comments = []
    for page in range(1, 11):
        url = API + f"/issues/{pr_number}/comments?per_page={MAX_PAGE}&page={page}"
        result = get(url, token)
        if not isinstance(result, list) or len(result) > MAX_PAGE:
            raise ValueError("invalid_github_comment_page")
        all_comments.extend(result)
        if len(result) < MAX_PAGE:
            return all_comments
    raise ValueError("too_many_github_comments_fail_closed")


def audit_human_decision(manifest, candidate, access, event_html, catalogue,
                         token, get=github_read):
    """Reports presence of a genuine private human decision; NEVER a release."""
    rid = validated_manifest(manifest, candidate, access, event_html, catalogue)
    if not isinstance(token, str) or not token:
        raise ValueError("missing_private_read_token")
    pr = get(API + f"/pulls/{manifest['pr_number']}", token)
    validate_pr(pr, manifest)
    comments = review_comments(manifest, token, get)
    expected_approve = decision_line(manifest, "APPROVE")
    expected_revoke = decision_line(manifest, "REVOKE")
    candidates = []
    for comment in comments:
        if not isinstance(comment, dict) or comment.get("body") not in (
                expected_approve, expected_revoke):
            continue
        actor = comment.get("user")
        if (not isinstance(actor, dict)
                or actor.get("login") != APPROVER
                or actor.get("type") != "User"
                or comment.get("author_association") != "OWNER"
                or type(comment.get("id")) is not int):
            continue
        candidates.append(comment)
    candidates.sort(key=lambda c: c["id"])
    approved = False
    if candidates:
        permission = get(API + "/collaborators/" + APPROVER + "/permission", token)
        if (not isinstance(permission, dict)
                or permission.get("permission") not in ("admin", "maintain")):
            raise ValueError("approval_actor_permission_not_verified")
        approved = candidates[-1]["body"] == expected_approve
    return {
        "schema": SCHEMA, "mode": "private_human_decision_check_only",
        "review_id": rid,
        "human_approval_evidence": approved,
        "last_decision": "authenticated_approval" if approved
                        else ("revoked_or_absent" if candidates else "absent"),
        "publication_ready": False, "approval_granted_to_publisher": False,
        "public_writes": 0,
    }


def main():
    p = argparse.ArgumentParser()
    for key in ("manifest", "candidate", "access", "event-html", "catalogue", "output"):
        p.add_argument("--" + key, type=Path, required=True)
    a = p.parse_args()
    if a.output.exists():
        raise ValueError("refuse_overwriting_existing_private_report")
    def load(path):
        return json.loads(path.read_text(encoding="utf-8"))
    status = audit_human_decision(
        load(a.manifest), load(a.candidate), load(a.access),
        a.event_html.read_text(encoding="utf-8"), load(a.catalogue),
        os.environ.get("PRIVATE_INTAKE_READ_TOKEN"),
    )
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(
        json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # Identifiers and source URLs remain in the private report only.
    print(json.dumps({"human_approval_evidence": status["human_approval_evidence"],
                      "publication_ready": False, "public_writes": 0}))


if __name__ == "__main__":
    main()
