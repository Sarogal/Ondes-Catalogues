"""Role-scoped configuration for a future protected laboratory publisher.

Explicit mappings from trusted jobs only: no implicit environment reads,
secret provisioning, workflow dispatch or publication activation.
The caller must enforce GitHub environment/runner permissions independently.
"""
import base64
import re
from collections.abc import Mapping

from radio_daily_baseline_verify import PUBLIC_KEY
from radio_daily_v9_generator import digest
from radio_daily_protected_signer import load_signer
from radio_daily_github_executor import transmit_github, _credential
from radio_daily_github_json_reader import GitHubJSONReader
from radio_daily_github_readback import GitHubReadback

SIGNING_ENV = "radio-lab-signing"
PUBLISHER_ENV = "radio-lab-transport"
READBACK_ENV = "radio-lab-readback"
ROLES = {
    "collector": (None, frozenset()),
    "signer": (SIGNING_ENV, frozenset({"RADIO_LAB_ENCRYPTED_KEY", "RADIO_LAB_PASSPHRASE"})),
    "publisher": (PUBLISHER_ENV, frozenset({"RADIO_LAB_WRITE_TOKEN"})),
    "readback": (READBACK_ENV, frozenset({"RADIO_LAB_READ_TOKEN"})),
}
REPO_ID = 1438875064
REPO = "Sarogal/Ondes-Catalogues"
REF = "refs/heads/feature/radio-daily-discovery-lab-20261120"


def validate_job(role, *, context, reviewed_sha, secrets):
    """Reject wrong roles, extra secret inputs and unreviewed execution context.

    Values in context must come from trusted workflow metadata; this check is
    not a substitute for protected environments or token permission scopes.
    """
    if role not in ROLES or not isinstance(context, Mapping) or not isinstance(secrets, Mapping):
        raise ValueError("invalid role configuration")
    environment, required = ROLES[role]
    if (not isinstance(reviewed_sha, str) or not re.fullmatch(r"[a-f0-9]{40}", reviewed_sha)
            or context.get("repository") != REPO
            or type(context.get("repository_id")) is not int or context["repository_id"] != REPO_ID
            or context.get("ref") != REF or context.get("sha") != reviewed_sha
            or context.get("event") != "workflow_dispatch"
            or context.get("environment") != environment
            or context.get("role") != role):
        raise ValueError("unreviewed laboratory job context")
    if set(secrets) != required:
        raise ValueError("missing or cross-role secret configuration")
    if any(not isinstance(v, str) or not v for v in secrets.values()):
        raise ValueError("empty or invalid role credential")
    if role == "signer" and secrets["RADIO_LAB_ENCRYPTED_KEY"] == secrets["RADIO_LAB_PASSPHRASE"]:
        raise ValueError("distinct signing credentials required")
    return None


def _pin(public_key, key_id):
    if not isinstance(public_key, str) or not isinstance(key_id, str):
        raise ValueError("independent laboratory public pin required")
    try:
        raw = base64.b64decode(public_key, validate=True)
    except (ValueError, TypeError):
        raise ValueError("invalid laboratory public pin") from None
    if (len(raw) != 32 or base64.b64encode(raw).decode("ascii") != public_key
            or public_key == PUBLIC_KEY or key_id != "radio-lab-" + digest(raw)[:24]):
        raise ValueError("invalid laboratory public pin")


def signing_job(*, context, reviewed_sha, secrets, public_key, key_id):
    validate_job("signer", context=context, reviewed_sha=reviewed_sha, secrets=secrets)
    _pin(public_key, key_id)
    return load_signer(secrets["RADIO_LAB_ENCRYPTED_KEY"],
        secrets["RADIO_LAB_PASSPHRASE"].encode("utf-8"),
        expected_public_key=public_key, expected_key_id=key_id)


def readback_job(*, context, reviewed_sha, secrets):
    validate_job("readback", context=context, reviewed_sha=reviewed_sha, secrets=secrets)
    return GitHubReadback(GitHubJSONReader(token=secrets["RADIO_LAB_READ_TOKEN"]))


def publisher_job(source, store, plan, *, context, reviewed_sha, secrets,
                  read_head, read_tree, authorized=False):
    validate_job("publisher", context=context, reviewed_sha=reviewed_sha, secrets=secrets)
    if authorized is not True:
        raise ValueError("explicit laboratory transfer authorization required")
    token = secrets["RADIO_LAB_WRITE_TOKEN"]
    _credential(token)
    return transmit_github(source, store, plan, read_head=read_head,
        read_tree=read_tree, write_token=token, authorized=True)
