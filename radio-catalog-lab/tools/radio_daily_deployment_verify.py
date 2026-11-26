"""Read-only deployment acceptance contract for the isolated radio lab.

A caller injects a bounded public reader and independently obtained deployment
status. No network implementation, GitHub credentials, writes or real keys.
Git transfer success alone must never count as deployment acceptance.
"""
from dataclasses import dataclass

from radio_daily_baseline_verify import strict_json, verify_baseline
from radio_daily_git_lab_reader import read_snapshot
from radio_daily_logo_plan import PREVIEW_BASE
from radio_daily_publication_simulator import check_logo, inventory
from radio_daily_v9_generator import digest

ROOT = PREVIEW_BASE.removesuffix("objects/sha256/")
POINTER_URL = ROOT + "pointer.json"


@dataclass(frozen=True)
class PublicResponse:
    status: int
    effective_url: str
    content_type: str
    body: bytes


def verify_deployment(transport, *, deployment_commit, deployment_status,
                      fetch, expected_commit, bootstrap_sha, expected_sha,
                      expected_sequence, public_key, key_id):
    """Accept only exact Git bytes and independently visible signed resources.

    fetch(url, max_bytes) is a read-only injected adapter. It must enforce the
    limit during transport; this verifier also validates it after receipt.
    No retries or fallback to the prior pointer occur inside acceptance.
    """
    if deployment_status != "success" or deployment_commit != expected_commit:
        raise ValueError("expected deployment has not succeeded")
    selected = read_snapshot(transport, expected_commit=expected_commit,
        bootstrap_sha=bootstrap_sha, expected_sha=expected_sha,
        expected_sequence=expected_sequence, public_key=public_key, key_id=key_id)
    calls = 0

    def read(url, limit, mime):
        nonlocal calls
        response = fetch(url, limit)
        calls += 1
        if not isinstance(response, PublicResponse):
            raise ValueError("invalid public response")
        if type(response.status) is not int or response.status != 200:
            raise ValueError("public resource unavailable")
        if response.effective_url != url:
            raise ValueError("public resource redirected")
        if (not isinstance(response.content_type, str)
                or response.content_type.split(";", 1)[0].strip().lower() != mime):
            raise ValueError("unexpected public content type")
        if not isinstance(response.body, bytes) or not 0 < len(response.body) <= limit:
            raise ValueError("invalid public resource size")
        return response.body

    pointer = read(POINTER_URL, 16384, "application/json")
    if pointer != selected["pointer"]:
        raise ValueError("public pointer differs from expected Git release")
    p = strict_json(pointer)
    body = read(ROOT + p["content_path"], p["content_length"], "application/json")
    if body != selected["body"]:
        raise ValueError("public catalogue differs from expected Git release")
    doc = verify_baseline(pointer, body, expected_sha=selected["sha256"],
        expected_sequence=selected["sequence"], public_key=public_key, key_id=key_id)
    checked = {}
    for logo, _ in inventory(doc):
        url = logo["url"]
        if url not in checked:
            checked[url] = read(url, logo["byte_size"], logo["mime_type"])
        check_logo(logo, checked[url])
    if read(POINTER_URL, 16384, "application/json") != pointer:
        raise ValueError("public pointer changed during verification")
    if transport.head() != expected_commit:
        raise ValueError("Git head changed during deployment verification")
    return dict(schemaVersion=1, publicationAllowed=False, deploymentVerified=True,
                gitCommit=expected_commit, selectedSequence=selected["sequence"],
                selectedSha256=digest(body), verifiedLogoUrls=len(checked),
                publicReads=calls, simulated=True)
